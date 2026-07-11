import os
import json
import subprocess
import sys
import time
import webbrowser

CONFIG_FILE = "run_config.json"

ROLES = [
    "FLIGHT", "CAPCOM", "PRO", "BME", "EVA", "SCIENCE", "CONTACT", "AA", "CMO"
]

PASSWORDS = {
    "FLIGHT":  "kP9!vX2$mL5*qR",
    "CAPCOM":  "3bF~7wK_2pZs+Q",
    "PRO":     "tN4#mY9.rV1=fX",
    "BME":     "wG6&xP3?zL8-qK",
    "EVA":     "8jD%2kC[9mB]5v",
    "SCIENCE": "4hS/7vF(2dT)9m",
    "CONTACT": "zB1@kM5_8xP2*r",
    "AA":      "9vY$3mC!7kR-2p",
    "CMO":     "4xG#8wQ!2mR-9k4"
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
