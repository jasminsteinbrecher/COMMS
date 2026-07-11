#!/usr/bin/env python3
import os, sys, time, wave, argparse
import numpy as np
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime
from pymumble_py3 import Mumble

script_dir = os.path.dirname(__file__)
os.add_dll_directory(script_dir)

# ------------------------------ SIGNAL HANDLING ------------------------------
import signal
def handle_exit(signum, frame):
    sys.exit(0)
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

# ------------------------------ CERTIFICATE ------------------------------
def ensure_bot_cert(bot_name):
    cert_dir = os.path.join(script_dir, "certs")
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
    return certfile, keyfile

# ------------------------------ ALARM PCM LOADER ------------------------------
def load_alarm_snippet(duration_seconds=10):
    alarm_path = os.path.join(script_dir, 'sounds', 'alarm.wav')
    with wave.open(alarm_path, 'rb') as wf:
        raw = wf.readframes(wf.getnframes())
    stereo = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
    mono = stereo.mean(axis=1).astype(np.int16)
    orig = np.arange(len(mono))
    target_len = int(len(mono) * 48000 / 44100)
    target = np.linspace(0, len(mono) - 1, target_len)
    resampled = np.interp(target, orig, mono).astype(np.int16)
    samples_needed = int(48000 * duration_seconds)
    if len(resampled) > samples_needed:
        resampled = resampled[:samples_needed]
    boosted = np.clip(resampled * 2.0, -32768, 32767).astype(np.int16)
    return boosted.tobytes()

# ------------------------------ MAIN ------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--password', default='')
    parser.add_argument('--channel', required=True)
    parser.add_argument('--loops', type=int, default=1)
    parser.add_argument('--duration', type=float, default=10.0)
    parser.add_argument('--stagger', type=float, default=0.0)
    parser.add_argument('--suffix', default='')
    args = parser.parse_args()

    if args.stagger > 0:
        time.sleep(args.stagger)

    base_name = f"ALARM_{args.channel.replace(' ', '_')}"
    bot_name = f"{base_name}_{args.suffix}" if args.suffix else base_name
    certfile, keyfile = ensure_bot_cert(base_name)
    alarm_pcm = load_alarm_snippet(args.duration)

    # Connect to Mumble
    kwargs = {
        "port": args.port,
        "reconnect": False,
        "certfile": certfile,
        "keyfile": keyfile,
    }
    if args.password:
        kwargs["password"] = args.password
    client = Mumble(args.server, bot_name, **kwargs)
    client.set_receive_sound(False)
    client.start()

    # Wait for connection
    for _ in range(30):
        if getattr(client, "connected", False):
            break
        time.sleep(0.2)
    else:
        print(f"[ALARM_BOT] {bot_name}: connect timeout")
        sys.exit(1)

    # Unmute / undeafen (actual protobuf commands via pymumble)
    if client.users.myself:
        client.users.myself.unmute()
        client.users.myself.undeafen()
    time.sleep(0.2)

    # Wait for channel list to populate, then find target channel
    target_ch = None
    for _ in range(50):
        for cid, ch in client.channels.items():
            ch_name = getattr(ch, 'name', None) or ch.get('name', '')
            if ch_name == args.channel:
                target_ch = ch
                break
        if target_ch:
            break
        time.sleep(0.2)
    if not target_ch:
        print(f"[ALARM_BOT] {bot_name}: channel '{args.channel}' not found")
        try:
            if hasattr(client, 'control_socket') and client.control_socket:
                client.control_socket.close()
        except Exception:
            pass
        sys.exit(1)

    target_ch.move_in()
    time.sleep(0.5)

    # Play alarm
    for _ in range(args.loops):
        if getattr(client, "sound_output", None):
            client.sound_output.add_sound(alarm_pcm)
        time.sleep(args.duration + 0.5)

    try:
        if hasattr(client, 'control_socket') and client.control_socket:
            client.control_socket.close()
    except Exception:
        pass
    time.sleep(0.3)
    sys.exit(0)

if __name__ == '__main__':
    main()
