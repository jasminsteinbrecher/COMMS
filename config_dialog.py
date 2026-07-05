import os
import json
import subprocess
import sys
import time
import webbrowser

CONFIG_FILE = "run_config.json"

ROLES = [
    "FLIGHT", "CAPCOM", "PRO", "BME", "EVA", "SCIENCE", "CONTACT", "AA"
]

PASSWORDS = {
    "FLIGHT":  "flight2026",
    "CAPCOM":  "capcom2026",
    "PRO":     "pro2026",
    "BME":     "bme2026",
    "EVA":     "eva2026",
    "SCIENCE": "science2026",
    "CONTACT": "contact2026",
    "AA":      "aa2026",
}

def verify_password(role, password):
    return PASSWORDS.get(role) == password


def read_config():
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        # Strip any password keys that may linger from old configs
        cfg.pop('password', None)
        cfg.pop('passwords', None)
        return cfg
    return None


def write_config(server, port, bot_base, role):
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "server": server,
            "port": port,
            "bot_base": bot_base,
            "role": role,
        }, f)


def get_config_from_dialog():
    """Launch web-based config UI (always — password validation is handled there)."""
    last_mtime = os.path.getmtime(CONFIG_FILE) if os.path.isfile(CONFIG_FILE) else 0

    server_py = os.path.join(os.path.dirname(__file__), "web_ui_server.py")
    proc = subprocess.Popen([sys.executable, server_py, "--config-only"])
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:8080/config")
    print("Waiting for configuration via web UI...")
    while True:
        time.sleep(1)
        if os.path.isfile(CONFIG_FILE) and os.path.getmtime(CONFIG_FILE) > last_mtime:
            break
    proc.terminate()
    return read_config()
