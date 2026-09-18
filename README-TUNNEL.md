# Atlas inference — Cloudflare Tunnel setup

Architecture:

Backend Worker
  -> https://inference.modulogical.com
  -> Cloudflare Tunnel
  -> http://localhost:8001
  -> PC-inference/inference.py
  -> Ollama

The old Worker-inference gateway is intentionally removed.

## PC inference

Run the inference API on the PC, for example:

    uvicorn inference:app --host 0.0.0.0 --port 8001

Verify locally:

    http://localhost:8001/health

Expected response:

    {"status":"ok"}

## Cloudflare Tunnel

Create a Cloudflare Tunnel and configure a Published Application:

Hostname:
    inference.modulogical.com

Service:
    http://localhost:8001

The backend's INFERENCE_URL should remain:

    https://inference.modulogical.com

Do not point the backend at localhost: the backend runs in Cloudflare, not on the PC.

Do not deploy an inference Worker for this architecture.
