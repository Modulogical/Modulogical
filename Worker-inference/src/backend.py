from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
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
NODE_HOSTNAME_SUFFIX = "node.modulogical.com"


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


async def create_node_tunnel(env: Any, node_id: str) -> tuple[str, str]:
    """Create a tunnel, configure ingress, create its DNS record, and return credentials."""
    account_path = "accounts/{account_id}/cfd_tunnel"
    hostname = f"{node_id}.{NODE_HOSTNAME_SUFFIX}"
    zone_id = get_secret(env, "CLOUDFLARE_ZONE_ID")
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
    try:
        token_result = await cloudflare_api(
            env,
            f"accounts/{{account_id}}/cfd_tunnel/{tunnel_id}/token",
            method="GET",
        )
        if not isinstance(token_result, str) or not token_result:
            raise HTTPException(status_code=502, detail="Cloudflare returned no tunnel token")

        # Configure this remotely-managed tunnel to forward inference-hostname
        # requests to the local node API. Keep a catch-all 404 rule last.
        await cloudflare_api(
            env,
            f"accounts/{{account_id}}/cfd_tunnel/{tunnel_id}/configurations",
            method="PUT",
            payload={
                "config": {
                    "ingress": [
                        {
                            "hostname": hostname,
                            "service": NODE_INFERENCE_ORIGIN,
                        },
                        {"service": "http_status:404"},
                    ]
                }
            },
        )

        # Point this node's hostname at its Cloudflare Tunnel. Reuse/update an
        # existing CNAME so retries don't fail on a duplicate DNS record.
        dns_payload = {
            "type": "CNAME",
            "name": hostname,
            "content": f"{tunnel_id}.cfargotunnel.com",
            "proxied": True,
            "ttl": 1,
            "comment": f"Modulogical node tunnel for {node_id}",
        }
        existing_records = await cloudflare_api(
            env,
            f"zones/{zone_id}/dns_records?type=CNAME&name={hostname}",
            method="GET",
        )
        if isinstance(existing_records, list) and existing_records:
            existing_record = existing_records[0]
            record_id = existing_record.get("id") if isinstance(existing_record, dict) else None
            if not record_id:
                raise HTTPException(status_code=502, detail="Cloudflare returned an invalid existing DNS record")
            await cloudflare_api(
                env,
                f"zones/{zone_id}/dns_records/{record_id}",
                method="PUT",
                payload=dns_payload,
            )
        else:
            await cloudflare_api(
                env,
                f"zones/{zone_id}/dns_records",
                method="POST",
                payload=dns_payload,
            )
        return tunnel_id, token_result
    except Exception:
        # Best-effort cleanup so failed provisioning does not leave an orphan tunnel.
        try:
            await cloudflare_api(
                env,
                f"accounts/{{account_id}}/cfd_tunnel/{tunnel_id}",
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
    tunnel_id, tunnel_token = await create_node_tunnel(env, node_id)
    node_secret = secrets.token_urlsafe(32)
    secret_hash = hash_secret(node_secret)
    created_at = utc_now()
    metadata_json = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)

    stage = "insert_inference_nodes"

    try:
        hardware = metadata.get("hardware") or {}
        cpu = hardware.get("cpu") or {}
        gpu = hardware.get("gpu") or {}
        ram = hardware.get("ram") or {}
        ssd = hardware.get("ssd") or {}

        await db.prepare("""
            INSERT INTO inference_nodes (
                node_id, node_secret_hash, status, metadata_json,
                cpu, os, logical_processors, physical_cores,
                gpu, vram, ram, total_storage,
                created_at, last_heartbeat, tunnel_id,
                tunnel_status, tunnel_created_at, tunnel_hostname
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """).bind(
            node_id, secret_hash, "pending", metadata_json,
            str(cpu.get("name") or "Unknown"),
            str(cpu.get("os") or "Unknown"),
            str(cpu.get("logical_processors") or 0),
            str(cpu.get("physical_cores") or 0),
            str(gpu.get("name") or "Unknown"),
            str(gpu.get("vram_total_mb") or 0),
            str(ram.get("total_ram_gb") or 0),
            str(ssd.get("total_gb") or 0),
            created_at, created_at, tunnel_id, "pending", created_at,
            f"{node_id}.{NODE_HOSTNAME_SUFFIX}"
        ).run()

        stage = "insert_heartbeats"

        await db.prepare("""
            INSERT INTO heartbeats (
                node_id, node_secret_hash, status, last_heartbeat,
                cpu_utilisation, logical_processors, ram_available,
                ram_free_percent, gpu_vram_available, gpu_name,
                gpu_utilisation_percent, timestamp, tunnel_hostname

            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """).bind(
            node_id, secret_hash, "pending", created_at,
            "not recorded","not recorded","not recorded",
            "not recorded","not recorded","not recorded",
            "not recorded","not recorded", f"{node_id}.{NODE_HOSTNAME_SUFFIX}"
        ).run()

    except Exception as exc:
        print(f"Registration database failure at {stage}: {type(exc).__name__}: {exc}")

        try:
            await db.prepare(
                "DELETE FROM inference_nodes WHERE node_id = ?"
            ).bind(node_id).run()
            await db.prepare(
                "DELETE FROM heartbeats WHERE node_id = ?"
            ).bind(node_id).run()
        except Exception:
            pass

        try:
            await delete_node_tunnel(env, tunnel_id)
        except Exception:
            pass
        # The DNS record may have been created before a later D1 insert failed.
        try:
            zone_id = get_secret(env, "CLOUDFLARE_ZONE_ID")
            hostname = f"{node_id}.{NODE_HOSTNAME_SUFFIX}"
            records = await cloudflare_api(
                env,
                f"zones/{zone_id}/dns_records?type=CNAME&name={hostname}",
                method="GET",
            )
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict) and record.get("id"):
                        await cloudflare_api(
                            env,
                            f"zones/{zone_id}/dns_records/{record['id']}",
                            method="DELETE",
                        )
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Database stage: {stage}; {type(exc).__name__}: {exc}"
        )
    return {
        "node_id": node_id,
        "node_secret": node_secret,
        "tunnel_id": tunnel_id,
        "tunnel_token": tunnel_token,
        "tunnel_status": "created",
        "status": "pending",
        "created_at": created_at,
        "heartbeat_interval_seconds": 30,
        "message": "Node and tunnel registered. Save node_secret and tunnel_token locally; the tunnel token is returned only during registration.",
        "inference_hostname": f"{node_id}.{NODE_HOSTNAME_SUFFIX}",
        "dns_status": "created",
        "dns_target": f"{tunnel_id}.cfargotunnel.com",
        "note": "The node hostname has a proxied CNAME record pointing to its Cloudflare Tunnel. Allow time for DNS and tunnel configuration to propagate.",
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
        saved = await db.prepare("SELECT node_secret_hash FROM heartbeats WHERE node_id = ?").bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query heartbeat credentials")
    if not saved:
        raise HTTPException(status_code=404, detail="Node heartbeat record not found")
    saved_secret = saved.get("node_secret_hash") if isinstance(saved, dict) else saved["node_secret_hash"]
    if saved_secret not in (supplied_hash, supplied_secret):
        raise HTTPException(status_code=401, detail="Invalid node secret")
    if saved_secret == supplied_secret:
        await db.prepare("UPDATE heartbeats SET node_secret_hash = ? WHERE node_id = ?").bind(supplied_hash, node_id).run()

    timestamp = utc_now()
    status = metadata.get("status")
    cpu_utilisation = metadata.get("cpu_utilisation")
    logical_processors = metadata.get("logical_processors")
    ram_available = metadata.get("ram_available")
    ram_free_percent = metadata.get("ram_free_percent")
    gpu_vram_available = metadata.get("gpu_vram_available")
    gpu_name = metadata.get("gpu_name")
    gpu_utilisation_percent = metadata.get("gpu_utilisation_percent")
   
    try:
        await db.prepare("""
            UPDATE inference_nodes
            SET status = ?, last_heartbeat = ?
            WHERE node_id = ?
        """).bind(
            "online", timestamp, node_id
        ).run()

        await db.prepare("""
            UPDATE heartbeats SET
                status = ?,
                last_heartbeat = ?,
                cpu_utilisation = ?,
                logical_processors = ?,
                ram_available = ?,
                ram_free_percent = ?,
                gpu_vram_available = ?,
                gpu_name = ?,
                gpu_utilisation_percent = ?,
                timestamp = ?
            WHERE node_id = ?
        """).bind(
            "online",
            timestamp,
            cpu_utilisation,
            logical_processors,
            ram_available,
            ram_free_percent,
            gpu_vram_available,
            gpu_name,
            gpu_utilisation_percent,
            timestamp,
            node_id,
        ).run()

    except Exception as exc:
        print(f"Heartbeat database update failed: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not update heartbeat status in D1"
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
        saved = await db.prepare("SELECT node_secret_hash FROM heartbeats WHERE node_id = ?").bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query heartbeat credentials")
    if not saved:
        raise HTTPException(status_code=404, detail="Node not found")
    saved_secret = saved.get("node_secret_hash") if isinstance(saved, dict) else saved["node_secret_hash"]
    if saved_secret not in (supplied_hash, supplied_secret):
        raise HTTPException(status_code=401, detail="Invalid node secret")
    timestamp = utc_now()
    try:
        await db.prepare("UPDATE inference_nodes SET status = ?, last_heartbeat = ? WHERE node_id = ?").bind("offline", timestamp, node_id).run()
        await db.prepare("UPDATE heartbeats SET status = ?, last_heartbeat = ? WHERE node_id = ?").bind("offline", timestamp, node_id).run()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not mark node offline")
    return {"ok": True, "node_id": node_id, "status": "offline", "last_heartbeat": timestamp}
