#!/usr/bin/env python3
import os
import time
import queue
import threading
import numpy as np
import sounddevice as sd
from flask import Flask, request, jsonify
import signal
import sys
from flask_cors import CORS

script_dir = os.path.dirname(__file__)
os.add_dll_directory(script_dir)

# --- Graceful Shutdown on SIGTERM/SIGINT ---
def handle_exit(signum, frame):
    print(f"Received signal {signum}. Exiting bot_server.py.")
    try:
        sd.stop()
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

# --- CERTIFICATE MANAGEMENT ---
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime

def ensure_bot_cert(bot_name):
    cert_dir = os.path.join(os.path.dirname(__file__), "certs")
    os.makedirs(cert_dir, exist_ok=True)
    certfile = os.path.join(cert_dir, f"{bot_name}.pem")
    keyfile  = os.path.join(cert_dir, f"{bot_name}-key.pem")
    if os.path.isfile(certfile) and os.path.isfile(keyfile):
        return certfile, keyfile
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"{}".format(bot_name))])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    with open(keyfile, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(certfile, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"[CERT] Generated new certificate for {bot_name}: {certfile}")
    return certfile, keyfile

# --- DEFAULT AUDIO DEVICES ---
devs = sd.query_devices()
DEFAULT_IN  = next(i for i,d in enumerate(devs) if d["max_input_channels"]>0)
DEFAULT_OUT = next(i for i,d in enumerate(devs) if d["max_output_channels"]>0)

# --- CLI ARGUMENTS ---
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--bot-name", required=True)
parser.add_argument("--api-port", required=True, type=int)
parser.add_argument("--server", required=True)
parser.add_argument("--port", required=True, type=int)
parser.add_argument("--password", default="")
args = parser.parse_args()

SERVER = args.server
PORT   = args.port
USER   = args.bot_name
PASSWORD = args.password

certfile, keyfile = ensure_bot_cert(USER)

# --- MUMBLE DEPENDENCIES ---
from pymumble_py3 import Mumble
from pymumble_py3.constants import (
    PYMUMBLE_CLBK_SOUNDRECEIVED,
    PYMUMBLE_CLBK_USERUPDATED,
    PYMUMBLE_CLBK_USERREMOVED,
)

class LoopBot:
    """
    Main class that manages Mumble connection, audio I/O, state, delay, and volume logic.
    """
    def __init__(self):
        self.dev_in    = DEFAULT_IN     # input device index
        self.dev_out   = DEFAULT_OUT    # output device index
        self.loop      = None           # currently joined loop (channel) name
        self.streaming = False          # True if currently "talking"
        self.status    = "Starting…"
        self._recv_q   = queue.Queue()  # queue for received PCM audio
        self.playback_volume = 1.0      # Output volume (0.0-2.0)
        self._connect_mumble()          # connect to Mumble server
        self._start_mic_stream()        # start microphone input stream
        self._start_playback_thread()   # start thread for playback
        self._users_by_channel = {}     # channel_id -> user count
        self._talkers = {}              # channel_name -> {user: last_time}

        # === DELAY feature (robust version) ===
        self.audio_delay_enabled = False        # if delay is active
        self.audio_delay_seconds = 3           # delay length (seconds)
        self.audio_delay_queue = queue.Queue() # queue for delayed audio
        self._delay_thread = threading.Thread(target=self._delay_audio_worker, daemon=True)
        self._delay_thread.start()

    def enable_audio_delay(self, seconds=3):
        self.audio_delay_enabled = True
        self.audio_delay_seconds = seconds
        # print(f"[DELAY] Enabled with {seconds}s")

    def disable_audio_delay(self):
        self.audio_delay_enabled = False
        # Immediately flush the queue
        flushed = 0
        while not self.audio_delay_queue.empty():
            try:
                self.audio_delay_queue.get_nowait()
                flushed += 1
            except Exception:
                break
        # print(f"[DELAY] Disabled. Flushed {flushed} audio chunks.")

    def _delay_audio_worker(self):
        while True:
            try:
                tstamp, pcm = self.audio_delay_queue.get()
                if not self.audio_delay_enabled:
                    # Discard all queued audio when delay is off
                    # print("[DELAY WORKER] Discarding chunk (delay is OFF)")
                    continue
                wait_needed = (tstamp + self.audio_delay_seconds) - time.time()
                if wait_needed > 0:
                    time.sleep(wait_needed)
                # Play out only if in "talking" mode
                if self.streaming and self.client and getattr(self.client, "sound_output", None):
                    try:
                        self.client.sound_output.add_sound(pcm)
                    except Exception as e:
                        print(f"[DELAY WORKER] Error playing sound: {e}")
            except Exception as e:
                # print(f"[DELAY WORKER ERROR] {e}")
                time.sleep(0.01)

    def _mic_callback(self, indata, frames, ti, status):
        if indata is None or len(indata) == 0:
            return
        try:
            pcm = (indata[:,0] * 32767).astype(np.int16).tobytes()
        except Exception as e:
            print(f"[MIC CALLBACK ERROR] Could not convert indata to PCM: {e}")
            return
        if self.audio_delay_enabled:
            self.audio_delay_queue.put((time.time(), pcm))
        elif self.streaming and self.client and getattr(self.client, "sound_output", None):
            try:
                self.client.sound_output.add_sound(pcm)
            except Exception as e:
                print(f"[AUDIO OUT ERROR] {e}")

    def _connect_mumble(self):
        kwargs = {
            "port": PORT,
            "reconnect": True,
            "certfile": certfile,
            "keyfile": keyfile,
        }
        if PASSWORD:
            kwargs["password"] = PASSWORD
        self.client = Mumble(SERVER, USER, **kwargs)
        self.client.callbacks.set_callback(PYMUMBLE_CLBK_USERUPDATED,  lambda u,e: self._update_user_map())
        self.client.callbacks.set_callback(PYMUMBLE_CLBK_USERREMOVED,  lambda u,e: self._update_user_map())
        self.client.set_receive_sound(True)
        self.client.callbacks.set_callback(
            PYMUMBLE_CLBK_SOUNDRECEIVED, self._on_sound_received
        )
        self.client.start()
        if hasattr(self.client, "undeafen"): self.client.undeafen()
        elif hasattr(self.client, "set_deaf"): self.client.set_deaf(False)
        if hasattr(self.client, "unmute"):   self.client.unmute()
        elif hasattr(self.client, "set_mute"): self.client.set_mute(False)
        for _ in range(20):
            if getattr(self.client, "connected", False): break
            time.sleep(0.2)
        else:
            raise RuntimeError("Mumble connect timeout")
        self.status = "Connected"
        self._update_user_map()

    def _on_sound_received(self, user, soundchunk):
        # Receive PCM from others, put to playback queue
        self._recv_q.put(soundchunk.pcm)
        try:
            uname = getattr(user, 'name', None) or user.get('name', '')
            ch_id = getattr(user, 'channel_id', None)
            if ch_id is None:
                ch_id = user.get('channel_id', None)
            ch_obj = self.client.channels.get(int(ch_id)) if ch_id is not None else None
            ch_name = ''
            if ch_obj is not None:
                ch_name = getattr(ch_obj, 'name', None) or ch_obj.get('name', '')
            if ch_name:
                self._talkers.setdefault(ch_name, {})[uname] = time.time()
        except Exception:
            pass

    def _start_mic_stream(self):
        self._mic_stream = sd.InputStream(
            device=self.dev_in,
            channels=1,
            samplerate=48000,
            blocksize=2048,
            latency=0.1,
            callback=self._mic_callback
        )
        self._mic_stream.start()

    def _playback_thread(self):
        """
        Background thread: plays back received PCM to output device,
        scaling by the current volume.
        """
        with sd.RawOutputStream(
            device=self.dev_out,
            channels=1,
            samplerate=48000,
            dtype="int16",
            blocksize=2048,
            latency=0.1
        ) as outstream:
            while True:
                pcm = self._recv_q.get()
                arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                arr *= self.playback_volume
                arr = np.clip(arr, -32768, 32767).astype(np.int16)
                outstream.write(arr.tobytes())

    def _start_playback_thread(self):
        t = threading.Thread(target=self._playback_thread, daemon=True)
        t.start()

    def set_input(self, idx):
        self._mic_stream.close()
        self.dev_in = idx
        self.status = f"Input → {idx}"
        self._start_mic_stream()

    def set_output(self, idx):
        self.dev_out = idx
        self.status  = f"Output → {idx}"

    def _move_to_loop(self):
        target = self.loop or "Root"
        for cid, ch in self.client.channels.items():
            name = getattr(ch, 'name', None) or ch.get('name', '')
            if name == target:
                ch.move_in()
                break

    def join(self, loop_name):
        self.loop   = loop_name
        self.status = f"Listen → {loop_name or 'Root'}"
        self._move_to_loop()

    def leave(self):
        self.join(None)

    def talk(self):
        self.streaming = True
        self.status    = f"Talk → {self.loop or 'Root'}"
        if self.audio_delay_enabled:
            while not self.audio_delay_queue.empty():
                try:
                    self.audio_delay_queue.get_nowait()
                except Exception:
                    break

    def mute(self):
        self.streaming = False
        self.status    = f"Muted → {self.loop or 'Root'}"

    def stop(self):
        self.mute()
        try: self._mic_stream.close()
        except: pass
        self.status = "Stopped"

    def set_volume(self, vol):
        """
        Set playback volume (0.0-2.0).
        """
        self.playback_volume = max(0.0, min(2.0, float(vol)))

    def _update_user_map(self):
        channel_users = {}
        try:
            chans = {int(cid): ch for cid, ch in self.client.channels.items()}
        except Exception:
            chans = {}
        users = getattr(self.client, 'users', {})
        for user in users.values():
            try:
                ch_id = getattr(user, 'channel_id', None)
                if ch_id is None:
                    ch_id = user.get('channel_id', None)
                if ch_id is not None:
                    channel_users.setdefault(ch_id, 0)
                    channel_users[ch_id] += 1
            except Exception:
                continue
        self._users_by_channel = channel_users

    def get_channel_user_count(self, name):
        for cid, ch in self.client.channels.items():
            chname = getattr(ch, 'name', None) or ch.get('name', '')
            if chname == name:
                return self._users_by_channel.get(int(cid), 0)
        return 0

    def report(self):
        user_counts = {}
        talkers = {}
        for cid, ch in self.client.channels.items():
            chname = getattr(ch, 'name', None) or ch.get('name', '')
            user_counts[chname] = self._users_by_channel.get(int(cid), 0)
            recent = []
            users = self._talkers.get(chname, {})
            now = time.time()
            for u, t in list(users.items()):
                if now - t < 1.0:
                    recent.append(u)
                else:
                    del users[u]
            if recent:
                talkers[chname] = recent
        return {
            'status':     self.status,
            'loop':       self.loop,
            'talking':    self.streaming,
            'device_in':  self.dev_in,
            'device_out': self.dev_out,
            'volume':     self.playback_volume,
            'user_counts': user_counts,
            'talkers':    talkers,
        }

# --- FLASK API SERVER ---
app = Flask(__name__)
CORS(app)
bot = LoopBot()

@app.route('/status')
def status():
    return jsonify(bot.report())

@app.route('/join', methods=['POST'])
def join():
    bot.join(request.json.get('loop'))
    return jsonify(ok=True)

@app.route('/leave', methods=['POST'])
def leave():
    bot.leave()
    return jsonify(ok=True)

@app.route('/talk', methods=['POST'])
def talk():
    bot.talk()
    return jsonify(ok=True)

@app.route('/mute', methods=['POST'])
def mute():
    bot.mute()
    return jsonify(ok=True)

@app.route('/device_in', methods=['POST'])
def device_in():
    bot.set_input(int(request.json['device']))
    return jsonify(ok=True)

@app.route('/device_out', methods=['POST'])
def device_out():
    bot.set_output(int(request.json['device']))
    return jsonify(ok=True)

@app.route('/stop', methods=['POST'])
def stop():
    bot.stop()
    return jsonify(ok=True)

@app.route('/users')
def users():
    users = []
    for user in getattr(bot.client, "users", {}).values():
        u_name = getattr(user, "name", None) or user.get("name")
        users.append(u_name)
    return jsonify(users=users)

@app.route('/delay_on', methods=['POST'])
def delay_on():
    data = request.get_json(silent=True) or {}
    seconds = data.get('seconds', 3)
    bot.enable_audio_delay(seconds)
    return jsonify(ok=True)

@app.route('/delay_off', methods=['POST'])
def delay_off():
    bot.disable_audio_delay()
    return jsonify(ok=True)

@app.route('/leave_after_delay', methods=['POST'])
def leave_after_delay():
    def delayed_leave():
        time.sleep(bot.audio_delay_seconds)
        bot.mute()
        bot.leave()
    threading.Thread(target=delayed_leave, daemon=True).start()
    return jsonify(ok=True)

@app.route('/mute_after_delay', methods=['POST'])
def mute_after_delay():
    def delayed_mute():
        time.sleep(bot.audio_delay_seconds)
        bot.mute()
    threading.Thread(target=delayed_mute, daemon=True).start()
    return jsonify(ok=True)

@app.route('/set_volume', methods=['POST'])
def set_volume():
    """
    Set the playback volume for this bot (0.0–1.0).
    """
    vol = float(request.json.get('volume', 1.0))
    bot.set_volume(vol)
    return jsonify(ok=True)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=args.api_port)
