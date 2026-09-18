from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import requests
import json

app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/generate"


class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemma3:latest"
    temperature: float = 0.2
    stream: bool = True


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate")
def generate(details: GenerateRequest):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": "gemma3:latest",
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
