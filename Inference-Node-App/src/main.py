from fastapi import FastAPI
from fastapi.responses import StreamingResponse
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


app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/generate"

WORKER_URL = "https://nodes.modulogical.com"

APPDATA = Path(os.environ["LOCALAPPDATA"]) / "Modulogical" / "Inference Node"
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
        "last_heartbeat" : datetime.now().strftime("%H:%M:%S"),
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
     except Exception:
        data={
                "node_id" : f"node_{secrets.token_urlsafe(32)}",
                "node_secret" : "",
                "modulogical_id" : "",
                "last_heartbeat" : datetime.now().strftime("%H:%M:%S"),
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
 if config_data["registered"] == 1:
    print("Already registered!")
 else:
  metadata = node()
  response = requests.post(
   f"{WORKER_URL}/v1/nodes/register",
   json=metadata,
   timeout=15
 )
  response.raise_for_status()
  result = response.json()

  config_data = config()
  config_data.update({"registered" : 1})
  with open(CONFIG_FILE, "w") as Register_status:
    json.dump(config_data, Register_status, indent=4)
  node_data = node()
  node_data["node_secret"] = result["node_secret"]
  with open(NODE_FILE, "w") as Write_secret:
    json.dump(node_data, Write_secret, indent=4)

# ---------------------------------------- Send Heartbeat ---------------------------------------- #

def send_heartbeat():
    node_data = node()  # Your saved node.json
    node_id = node_data["node_id"]
    node_secret = node_data["node_secret"]
    HEARTBEAT_INTERVAL = 30

    url = f"{WORKER_URL}/v1/nodes/heartbeat"

    while True:
        config_data = config()
        if config_data["registered"] == 1:
          try:
            metadata = {
                   "node_id" : node_id,
                    "status": "online",
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat()
                }
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {node_secret}"
                },
                json=metadata,
                timeout=10
            )

            response.raise_for_status()
            print("Heartbeat acknowledged:", response.status_code)

          except requests.RequestException as e:
            print("Heartbeat failed:", e)

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

register_node()
start_heartbeat_thread()
