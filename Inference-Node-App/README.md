# Modulogical Inference Node — desktop UI shell

This version keeps the Python backend in `src/main.py` and adds an HTML/CSS/JavaScript desktop dashboard in `src/ui/`.

## Run from source (Windows)

1. Install Python 3.11 or newer.
2. Open a terminal in this folder.
3. Run `py -m pip install -r requirements.txt`.
4. Run `py src/main.py`.

The app starts a local FastAPI service on `127.0.0.1:8765` and opens a pywebview desktop window. If pywebview is unavailable, it attempts to open the dashboard in the default browser.

## Build the executable

Run `build.bat` from Windows. The resulting executable is `dist\ModulogicalInferenceNode.exe`.

The HTML assets are bundled into the executable. User configuration remains in `%LOCALAPPDATA%\Modulogical\Inference Node`.

## Current UI features

- Dashboard with registration, Ollama, hardware, and node information
- Local inference test using the `/generate` endpoint
- Basic configuration editor for existing settings
- Session activity list
- Reconnect/registration attempt

## Important notes

- This is an initial UI shell, not yet the finished Worker integration.
- The settings UI stores preferences; it does not yet enforce CPU/GPU resource limits or implement Windows startup/tray behaviour.
- The local API binds to `127.0.0.1`, not the public network.
- The Worker URL and existing registration/heartbeat protocol are retained from the supplied backend.
- Before public distribution, add stronger local API authentication and review the Worker registration/heartbeat flow.
