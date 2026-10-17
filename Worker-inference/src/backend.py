from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from workers import asgi

app = FastAPI(
    title="Modulogical Inference API",
    version="0.3.0",
    description="Node registration and lifecycle API for Modulogical.",
)
Default = asgi.entrypoint(app)

NODE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")


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
        raise HTTPException(
            status_code=500,
            detail="D1 binding INFERENCE_NODE is unavailable",
        )
    return db


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def bearer_secret(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, secret = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secret.strip():
        raise HTTPException(
            status_code=401,
            detail="Missing node secret; use Authorization: Bearer <node_secret>",
        )
    return secret.strip()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "modulogical-inference"}


@app.post("/v1/nodes/heartbeat")
async def heartbeat(request: Request):
    """Accept heartbeats sent to /v1/nodes/heartbeat with a Bearer node secret.

    The body should contain at least {"node_id": "..."}; extra metadata is ignored
    for authentication and server time is used for last_heartbeat.
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

    supplied_secret = bearer_secret(request)
    supplied_hash = hash_secret(supplied_secret)

    db = get_db(get_env(request))

    try:
        saved = await db.prepare(
            "SELECT node_secret_hash FROM heartbeats WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query heartbeat credentials")

    if not saved:
        raise HTTPException(status_code=404, detail="Node heartbeat record not found")

    saved_secret = saved.get("node_secret_hash") if isinstance(saved, dict) else saved["node_secret_hash"]

    # Compatibility: earlier deployments stored the raw secret in the column named
    # node_secret_hash. Accept it once, then migrate it to a SHA-256 hash.
    if saved_secret not in (supplied_hash, supplied_secret):
        raise HTTPException(status_code=401, detail="Invalid node secret")

    if saved_secret == supplied_secret:
        try:
            await db.prepare(
                "UPDATE heartbeats SET node_secret_hash = ? WHERE node_id = ?"
            ).bind(supplied_hash, node_id).run()
        except Exception:
            raise HTTPException(status_code=500, detail="Could not migrate heartbeat credential")

    timestamp = utc_now()

    try:
        await db.prepare(
            """
            UPDATE inference_nodes
            SET status = ?, last_heartbeat = ?
            WHERE node_id = ?
            """
        ).bind("online", timestamp, node_id).run()

        await db.prepare(
            """
            UPDATE heartbeats
            SET status = ?, last_heartbeat = ?
            WHERE node_id = ?
            """
        ).bind("online", timestamp, node_id).run()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update heartbeat status in D1")

    return {
        "ok": True,
        "node_id": node_id,
        "status": "online",
        "last_heartbeat": timestamp,
        "heartbeat_interval_seconds": 30,
    }


@app.post("/v1/nodes/register")
async def register_node(request: Request):
    """Register a node and issue a per-node secret once."""
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

    hardware = metadata.get("hardware", {})
    if not isinstance(hardware, dict):
        raise HTTPException(status_code=400, detail="'hardware' must be a JSON object")

    db = get_db(get_env(request))

    try:
        existing = await db.prepare(
            "SELECT node_id FROM inference_nodes WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not query inference_nodes; check the D1 schema and binding.",
        )

    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                "This node_id is already registered. Keep its existing node credentials; "
                "do not register it again."
            ),
        )

    node_secret = secrets.token_urlsafe(32)
    secret_hash = hash_secret(node_secret)
    created_at = utc_now()
    metadata_json = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)

    try:
        await db.prepare(
            """
            INSERT INTO inference_nodes
                (node_id, node_secret_hash, status, metadata_json, created_at, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?)
            """
        ).bind(
            node_id, secret_hash, "pending", metadata_json, created_at, created_at
        ).run()

        await db.prepare(
            """
            INSERT INTO heartbeats
                (node_id, node_secret_hash, status, last_heartbeat)
            VALUES (?, ?, ?, ?)
            """
        ).bind(node_id, secret_hash, "pending", created_at).run()
    except Exception:
        # D1 does not provide a transaction across these independent calls. If one
        # insert fails, surface the failure so the schema can be corrected.
        raise HTTPException(
            status_code=500,
            detail="Could not save node registration to both D1 tables; check their schemas.",
        )

    return {
        "node_id": node_id,
        "node_secret": node_secret,
        "status": "pending",
        "created_at": created_at,
        "heartbeat_interval_seconds": 30,
        "message": "Node registered. Save node_secret locally; it is returned only once.",
    }


@app.post("/v1/nodes/{node_id}/heartbeat")
async def heartbeat_by_id(node_id: str, request: Request):
    """Compatibility route for clients that put node_id in the URL."""
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")

    try:
        body = await request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        body = {}
    body["node_id"] = node_id

    # Reuse the canonical handler while preserving the incoming Authorization header.
    # This route is retained for compatibility with clients using the URL form.
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
            "SELECT node_secret_hash FROM heartbeats WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not query heartbeat credentials")

    if not saved:
        raise HTTPException(status_code=404, detail="Node not found")

    saved_secret = saved["node_secret_hash"]
    if saved_secret not in (supplied_hash, supplied_secret):
        raise HTTPException(status_code=401, detail="Invalid node secret")

    timestamp = utc_now()
    try:
        await db.prepare(
            "UPDATE inference_nodes SET status = ?, last_heartbeat = ? WHERE node_id = ?"
        ).bind("offline", timestamp, node_id).run()
        await db.prepare(
            "UPDATE heartbeats SET status = ?, last_heartbeat = ? WHERE node_id = ?"
        ).bind("offline", timestamp, node_id).run()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update node disconnect status")

    return {"ok": True, "node_id": node_id, "status": "offline", "last_heartbeat": timestamp}
