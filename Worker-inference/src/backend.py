from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from workers import asgi

app = FastAPI(
    title="Modulogical Inference API",
    version="0.1.0",
    description="Node registration and Cloudflare Tunnel provisioning for Modulogical.",
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


def get_secret(env: Any, name: str) -> str:
    value = getattr(env, name, None)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing Worker secret: {name}")
    return str(value)


class NodeRegistration(BaseModel):
    node_id: str = Field(min_length=8, max_length=80)
    hardware: dict[str, Any]
    app_version: str = Field(default="0.1.0", max_length=40)
    protocol_version: int = Field(default=1, ge=1)


class NodeHeartbeat(BaseModel):
    status: str = Field(default="online", pattern="^(online|idle|busy|offline)$")
    telemetry: dict[str, Any] = Field(default_factory=dict)
    app_version: str | None = Field(default=None, max_length=40)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "modulogical-inference"}


@app.post("/v1/nodes/register")
async def register_node(payload: NodeRegistration, request: Request):
    if not NODE_ID_PATTERN.fullmatch(payload.node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")

    env = get_env(request)
    get_secret(env, "CLOUDFLARE_API_TOKEN")
    get_secret(env, "CLOUDFLARE_ACCOUNT_ID")
    get_secret(env, "CLOUDFLARE_ZONE_ID")

    # Next: authenticate the existing Modu account, persist in D1, then create
    # or reuse a tunnel idempotently. Don't provision externally reachable
    # resources before account authentication and database persistence work.
    raise HTTPException(
        status_code=501,
        detail="Registration scaffolded; authentication, D1 persistence, and tunnel provisioning are next.",
    )


@app.post("/v1/nodes/{node_id}/heartbeat")
async def heartbeat(node_id: str, payload: NodeHeartbeat, request: Request):
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")
    # Next: authenticate node credentials and update D1. Calculate uptime server-side.
    raise HTTPException(status_code=501, detail="Heartbeat route not implemented yet")


@app.post("/v1/nodes/{node_id}/disconnect")
async def disconnect_node(node_id: str, request: Request):
    if not NODE_ID_PATTERN.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="Invalid node_id format")
    # Next: authenticate node, mark offline, optionally clean up tunnel and DNS.
    raise HTTPException(status_code=501, detail="Disconnect route not implemented yet")
