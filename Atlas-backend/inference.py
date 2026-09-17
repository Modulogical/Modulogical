from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import requests
import os

app = FastAPI(title="Atlas Inference Service")

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
)


class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemma3:latest"
    temperature: float = 0.2
    stream: bool = True


@app.get("/")
def root():
    return {"service": "Atlas inference", "status": "online"}


@app.post("/generate")
def generate(request: GenerateRequest):
    payload = {
        "model": request.model,
        "prompt": request.prompt,
        "stream": request.stream,
        "options": {
            "temperature": float(request.temperature),
            "repeat_penalty": 1.15,
            "repeat_last_n": 64,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        stream=request.stream,
        timeout=None,
    )

    if response.status_code != 200:
        return {
            "error": "Ollama request failed",
            "status": response.status_code,
            "detail": response.text,
        }

    if request.stream:
        # Stream Ollama's JSONL response straight through.
        from fastapi.responses import StreamingResponse

        def stream():
            for line in response.iter_lines():
                if line:
                    yield line + b"\n"

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
        )

    return response.json()
