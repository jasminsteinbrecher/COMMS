# MC-COMMS2

This project provides a simple interface for controlling multiple Mumble bots through a web page. It was
built for mission control style voice loops. The included `start_all.py` script launches the bots and the web
UI.

## 1. Install Python 3.11

This application **requires Python 3.11**. If you do not already have Python:

1. Go to https://www.python.org/downloads/release/python-3110/.
2. Scroll down and Download the installer for your operating system.
3. Run the installer. On Windows make sure **"Add Python to PATH"** is checked.
4. Open a new terminal/command prompt and run:
   ```bash
   python --version
   ```
   It should print `Python 3.11.0`.

## 2. Install the project

1. Download or clone this repository.
2. Open a terminal in the project folder.
3. Install the required Python packages (run again if you already installed earlier):
   ```bash
   python -m pip install -r requirements.txt
   ```

If `pip` is not recognised, reinstall Python and ensure that the option to add it to your
system `PATH` is enabled.

## 3. First run and configuration

Run the main script:
```bash
python start_all.py
```
On the first launch, a configuration web page will open automatically. Enter the
Mumble server address, port, optional server password, bot base name and choose your role. When you submit
that page a `run_config.json` file is created and the application will continue
running.

Subsequent launches will reuse the saved configuration and directly start the
bots and the web UI.

The web interface is available at [http://127.0.0.1:8080/](http://127.0.0.1:8080/).
Use it to join or leave loops and control bot audio.

## 4. Troubleshooting

If you see errors about missing packages, make sure you installed the
requirements with the correct Python 3.11 interpreter. You can explicitly call
`python3.11` instead of `python` if multiple Python versions are installed.

