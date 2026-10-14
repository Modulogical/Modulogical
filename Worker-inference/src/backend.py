from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from workers import asgi

app = FastAPI(
    title="Modulogical Inference API",
    version="0.2.0",
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
    # The Wrangler binding is named INFERENCE_NODE (a Python-safe identifier).
    db = getattr(env, "INFERENCE_NODE", None)
    if db is None:
        raise HTTPException(status_code=500, detail="D1 binding INFERENCE_NODE is unavailable")
    return db


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class NodeHeartbeat(BaseModel):
    status: str = Field(default="online", pattern="^(online|idle|busy|offline)$")
    telemetry: dict[str, Any] = Field(default_factory=dict)
    app_version: str | None = Field(default=None, max_length=40)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "modulogical-inference"}


@app.post("/v1/nodes/register")
async def register_node(request: Request):
    """Register a node and issue a per-node secret.

    Accepts either the node object directly or {"metadata": <node object>}.
    This initial endpoint intentionally does not provision a Cloudflare Tunnel.
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

    hardware = metadata.get("hardware", {})
    if not isinstance(hardware, dict):
        raise HTTPException(status_code=400, detail="'hardware' must be a JSON object")

    env = get_env(request)
    db = get_db(env)

    try:
        existing = await db.prepare(
            "SELECT node_id FROM inference_nodes WHERE node_id = ?"
        ).bind(node_id).first()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not query the inference_nodes table; check your D1 schema and binding.",
        )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="This node_id is already registered. Use the existing node credentials or implement an authenticated re-registration flow.",
        )

    node_secret = secrets.token_urlsafe(32)
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
            node_id,
            hash_secret(node_secret),
            "pending",
            metadata_json,
            created_at,
            metadata_json["last_heartbeat"],
        ).run()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not save node registration; check that the D1 table has the expected columns.",
        )

    # Return the raw secret only once. Store only its hash in D1.
    return {
        "node_id": node_id,
        "node_secret": node_secret,
        "status": "pending",
        "created_at": created_at,
        "heartbeat_interval_seconds": 60,
        "message": "Node registered. Tunnel provisioning and authenticated heartbeats are not enabled yet.",
    }


@app.post("/v1/nodes/{node_id}/heartbeat")
async def heartbeat(node_id: str, payload: NodeHeartbeat, request: Request):
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")
    # TODO: require the node's per-node credential before changing state.
    # Do not mark a node online until authentication and a tunnel health check pass.
    raise HTTPException(
        status_code=501,
        detail="Heartbeat is not implemented yet; registration currently creates pending nodes only.",
    )


@app.post("/v1/nodes/{node_id}/disconnect")
async def disconnect_node(node_id: str, request: Request):
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")
    # TODO: authenticate the node and mark it offline in D1.
    raise HTTPException(status_code=501, detail="Disconnect route not implemented yet")
