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
    Models = {
    "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY": "LlaMa3.2:latest",
    "YCaXXcxd9q_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E": "gemma3:latest",
    "U611jj6ZcghehmIrLKCoFmShaUwt--4LWBoee5d7bHc": "phi:latest",
    "OD4TbKRobbGDtYWVPciloUYR6PPT1f4gKwTqx4jX6eE": "qwen3.5:latest",
    "B2_9IU7LiIh0hkeiLMqXxAcKn5NcwWYTqMZe4Q9-bZM": "mistral:latest"
}
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": Models[details.model],
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
