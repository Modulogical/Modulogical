from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import secrets
import requests
import json
from datetime import datetime, timezone
import os
import psutil
from pathlib import Path
import subprocess
import threading
import time
import sys
import logging
from collections import deque
import platform
#hi

app = FastAPI(title="Modulogical Inference Node")

# Keep the Python backend in this file; the desktop shell is served from ./ui.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UI_DIR = BASE_DIR / "ui"
APP_LOGS = deque(maxlen=100)
LOG_LOCK = threading.Lock()


def log_event(message: str, level: str = "info"):
    entry = {"time": datetime.now().astimezone().strftime("%H:%M:%S"), "level": level, "message": str(message)}
    with LOG_LOCK:
        APP_LOGS.appendleft(entry)
    # PyInstaller --windowed can set stdout/stderr to None on Windows.
    # Keep the UI log active without letting console logging crash the app.
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        try:
            print(f"[{entry['time']}] {message}", file=stream, flush=True)
        except (OSError, ValueError, AttributeError):
            pass


OLLAMA_URL = "http://localhost:11434/api/generate"

# Official Ollama for Windows installer. Downloaded on first launch if the
# local Ollama API is not already available.
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_INSTALLER = BASE_DIR / "bin" / "OllamaSetup.exe"
OLLAMA_INSTALL_LOCK = threading.Lock()
OLLAMA_INSTALL_STARTED = False


def ensure_ollama_runtime():
    """Launch Ollama if present; otherwise download and launch its official installer."""
    global OLLAMA_INSTALL_STARTED

    with OLLAMA_INSTALL_LOCK:
        if OLLAMA_INSTALL_STARTED:
            return
        OLLAMA_INSTALL_STARTED = True

    try:
        # If Ollama is already running, no download or installation is needed.
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.ok:
                log_event("Ollama runtime is already available.")
                return
        except requests.RequestException:
            pass

        if os.name != "nt":
            log_event("Automatic Ollama runtime installation currently supports Windows only.", "warning")
            return

        OLLAMA_INSTALLER.parent.mkdir(parents=True, exist_ok=True)
        if not OLLAMA_INSTALLER.exists() or OLLAMA_INSTALLER.stat().st_size < 1_000_000:
            temporary_path = OLLAMA_INSTALLER.with_suffix(".download")
            log_event("Downloading the official Ollama runtime installer...")
            try:
                with requests.get(OLLAMA_INSTALLER_URL, stream=True, timeout=(15, 180)) as response:
                    response.raise_for_status()
                    total = 0
                    with temporary_path.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 256):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > 1_000 * 1024 * 1024:
                                raise RuntimeError("Ollama installer exceeded the 1 GB safety limit.")
                            handle.write(chunk)
                if temporary_path.stat().st_size < 1_000_000:
                    raise RuntimeError("Downloaded Ollama installer was unexpectedly small.")
                temporary_path.replace(OLLAMA_INSTALLER)
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise

        log_event("Launching the Ollama installer. Follow its installation prompts to finish setup.")
        subprocess.Popen(
            [str(OLLAMA_INSTALLER)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(OLLAMA_INSTALLER.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        log_event(f"Could not download or launch the Ollama installer ({type(exc).__name__}).", "error")

WORKER_URL = "https://nodes.modulogical.com"

APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Modulogical" / "Inference Node"
APPDATA.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = APPDATA / "config.json"
NODE_FILE = APPDATA / "node.json"
CLOUDFLARED_DIR = APPDATA / "bin"
CLOUDFLARED_EXE = CLOUDFLARED_DIR / "cloudflared.exe"
TUNNEL_TOKEN_FILE = APPDATA / "cloudflared-token.txt"
CLOUDFLARED_DOWNLOAD_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
TUNNEL_PROCESS = None
TUNNEL_PROCESS_LOCK = threading.Lock()
TUNNEL_STATE = "not_started"

# ------------------------------------ Initialise/Load startup files ------------------------------------ #

# - Config Catch-all function - #
def config(): 
 if CONFIG_FILE.exists():
    with open(CONFIG_FILE, "r") as read_config:
        config_data=json.load(read_config)
    return config_data
 else: 
    with open(CONFIG_FILE, "w") as write_config:
        data={
    "registered" : 0,
    "resource_limits": {
        "cpu_percent": 50,
        "gpu_percent": 50,
        "max_concurrent_requests": 1,
        "idle_only": True
    },
    "inference": {
        "enabled_models": [],
        "allow_remote_inference": True
    },
    "network": {
        "auto_connect": True,
        "auto_start": True
    },
    "application": {
        "start_with_windows": True,
        "minimize_to_tray": True
    }
}
        json.dump(data, write_config, indent=4)
    return data
 
# - Node Catch-all function - #
def node():
 if NODE_FILE.exists():
    with open(NODE_FILE, "r") as read_node:
        node_data=json.load(read_node)
        with open(NODE_FILE, "w") as New_heartbeat:
            node_data.update({"last_heartbeat" : datetime.now().strftime("%H:%M:%S")})
            json.dump(node_data, New_heartbeat, indent=4)
            return node_data
 else: 
    with open(NODE_FILE, "w") as write_node:
     ram=psutil.virtual_memory()
     disk = psutil.disk_usage("C:\\")
     try: 
      data={
        "node_id" : f"node_{secrets.token_urlsafe(32)}",
        "node_secret" : "",
        "modulogical_id" : "",
        "hardware" : {
            "cpu" : {
                "logical_processors" : grab_cpu()["logical_processors"],
                "physical_cores" : grab_cpu()["physical_cores"],
                "name" : grab_cpu()["name"],
                "os" : grab_cpu()["os"]
            },
            "gpu" : {
                "name" : get_nvidia_gpus()[0]["name"],
                "vram_total_mb" : get_nvidia_gpus()[0]["vram_total_mb"]
            },
            "ram" : {
                "total_ram_gb" : round(ram.total / (1024 ** 3), 1)
            },
            "ssd" : {
                "total_gb" : round(disk.total / 1024**3,1),
                "free_gb" : round(disk.free / 1024**3,1)
            },
        }
    }
      json.dump(data, write_node, indent=4)
     except Exception:
        data={
                "node_id" : f"node_{secrets.token_urlsafe(32)}",
                "node_secret" : "",
                "modulogical_id" : "",
                "hardware" : {
                    "cpu" : {
                        "logical_cores" :  grab_cpu()["logical_processors"],
                        "physical_cores" : grab_cpu()["physical_cores"],
                        "name" : grab_cpu()["name"],
                        "os" : grab_cpu()["os"]
                    },
                    "gpu" : {
                        "name" : "couldn't get GPU",
                        "vram_total_mb" : "couldn't get GPU"
                    },
                    "ram" : {
                        "total_ram_gb" : round(ram.total / (1024 ** 3), 1)
                    },
                    "ssd" : {
                        "total_gb" : round(disk.total / 1024**3,1),
                        "free_gb" : round(disk.free / 1024**3,1)
                    },
                }
            }
        json.dump(data, write_node, indent=4)
    return data

# ---------- Load Telemetry data ---------- #

def get_nvidia_gpus():
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits"
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=True
        )

        gpus = []

        for line in result.stdout.strip().splitlines():
            name, total, free, used, utilisation = [
                value.strip() for value in line.split(",")
            ]

            gpus = [{
                "name": name,
                "vram_total_mb": int(total),
                "vram_free_mb": int(free),
                "vram_used_mb": int(used),
                "utilisation_percent": int(utilisation),
            }]

        return gpus

    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return []

def grab_cpu():
    try:
        result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 -ExpandProperty Name)"
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True
    )

        print(f"Exact CPU model: {result.stdout.strip()}")
        cpu_data={
            "name" : result.stdout.strip(),
            "os" : f"{platform.system()} {platform.release()}",
            "logical_processors": psutil.cpu_count(logical=True),
            "physical_cores" : psutil.cpu_count(logical=False),
            "current_frequency" : f"{psutil.cpu_freq().current:.0f} MHz"
        }
        return cpu_data
except Exception:
        return {}
    
# ---------------------------------------- Cloudflare Tunnel connector ---------------------------------------- #

def ensure_cloudflared() -> Path:
    """Download the official Windows x64 cloudflared connector if it is absent."""
    if os.name != "nt":
        raise RuntimeError("Automatic cloudflared installation currently supports Windows only.")
    if CLOUDFLARED_EXE.exists() and CLOUDFLARED_EXE.stat().st_size > 1_000_000:
        try:
            with CLOUDFLARED_EXE.open("rb") as handle:
                if handle.read(2) == b"MZ":
                    return CLOUDFLARED_EXE
        except OSError:
            pass
        CLOUDFLARED_EXE.unlink(missing_ok=True)

    CLOUDFLARED_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = CLOUDFLARED_EXE.with_suffix(".download")
    log_event("Downloading the official Cloudflare Tunnel connector (cloudflared)...")
    try:
        with requests.get(CLOUDFLARED_DOWNLOAD_URL, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            total = 0
            with temporary_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise RuntimeError("cloudflared download exceeded the 100 MB safety limit.")
                    handle.write(chunk)
        with temporary_path.open("rb") as handle:
            if handle.read(2) != b"MZ" or temporary_path.stat().st_size < 1_000_000:
                raise RuntimeError("Downloaded cloudflared file did not look like a valid Windows executable.")
        temporary_path.replace(CLOUDFLARED_EXE)
        log_event("cloudflared downloaded successfully.")
        return CLOUDFLARED_EXE
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _watch_cloudflared_output(process):
    """Read connector output without ever recording credentials or command arguments."""
    global TUNNEL_STATE
    try:
        for raw_line in iter(process.stdout.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if "registered tunnel connection" in lowered or "connection established" in lowered:
                TUNNEL_STATE = "connected"
                log_event("Cloudflare Tunnel connection established.")
            elif "failed to" in lowered or "error" in lowered:
                # Avoid dumping arbitrary connector output into the UI logs.
                log_event("cloudflared reported a connection error; check Cloudflare Tunnel logs.", "error")
        return_code = process.poll()
        if return_code is not None:
            TUNNEL_STATE = "offline"
            log_event(f"cloudflared exited (code {return_code}).", "error" if return_code else "warning")
    except Exception:
        TUNNEL_STATE = "unknown"


def start_cloudflared() -> bool:
    """Start the locally installed connector using the node's saved tunnel token."""
    global TUNNEL_PROCESS, TUNNEL_STATE
    with TUNNEL_PROCESS_LOCK:
        if TUNNEL_PROCESS is not None and TUNNEL_PROCESS.poll() is None:
            return True

        try:
            node_data = json.loads(NODE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log_event(f"Cannot start Cloudflare Tunnel: node credentials could not be read ({type(exc).__name__}).", "error")
            TUNNEL_STATE = "error"
            return False

        tunnel_token = node_data.get("tunnel_token")
        if not isinstance(tunnel_token, str) or not tunnel_token.strip():
            log_event("Cannot start Cloudflare Tunnel: no saved tunnel token is present.", "error")
            TUNNEL_STATE = "not_configured"
            return False

        try:
            connector = ensure_cloudflared()
            # Keep the token out of process command-line arguments. The file is
            # stored under the user's LocalAppData directory, not in app logs.
            TUNNEL_TOKEN_FILE.write_text(tunnel_token.strip(), encoding="utf-8")
            try:
                os.chmod(TUNNEL_TOKEN_FILE, 0o600)
            except OSError:
                pass
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            TUNNEL_PROCESS = subprocess.Popen(
                [str(connector), "tunnel", "--no-autoupdate", "run", "--token-file", str(TUNNEL_TOKEN_FILE)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                cwd=str(CLOUDFLARED_DIR),
            )
            TUNNEL_STATE = "starting"
            threading.Thread(target=_watch_cloudflared_output, args=(TUNNEL_PROCESS,), daemon=True).start()
            time.sleep(0.5)
            if TUNNEL_PROCESS.poll() is not None:
                TUNNEL_STATE = "offline"
                log_event(f"cloudflared exited immediately (code {TUNNEL_PROCESS.returncode}). Check the connector version and tunnel token.", "error")
                return False
            log_event("Cloudflare Tunnel connector started; waiting for Cloudflare to confirm a connection.")
            return True
        except Exception as exc:
            TUNNEL_STATE = "error"
            log_event(f"Could not start cloudflared ({type(exc).__name__}): {exc}", "error")
            return False


# ---------------------------------------- Registration ---------------------------------------- #

def register_node():
    config_data = config()
    if config_data.get("registered") == 1:
        log_event("Node is already registered.")
        return

    metadata = node()
    response = requests.post(
        f"{WORKER_URL}/v1/nodes/register",
        json=metadata,
        timeout=30,
    )

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.reason)
        except (ValueError, AttributeError):
            detail = response.reason
        raise RuntimeError(f"Node registration failed ({response.status_code}): {detail}")

    result = response.json()
    required = ("node_secret", "tunnel_id", "tunnel_token")
    missing = [key for key in required if not isinstance(result.get(key), str) or not result[key]]
    if missing:
        raise RuntimeError(
            "Worker registration response is missing required fields: " + ", ".join(missing)
        )

    # Persist both one-time credentials before marking the node registered.
    node_data = node()
    node_data["node_secret"] = result["node_secret"]
    node_data["tunnel_id"] = result["tunnel_id"]
    node_data["tunnel_token"] = result["tunnel_token"]
    node_data["tunnel_status"] = result.get("tunnel_status", "created")
    with open(NODE_FILE, "w", encoding="utf-8") as handle:
        json.dump(node_data, handle, indent=4)

    config_data = config()
    config_data["registered"] = 1
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(config_data, handle, indent=4)

    log_event(f"Node registered successfully. Tunnel provisioned: {result['tunnel_id']}")
    start_cloudflared()


# ---------------------------------------- Send Heartbeat ---------------------------------------- #

def send_heartbeat():
    HEARTBEAT_INTERVAL = 30

    url = f"{WORKER_URL}/v1/nodes/heartbeat"

    while True:
        config_data = config()
        if config_data.get("registered") != 1:
            log_event("Node is not registered; attempting registration.")
            try:
                register_node()
            except Exception as e:
                log_event(f"Registration failed: {e}", "error")

        # Reload persisted node credentials after registration so the first
        # successful registration can be used by this same heartbeat loop.
        node_data = {}
        if NODE_FILE.exists():
            try:
                node_data = json.loads(NODE_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                log_event(f"Could not read node configuration: {e}", "error")

        config_data = config()
        node_id = node_data.get("node_id")
        node_secret = node_data.get("node_secret")
        if config_data.get("registered") == 1 and node_data.get("tunnel_token"):
            start_cloudflared()
        if config_data.get("registered") == 1 and node_id and node_secret:
            try:
                metadata = {
                    "node_id": node_id,
                    "status": "online",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {node_secret}"},
                    json=metadata,
                    timeout=10
                )
                response.raise_for_status()
                log_event(f"Heartbeat acknowledged ({response.status_code}).")
                node_data = node()
                node_data["last_heartbeat"] = datetime.now().strftime("%H:%M:%S")
                with open(NODE_FILE, "w") as Write_node:
                    json.dump(node_data, Write_node, indent=4)
            except requests.RequestException as e:
                log_event(f"Heartbeat failed: {e}", "error")
        elif config_data.get("registered") == 1:
            log_event("Node is marked registered but its saved credentials are incomplete.", "error")

        time.sleep(HEARTBEAT_INTERVAL)


def start_heartbeat_thread():
    thread = threading.Thread(
        target=send_heartbeat,
        daemon=True
    )
    thread.start()


# ---------------------------------------- Classes ---------------------------------------- #

class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemma3:latest"
    temperature: float = 0.2
    stream: bool = True

# ---------------------------------------- Endpoints ---------------------------------------- #

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate")
def generate(details: GenerateRequest):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": details.model,
            "prompt": details.prompt,
            "stream": details.stream,
            "options": {
                "temperature": details.temperature,
                "repeat_penalty": 1.15,
                "repeat_last_n": 64
            }
        },
        stream=details.stream,
        timeout=None
    )

    if response.status_code != 200:
        return {
            "error": "Ollama request failed",
            "status": response.status_code,
            "detail": response.text
        }

    if not details.stream:
        return response.json()

    def stream():
        for line in response.iter_lines():
            if line:
                # Preserve Ollama's JSON-lines stream.
                yield line + b"\n"
    print("Generating")

    return StreamingResponse(stream(), media_type="application/x-ndjson")

# ---------------------------------------- Desktop UI and local status API ---------------------------------------- #

@app.get("/")
def desktop_home():
    index_file = UI_DIR / "index.html"
    if not index_file.exists():
        return {"error": "UI assets were not found", "expected": str(index_file)}
    return FileResponse(index_file)


@app.get("/api/status")
def api_status():
    config_data = config()
    node_data = {}
    if NODE_FILE.exists():
        try:
            node_data = json.loads(NODE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            node_data = {}

    ollama_online = False
    model_names = []
    try:
        ollama_response = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        ollama_online = ollama_response.ok
        if ollama_online:
            model_names = [item.get("name", "Unknown model") for item in ollama_response.json().get("models", [])]
    except requests.RequestException:
        pass

    registered = config_data.get("registered") == 1
    return {
        "app": "Modulogical Inference Node",
        "registered": registered,
        "node_id": node_data.get("node_id", ""),
        "tunnel_id": node_data.get("tunnel_id", ""),
        "tunnel_status": TUNNEL_STATE if node_data.get("tunnel_token") else node_data.get("tunnel_status", "not provisioned"),
        "cloudflared_installed": CLOUDFLARED_EXE.exists(),
        "last_heartbeat": node_data.get("last_heartbeat", "Never"),
        "hardware": node_data.get("hardware", {}),
        "ollama_online": ollama_online,
        "models": model_names,
        "config": config_data,
        "worker_url": WORKER_URL,
    }


@app.get("/api/logs")
def api_logs():
    with LOG_LOCK:
        return {"logs": list(APP_LOGS)}


@app.get("/api/config")
def api_get_config():
    return config()


@app.post("/api/config")
def api_update_config(payload: dict):
    """Update only recognised settings; secrets are never accepted from the UI."""
    current = config()
    allowed_sections = {
        "resource_limits": {"cpu_percent", "gpu_percent", "max_concurrent_requests", "idle_only"},
        "inference": {"enabled_models", "allow_remote_inference"},
        "network": {"auto_connect", "auto_start"},
        "application": {"start_with_windows", "minimize_to_tray"},
    }
    for section, allowed_keys in allowed_sections.items():
        incoming = payload.get(section)
        if isinstance(incoming, dict):
            target = current.setdefault(section, {})
            for key in allowed_keys:
                if key in incoming:
                    target[key] = incoming[key]
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=4)
    log_event("Settings saved.")
    return {"ok": True, "config": current}


@app.post("/api/reconnect")
def api_reconnect():
    def attempt():
        try:
            register_node()
        except Exception as exc:
            log_event(f"Registration attempt failed: {exc}", "error")
    threading.Thread(target=attempt, daemon=True).start()
    log_event("Registration/reconnect requested.")
    return {"ok": True, "message": "Connection attempt started."}


if UI_DIR.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIR / "assets", check_dir=False), name="assets")


def main():
    # Start the heartbeat/registration loop and local API before opening the window.
    threading.Thread(target=ensure_ollama_runtime, daemon=True).start()
    start_heartbeat_thread()
    import uvicorn
    # Disable Uvicorn's default dictConfig logging: its default formatter calls
    # sys.stderr.isatty(), but sys.stderr can be None in a windowed .exe.
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8001,
        log_level="warning",
        log_config=None,
        access_log=False,
    ))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait briefly for the local API to become available.
    for _ in range(50):
        try:
            if requests.get("http://127.0.0.1:8001/health", timeout=0.2).ok:
                break
        except requests.RequestException:
            time.sleep(0.1)

    try:
        import webview
        webview.create_window(
            "Modulogical Inference Node",
            "http://127.0.0.1:8001/",
            width=1180,
            height=780,
            min_size=(820, 600),
            background_color="#0b1020",
        )
        webview.start()
    except ImportError:
        log_event("pywebview is not installed; opening the dashboard in your default browser.", "warning")
        import webbrowser
        webbrowser.open("http://127.0.0.1:8001/")
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
