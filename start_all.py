import os
import subprocess
import time
import sys
import psutil

from config_dialog import get_config_from_dialog
import webbrowser

DIR = os.path.dirname(os.path.abspath(__file__))

# Only prompt on first run, reuse config otherwise
print("Opening config dialog...")
config = get_config_from_dialog()
print("Config returned:", config)

SERVER = config['server']
PORT = config['port']
BOT_BASE = config['bot_base']
PASSWORD = config.get('password', '')

bots = [
    [sys.executable, os.path.join(DIR, "bot_server.py"), "--server", SERVER, "--port", str(PORT), "--bot-name", f"{BOT_BASE}", "--api-port", "6001"],
    [sys.executable, os.path.join(DIR, "bot_server.py"), "--server", SERVER, "--port", str(PORT), "--bot-name", f"{BOT_BASE}1", "--api-port", "6002"],
    [sys.executable, os.path.join(DIR, "bot_server.py"), "--server", SERVER, "--port", str(PORT), "--bot-name", f"{BOT_BASE}2", "--api-port", "6003"]
]

if PASSWORD:
    for cmd in bots:
        cmd.extend(["--password", PASSWORD])

procs = []
for cmd in bots:
    try:
        print(f"Starting bot: {cmd}")
        p = subprocess.Popen(cmd, cwd=DIR)
    except Exception as e:
        print(f"Could not start bot: {cmd}: {e}")
        continue
    procs.append(p)

time.sleep(2)

# start web UI server
ui_proc = subprocess.Popen([sys.executable, os.path.join(DIR, 'web_ui_server.py')], cwd=DIR)
time.sleep(1)
#  webbrowser.open('http://127.0.0.1:8080')

try:
    ui_proc.wait()
except KeyboardInterrupt:
    pass

for p in procs:
    try:
        print(f"Terminating bot process PID: {p.pid}")
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            print(f"Bot PID {p.pid} did not exit in time. Killing...")
            p.kill()
    except Exception as e:
        print(f"Error terminating bot process: {e}")

print("All bots terminated. Exiting app.")

try:
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        if proc.info['name'] and 'bot_server' in proc.info['name']:
            print(f"Forcibly killing leftover bot_server PID={proc.pid}")
            try:
                proc.kill()
            except Exception as e:
                print(f"Could not kill PID={proc.pid}: {e}")
except Exception as e:
    print(f"psutil cleanup failed: {e}")

print("All bots terminated. Exiting app.")
