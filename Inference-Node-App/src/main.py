from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import secrets
import requests
import json
from datetime import datetime
import psutil


APPDATA = Path(os.environ["LOCALAPPDATA"]) / "Modulogical" / "Inference Node"
APPDATA.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = APPDATA / "config.json"
NODE_FILE = APPDATA / "node.json"

app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/generate"


class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemma3:latest"
    temperature: float = 0.2
    stream: bool = True

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

with open(NODE_FILE, "w") as write_node:
    data={
        "node_id" : f"node_{secrets.token_urlsafe(32)}",
        "node_secret" : "",
        "modulogical_id" : "",
        "last_heartbeat" : datetime.now().strtime("%H:%M:%S"),
        "hardware" : {
            "gpu" : "",
            "ram" : "",
            "vram" : "",
            "ssd" : "",
        }
    }


















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
