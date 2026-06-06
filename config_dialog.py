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


def read_config():
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return None


def write_config(server, port, password, bot_base, role):
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "server": server,
            "port": port,
            "password": password,
            "bot_base": bot_base,
            "role": role,
        }, f)


def get_config_from_dialog():
    """Launch web-based config UI if no config file exists."""
    cfg = read_config()
    if cfg:
        return cfg

    server_py = os.path.join(os.path.dirname(__file__), "web_ui_server.py")
    proc = subprocess.Popen([sys.executable, server_py, "--config-only"])
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:8080/config")
    print("Waiting for configuration via web UI...")
    while not os.path.isfile(CONFIG_FILE):
        time.sleep(1)
    proc.terminate()
    return read_config()
