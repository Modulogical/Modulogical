"""
Engine Forge backend for Cloudflare Python Workers.

This is the Python/ASGI backend for the Engine Forge Worker.
It exposes separate production endpoints for each item type and a
standard health endpoint.

Routes:
    GET  /health
    POST /produce/module
    POST /produce/personality
    POST /produce/workflow
    POST /produce/webvector

D1 binding:
    env.DB

Inference:
    https://inference.modulogical.com/health
"""

import json
import urllib.request
import urllib.error
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Modulogical Engine Forge")


ITEM_TYPES = {
    "module": {
        "table": "module_queue",
        "id_column": "module_id",
        "version_column": "module_version",
        "price_column": "module_price",
        "dependencies_column": "module_dependencies",
    },
    "personality": {
        "table": "personality_queue",
        "id_column": "personality_id",
        "version_column": "personality_version",
        "price_column": "personality_price",
        "dependencies_column": "personality_dependencies",
    },
    "workflow": {
        "table": "workflow_queue",
        "id_column": "workflow_id",
        "version_column": "workflow_version",
        "price_column": "workflow_price",
        "dependencies_column": "workflow_dependencies",
    },
    "webvector": {
        "table": "webvector_queue",
        "id_column": "webvector_id",
        "version_column": "webvector_version",
        "price_column": "webvector_price",
        "dependencies_column": "webvector_dependencies",
    },
}


def get_db(request: Request):
    """
    Cloudflare's Python Worker exposes bindings through request.scope["env"].
    """
    env = request.scope.get("env")
    if env is None:
        raise RuntimeError("Cloudflare Worker environment is unavailable.")
    db = getattr(env, "DB", None)
    if db is None:
        raise RuntimeError("D1 binding DB is unavailable.")
    return db


def parse_json(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


async def inference_health() -> str:
    try:
        request = urllib.request.Request(
            "https://inference.modulogical.com/health",
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return "online" if 200 <= response.status < 300 else "offline"
    except Exception:
        return "offline"


async def produce_item(item_type: str, request: Request):
    config = ITEM_TYPES[item_type]

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Request body must be valid JSON."},
            status_code=400,
        )

    required = [
        "title",
        "developer_id",
        "developer_tier",
        "item_id",
        "item_version",
        "item_price",
        "item_dependencies",
        "code",
    ]

    missing = [
        field for field in required
        if body.get(field) is None or body.get(field) == ""
    ]

    if missing:
        return JSONResponse(
            {"error": "Missing required fields.", "fields": missing},
            status_code=400,
        )

    schema = parse_json(body.get("schema"), {})
    display = parse_json(body.get("display"), {})
    dependencies = parse_json(body.get("item_dependencies"), [])

    if schema is None:
        return JSONResponse(
            {"error": "schema must contain valid JSON."},
            status_code=400,
        )

    if display is None:
        return JSONResponse(
            {"error": "display must contain valid JSON."},
            status_code=400,
        )

    if dependencies is None:
        return JSONResponse(
            {"error": "item_dependencies must contain valid JSON."},
            status_code=400,
        )

    # WebVector uses the Information JSON object as its stored schema payload.
    if item_type == "webvector":
        information = parse_json(body.get("information"), {})
        if information is None:
            return JSONResponse(
                {"error": "information must contain valid JSON."},
                status_code=400,
            )
        schema = information

    # Workflow flowchart data can be supplied as part of the schema.
    if item_type == "workflow":
        flow = body.get("flow")
        if flow is not None:
            if isinstance(flow, str):
                flow = parse_json(flow, None)
            if flow is None:
                return JSONResponse(
                    {"error": "flow must contain valid JSON."},
                    status_code=400,
                )
            if not isinstance(schema, dict):
                schema = {"schema": schema}
            schema["flow"] = flow

    values = [
        str(body["title"]),
        str(body["developer_id"]),
        str(body["developer_tier"]),
        str(body["item_id"]),
        json.dumps(schema, separators=(",", ":")),
        str(body.get("description", "")),
        json.dumps(display, separators=(",", ":")),
        str(body["item_version"]),
        str(body["item_price"]),
        json.dumps(dependencies, separators=(",", ":")),
    ]

    # The requested queue schema currently has no code column.
    # Do not silently discard code. Return a clear response until the
    # corresponding *_code column is added to the D1 queue table.
    return JSONResponse(
        {
            "error": "Queue schema is missing a code column.",
            "item_type": item_type,
            "message": (
                f"{config['table']} does not currently contain a code column. "
                "Add one before submitting executable item code."
            ),
            "received": {
                "title": body["title"],
                "item_id": body["item_id"],
                "version": body["item_version"],
                "code_received": True,
            },
        },
        status_code=409,
    )


@app.get("/health")
async def health(request: Request):
    inference = await inference_health()

    try:
        db = get_db(request)
        db.prepare("SELECT 1").first()
        database = "online"
    except Exception:
        database = "offline"

    status = "ok" if database == "online" else "degraded"

    return {
        "status": status,
        "service": "engine-forge",
        "database": database,
        "inference": inference,
    }


@app.post("/produce/module")
async def produce_module(request: Request):
    return await produce_item("module", request)


@app.post("/produce/personality")
async def produce_personality(request: Request):
    return await produce_item("personality", request)


@app.post("/produce/workflow")
async def produce_workflow(request: Request):
    return await produce_item("workflow", request)


@app.post("/produce/webvector")
async def produce_webvector(request: Request):
    return await produce_item("webvector", request)
