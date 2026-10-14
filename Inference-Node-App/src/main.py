from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import secrets
import requests
import json
from datetime import datetime
import os
import psutil
from pathlib import Path
import subprocess

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
 metadata = node()
 response = requests.post(
   f"{WORKER_URL}/v1/nodes/register",
   json=metadata,
   timeout=15
)
 response.raise_for_status()
 result = response.json()
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
