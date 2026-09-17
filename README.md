# Modulogical / Atlas separated deployment

## Architecture

Browser
  -> Worker-frontend (modulogical.com)
  -> /api/* -> Worker-backend
  -> Python FastAPI backend
  -> Worker-inference
  -> PC-inference
  -> Ollama

The important correction is that the browser does not need Worker-frontend to "send information" to the backend in an application-data sense. Worker-frontend is the public web/API gateway and proxies `/api/*` to Worker-backend.

Worker-backend is the Cloudflare API gateway. Your existing Python `backend/backend.py` remains the stateful application backend for now, so your account/history code keeps working. This is deliberate: moving filesystem storage to Cloudflare D1 is a separate migration.

Worker-inference is a separate Cloudflare Worker facade. It forwards `/generate` to the PC inference server.

## URLs

- `modulogical.com` = Worker-frontend
- Worker-backend = internal Cloudflare service binding
- Worker-inference = internal Cloudflare service binding if you later bind it to backend; it can also be reached by a public workers.dev URL for testing
- PC inference = your tunnel URL -> port 8001
- Ollama = localhost:11434 on your PC only

## PC inference

Install/use FastAPI + requests + uvicorn, then run:

    uvicorn inference:app --host 0.0.0.0 --port 8001

The PC server calls:

    http://localhost:11434/api/generate

Do NOT put localhost:11434 into a Cloudflare Worker. Cloudflare cannot reach your PC's localhost.

Expose port 8001 through your existing HTTPS tunnel and put that HTTPS URL in Worker-inference's `INFERENCE_ORIGIN`.

Example:

    INFERENCE_ORIGIN=https://your-inference-tunnel.example

The Worker will call:

    https://your-inference-tunnel.example/generate

## Backend origin

Your existing FastAPI Atlas backend needs its own HTTPS tunnel/public origin for Worker-backend.

Put that URL into Worker-backend's `BACKEND_ORIGIN`.

The supplied `backend/backend.py` now reads:

    ATLAS_INFERENCE_URL

If that variable is set, it calls that URL. Otherwise it falls back to:

    http://localhost:8001/generate

## Important

This transitional package intentionally keeps your account/history filesystem on the Python backend. That means Worker-backend is a Cloudflare API facade, not yet the place where account data is physically stored.

If you later want account data to live fully on Cloudflare, migrate the backend storage to D1/R2/KV. Do that as a separate step rather than changing storage and networking at the same time.

## Deploy order

1. Deploy Worker-backend.
2. Set its BACKEND_ORIGIN.
3. Deploy Worker-inference.
4. Run PC-inference and expose port 8001 through HTTPS.
5. Set Worker-inference INFERENCE_ORIGIN.
6. Make the Python backend call the Worker-inference URL.
7. Deploy Worker-frontend.
8. Attach modulogical.com to Worker-frontend.
9. Test CSS first, then /api/auth/check, then login, then chat.
