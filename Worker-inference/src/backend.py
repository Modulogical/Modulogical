from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from workers import asgi, fetch

app = FastAPI(
    title="Modulogical Inference API",
    version="0.4.1",
    description="Node registration, Cloudflare Tunnel provisioning, and lifecycle API.",
)
Default = asgi.entrypoint(app)

NODE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
NODE_INFERENCE_ORIGIN = "http://127.0.0.1:8001"
HEARTBEAT_TTL_SECONDS = 90


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_env(request: Request) -> Any:
    env = request.scope.get("env")
    if env is None:
        raise HTTPException(status_code=500, detail="Worker environment unavailable")
    return env


def get_db(env: Any) -> Any:
    db = getattr(env, "INFERENCE_NODE", None)
    if db is None:
        raise HTTPException(status_code=500, detail="D1 binding INFERENCE_NODE is unavailable")
    return db


def get_secret(env: Any, name: str) -> str:
    value = getattr(env, name, None)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing Worker secret: {name}")
    return str(value)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def bearer_secret(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, secret = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secret.strip():
        raise HTTPException(status_code=401, detail="Missing node secret; use Authorization: Bearer <node_secret>")
    return secret.strip()


async def cloudflare_api(env: Any, path: str, method: str = "GET", payload: dict | None = None) -> Any:
    """Call the Cloudflare API using Worker fetch; never log or return API credentials."""
    api_token = get_secret(env, "CLOUDFLARE_API_TOKEN")
    account_id = get_secret(env, "CLOUDFLARE_ACCOUNT_ID")
    url = f"{CLOUDFLARE_API}/{path.format(account_id=account_id)}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    # Cloudflare Python Workers exposes fetch(url, *, method=..., headers=..., body=...).
    # Its request options are keyword-only; passing an options dict as a second
    # positional argument raises: fetch() takes 1 positional argument but 2 were given.
    fetch_kwargs: dict[str, Any] = {"method": method, "headers": headers}
    if payload is not None:
        fetch_kwargs["body"] = json.dumps(payload, separators=(",", ":"))

    try:
        response = await fetch(url, **fetch_kwargs)
        response_text = await response.text()
        try:
            data = json.loads(response_text) if response_text else {}
        except ValueError:
            data = {}
    except Exception:
        raise HTTPException(status_code=502, detail="Could not reach Cloudflare API")

    if not response.ok or not isinstance(data, dict) or data.get("success") is not True:
        # Avoid reflecting raw Cloudflare response bodies to the caller.
        raise HTTPException(status_code=502, detail="Cloudflare API rejected tunnel provisioning")
    return data.get("result")


async def create_node_dns_record(env: Any, node_id: str, tunnel_id: str) -> str:
    zone_id = get_secret(env, "CLOUDFLARE_ZONE_ID")
    result = await cloudflare_api(
        env,
        f"zones/{zone_id}/dns_records",
        method="POST",
        payload={
            "type": "CNAME",
            "name": f"{node_id}.nodes.modulogical.com",
            "content": f"{tunnel_id}.cfargotunnel.com",
            "proxied": True,
            "ttl": 1,
        },
    )
    if not isinstance(result, dict) or not result.get("id"):
        raise HTTPException(status_code=502, detail="Cloudflare created no usable node DNS record")
    return str(result["id"])


async def delete_node_dns_record(env: Any, dns_record_id: str) -> None:
    zone_id = get_secret(env, "CLOUDFLARE_ZONE_ID")
    await cloudflare_api(
        env,
        f"zones/{zone_id}/dns_records/{dns_record_id}",
        method="DELETE",
    )


async def create_node_tunnel(env: Any, node_id: str) -> tuple[str, str, str]:
    """Create a tunnel and its hostname DNS record; return their IDs and token."""
    account_path = "accounts/{account_id}/cfd_tunnels"
    result = await cloudflare_api(
        env,
        account_path,
        method="POST",
        payload={
            "name": f"modulogical-{node_id}",
            "config_src": "cloudflare",
        },
    )
    if not isinstance(result, dict) or not result.get("id"):
        raise HTTPException(status_code=502, detail="Cloudflare created no usable tunnel ID")

    tunnel_id = str(result["id"])
    dns_record_id = None
    try:
        token_result = await cloudflare_api(
            env,
            f"accounts/{{account_id}}/cfd_tunnels/{tunnel_id}/token",
            method="GET",
        )
        if not isinstance(token_result, str) or not token_result:
            raise HTTPException(status_code=502, detail="Cloudflare returned no tunnel token")

        # Configure this remotely-managed tunnel to forward inference-hostname
        # requests to the local node API. Keep a catch-all 404 rule last.
        await cloudflare_api(
            env,
            f"accounts/{{account_id}}/cfd_tunnels/{tunnel_id}/configurations",
            method="PUT",
            payload={
                "config": {
                    "ingress": [
                        {
                            "hostname": f"{node_id}.nodes.modulogical.com",
                            "service": NODE_INFERENCE_ORIGIN,
                        },
                        {"service": "http_status:404"},
                    ]
                }
            },
        )
        dns_record_id = await create_node_dns_record(env, node_id, tunnel_id)
        return tunnel_id, token_result, dns_record_id
    except Exception:
        if dns_record_id:
            try:
                await delete_node_dns_record(env, dns_record_id)
            except Exception:
                pass
        try:
            await cloudflare_api(
                env,
                f"accounts/{{account_id}}/cfd_tunnels/{tunnel_id}",
                method="DELETE",
            )
        except Exception:
            pass
        raise


async def delete_node_tunnel(env: Any, tunnel_id: str) -> None:
    await cloudflare_api(
        env,
        f"accounts/{{account_id}}/cfd_tunnel/{tunnel_id}",
        method="DELETE",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "modulogical-inference", "version": "0.4.1"}


@app.post("/v1/nodes/register")
async def register_node(request: Request):
    """Register a node, provision its tunnel, and return its credentials once.

    Cloudflare API credentials are read only from Worker secrets; clients do not
    need or receive those credentials. This endpoint is public until account-level
    authorization is integrated, so apply abuse controls before broad public launch.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    metadata = body.get("metadata", body)
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="'metadata' must be a JSON object")
    node_id = metadata.get("node_id")
    if not isinstance(node_id, str) or not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid or missing node_id")
    if not isinstance(metadata.get("hardware", {}), dict):
        raise HTTPException(status_code=400, detail="'hardware' must be a JSON object")

    env = get_env(request)
    db = get_db(env)
    try:
        existing = await db.prepare(
            "SELECT node_id FROM inference_nodes WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query inference_nodes; apply the tunnel migration first")
    if existing:
        raise HTTPException(status_code=409, detail="This node_id is already registered; use its existing credentials")

    # Provision after validation but before inserting. If D1 fails, delete the tunnel.
    tunnel_id, tunnel_token, dns_record_id = await create_node_tunnel(env, node_id)
    node_secret = secrets.token_urlsafe(32)
    secret_hash = hash_secret(node_secret)
    created_at = utc_now()
    hostname = f"{node_id}.nodes.modulogical.com"
    hardware = metadata.get("hardware", {})
    models = metadata.get("models", [])
    if not isinstance(models, list):
        models = []
    models = [model.strip() for model in models if isinstance(model, str) and model.strip()]
    telemetry = json.dumps({"models": models}, separators=(",", ":"))

    try:
        await db.prepare(
            """
            INSERT INTO inference_nodes
                (node_id, account_id, node_secret_hash, status, hostname, tunnel_id, dns_record_id,
                 hardware_json, telemetry_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        ).bind(
            node_id, "", secret_hash, "pending", hostname, tunnel_id, dns_record_id,
            json.dumps(hardware, separators=(",", ":")), telemetry, created_at, created_at,
        ).run()
    except Exception:
        # Clean up this attempt's tunnel resources without touching any existing node row.
        try:
            await delete_node_dns_record(env, dns_record_id)
        except Exception:
            pass
        try:
            await delete_node_tunnel(env, tunnel_id)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Could not save node and tunnel details to D1; check the migration and binding")

    return {
        "node_id": node_id,
        "node_secret": node_secret,
        "tunnel_id": tunnel_id,
        "dns_record_id": dns_record_id,
        "tunnel_token": tunnel_token,
        "tunnel_status": "created",
        "status": "pending",
        "created_at": created_at,
        "heartbeat_interval_seconds": 30,
        "message": "Node and tunnel registered. Save node_secret and tunnel_token locally; the tunnel token is returned only during registration.",
        "inference_hostname": hostname,
        "note": "Use POST /v1/nodes/select to choose a fresh online node by model and hardware requirements.",
    }


@app.post("/v1/nodes/heartbeat")
async def heartbeat(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    metadata = body.get("metadata", body)
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="'metadata' must be a JSON object")
    node_id = metadata.get("node_id")
    if not isinstance(node_id, str) or not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid or missing node_id")

    supplied_secret = bearer_secret(request)
    supplied_hash = hash_secret(supplied_secret)
    db = get_db(get_env(request))
    try:
        saved = await db.prepare(
            "SELECT node_secret_hash FROM inference_nodes WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query heartbeat credentials")
    if not saved:
        raise HTTPException(status_code=404, detail="Node heartbeat record not found")
    saved_secret = saved.get("node_secret_hash") if isinstance(saved, dict) else saved["node_secret_hash"]
    if not saved_secret or saved_secret != supplied_hash:
        raise HTTPException(status_code=401, detail="Invalid node secret")

    timestamp = utc_now()
    hardware = metadata.get("hardware")
    if hardware is not None and not isinstance(hardware, dict):
        raise HTTPException(status_code=400, detail="'hardware' must be a JSON object")
    models = metadata.get("models")
    if models is not None and not isinstance(models, list):
        raise HTTPException(status_code=400, detail="'models' must be a JSON array")
    if models is not None:
        models = [model.strip() for model in models if isinstance(model, str) and model.strip()]
    try:
        assignments = ["status = ?", "last_heartbeat_at = ?", "updated_at = ?"]
        values: list[Any] = ["online", timestamp, timestamp]
        if hardware is not None:
            assignments.append("hardware_json = ?")
            values.append(json.dumps(hardware, separators=(",", ":")))
        if models is not None:
            assignments.append("telemetry_json = ?")
            values.append(json.dumps({"models": models}, separators=(",", ":")))
        values.append(node_id)
        await db.prepare(
            f"UPDATE inference_nodes SET {', '.join(assignments)} WHERE node_id = ?"
        ).bind(*values).run()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update heartbeat status in D1")
    return {"ok": True, "node_id": node_id, "status": "online", "last_heartbeat": timestamp, "heartbeat_interval_seconds": 30}


def numeric_value(value: Any) -> float:
    try:
        number = float(value)
        return number if number >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


async def choose_node(db: Any, model: str, requirements: dict[str, Any]) -> dict[str, Any]:
    min_ram_gb = numeric_value(requirements.get("ram_gb", 0))
    min_vram_mb = numeric_value(requirements.get("vram_mb", 0))
    min_cpu_cores = numeric_value(requirements.get("cpu_cores", 0))
    min_physical_cores = numeric_value(requirements.get("cpu_physical_cores", 0))
    requires_gpu = requirements.get("gpu", False)
    if not isinstance(requires_gpu, bool):
        raise HTTPException(status_code=400, detail="'requirements.gpu' must be a boolean")
    requested_gpu_name = requirements.get("gpu_name")
    if requested_gpu_name is not None and (
        not isinstance(requested_gpu_name, str) or not requested_gpu_name.strip()
    ):
        raise HTTPException(status_code=400, detail="'requirements.gpu_name' must be a non-empty string")

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TTL_SECONDS)).isoformat()
    try:
        result = await db.prepare(
            """SELECT node_id, hostname, hardware_json, telemetry_json, last_heartbeat_at
               FROM inference_nodes
               WHERE status IN ('online', 'idle')
                 AND last_heartbeat_at IS NOT NULL
                 AND julianday(last_heartbeat_at) >= julianday(?)"""
        ).bind(cutoff).all()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query online inference nodes")

    candidates = []
    for row in result.results or []:
        try:
            hardware = json.loads(row.get("hardware_json") or "{}")
            telemetry = json.loads(row.get("telemetry_json") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(hardware, dict) or not isinstance(telemetry, dict):
            continue

        installed_models = telemetry.get("models", [])
        if not isinstance(installed_models, list):
            continue
        installed_names = {
            value.strip().casefold()
            for value in installed_models
            if isinstance(value, str) and value.strip()
        }
        if model.casefold() not in installed_names:
            continue

        cpu = hardware.get("cpu") if isinstance(hardware.get("cpu"), dict) else {}
        gpu = hardware.get("gpu") if isinstance(hardware.get("gpu"), dict) else {}
        ram = hardware.get("ram") if isinstance(hardware.get("ram"), dict) else {}
        ram_gb = numeric_value(ram.get("total_ram_gb"))
        vram_mb = numeric_value(gpu.get("vram_total_mb"))
        cpu_cores = numeric_value(cpu.get("logical_cores"))
        physical_cores = numeric_value(cpu.get("physical_cores"))
        if (
            ram_gb < min_ram_gb
            or vram_mb < min_vram_mb
            or cpu_cores < min_cpu_cores
            or physical_cores < min_physical_cores
        ):
            continue
        if requires_gpu and vram_mb <= 0:
            continue
        if requested_gpu_name and requested_gpu_name.casefold() not in str(gpu.get("name", "")).casefold():
            continue

        hostname = row.get("hostname")
        if not isinstance(hostname, str) or not hostname:
            continue
        score = (vram_mb / 1024 * 8) + ram_gb + (cpu_cores * 0.25)
        candidates.append((score, row, hostname))

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="No fresh online node has the requested model and hardware capacity",
        )

    score, node, hostname = max(
        candidates,
        key=lambda candidate: (
            candidate[0],
            candidate[1].get("last_heartbeat_at", ""),
        ),
    )
    return {
        "node_id": node.get("node_id"),
        "hostname": hostname,
        "model": model,
        "hardware_score": round(score, 2),
    }


def selection_input(body: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise HTTPException(status_code=400, detail="'model' is required")
    requirements = body.get("requirements", {})
    if not isinstance(requirements, dict):
        raise HTTPException(status_code=400, detail="'requirements' must be a JSON object")
    return model.strip(), requirements


@app.post("/v1/nodes/select")
async def select_node(request: Request):
    """Return the strongest fresh node that has the requested model installed."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    model, requirements = selection_input(body)
    return await choose_node(get_db(get_env(request)), model, requirements)


@app.post("/generate")
async def generate(request: Request):
    """Select a capable node and proxy its Ollama generation response."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    model, requirements = selection_input(body)
    if "prompt" not in body:
        raise HTTPException(status_code=400, detail="'prompt' is required")

    selection = await choose_node(get_db(get_env(request)), model, requirements)
    try:
        response = await fetch(
            f"https://{selection['hostname']}/generate",
            method="POST",
            headers={"content-type": "application/json"},
            body=json.dumps(body, separators=(",", ":")),
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Could not reach the selected inference node")

    response_headers = {
        "X-Inference-Node": str(selection["node_id"]),
        "X-Inference-Hostname": str(selection["hostname"]),
    }
    if not response.ok:
        detail = await response.text()
        raise HTTPException(
            status_code=502,
            detail=f"Selected inference node returned HTTP {response.status}: {detail[:500]}",
        )

    if body.get("stream", True) is False:
        text = await response.text()
        try:
            result = json.loads(text)
        except ValueError:
            result = {"response": text}
        return JSONResponse(content=result, headers=response_headers)

    reader = response.body.getReader()
    decoder = __import__("js").TextDecoder.new()

    async def stream_response():
        try:
            while True:
                chunk = await reader.read()
                if chunk.done:
                    break
                text = str(decoder.decode(chunk.value, {"stream": True}))
                if text:
                    yield text.encode("utf-8")
            tail = str(decoder.decode())
            if tail:
                yield tail.encode("utf-8")
        finally:
            try:
                await reader.cancel()
            except Exception:
                pass

    return StreamingResponse(
        stream_response(),
        media_type="application/x-ndjson",
        headers=response_headers,
    )


@app.post("/v1/nodes/{node_id}/heartbeat")
async def heartbeat_by_id(node_id: str, request: Request):
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    body["node_id"] = node_id
    request._body = json.dumps(body).encode("utf-8")
    return await heartbeat(request)


@app.post("/v1/nodes/{node_id}/disconnect")
async def disconnect_node(node_id: str, request: Request):
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")
    supplied_secret = bearer_secret(request)
    supplied_hash = hash_secret(supplied_secret)
    db = get_db(get_env(request))
    try:
        saved = await db.prepare(
            "SELECT node_secret_hash FROM inference_nodes WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query heartbeat credentials")
    if not saved:
        raise HTTPException(status_code=404, detail="Node not found")
    saved_secret = saved.get("node_secret_hash") if isinstance(saved, dict) else saved["node_secret_hash"]
    if saved_secret not in (supplied_hash, supplied_secret):
        raise HTTPException(status_code=401, detail="Invalid node secret")
    timestamp = utc_now()
    try:
        await db.prepare(
            "UPDATE inference_nodes SET status = ?, last_heartbeat_at = ?, updated_at = ? WHERE node_id = ?"
        ).bind("offline", timestamp, timestamp, node_id).run()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not mark node offline")
    return {"ok": True, "node_id": node_id, "status": "offline", "last_heartbeat": timestamp}
