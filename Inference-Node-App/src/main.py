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

WORKER_URL = "https://nodes.modulogical.com"

APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Modulogical" / "Inference Node"
APPDATA.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = APPDATA / "config.json"
NODE_FILE = APPDATA / "node.json"

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
                "logical_cores" :  psutil.cpu_count(logical=True),
                "physical_cores" : psutil.cpu_count(logical=False)
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
                        "logical_cores" :  psutil.cpu_count(logical=True),
                        "physical_cores" : psutil.cpu_count(logical=False)
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

# ---------- Load GPU data ---------- #

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
    log_event("Tunnel token saved locally; connectivity and routing are not configured yet.")


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
        "tunnel_status": node_data.get("tunnel_status", "not provisioned"),
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
    start_heartbeat_thread()
    import uvicorn
    # Disable Uvicorn's default dictConfig logging: its default formatter calls
    # sys.stderr.isatty(), but sys.stderr can be None in a windowed .exe.
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8765,
        log_level="warning",
        log_config=None,
        access_log=False,
    ))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait briefly for the local API to become available.
    for _ in range(50):
        try:
            if requests.get("http://127.0.0.1:8765/health", timeout=0.2).ok:
                break
        except requests.RequestException:
            time.sleep(0.1)

    try:
        import webview
        webview.create_window(
            "Modulogical Inference Node",
            "http://127.0.0.1:8765/",
            width=1180,
            height=780,
            min_size=(820, 600),
            background_color="#0b1020",
        )
        webview.start()
    except ImportError:
        log_event("pywebview is not installed; opening the dashboard in your default browser.", "warning")
        import webbrowser
        webbrowser.open("http://127.0.0.1:8765/")
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
