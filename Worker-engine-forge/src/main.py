"""
Modulogical Engine Forge Cloudflare Python Worker.
"""
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from workers import asgi

app = FastAPI(title="Modulogical Engine Forge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

ITEM_TYPES = {
    "module": "module_queue",
    "personality": "personality_queue",
    "workflow": "workflow_queue",
    "webvector": "webvector_queue",
}

def get_db(request: Request):
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

async def produce_item(item_type: str, request: Request):
    table = ITEM_TYPES[item_type]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)

    required = [
        "title", "developer_id", "developer_tier", "item_id",
        "item_version", "item_price", "item_dependencies", "code",
    ]
    missing = [f for f in required if body.get(f) is None or body.get(f) == ""]
    if missing:
        return JSONResponse({"error": "Missing required fields.", "fields": missing}, status_code=400)

    schema = parse_json(body.get("schema"), {})
    display = parse_json(body.get("display"), {})
    dependencies = parse_json(body.get("item_dependencies"), [])
    if schema is None:
        return JSONResponse({"error": "schema must contain valid JSON."}, status_code=400)
    if display is None:
        return JSONResponse({"error": "display must contain valid JSON."}, status_code=400)
    if dependencies is None:
        return JSONResponse({"error": "item_dependencies must contain valid JSON."}, status_code=400)

    if item_type == "webvector":
        information = parse_json(body.get("information"), {})
        if information is None:
            return JSONResponse({"error": "information must contain valid JSON."}, status_code=400)
        schema = information

    if item_type == "workflow" and body.get("flow") is not None:
        flow = body["flow"]
        if isinstance(flow, str):
            flow = parse_json(flow, None)
        if flow is None:
            return JSONResponse({"error": "flow must contain valid JSON."}, status_code=400)
        if not isinstance(schema, dict):
            schema = {"schema": schema}
        schema["flow"] = flow

    id_col = f"{item_type}_id"
    version_col = f"{item_type}_version"
    price_col = f"{item_type}_price"
    deps_col = f"{item_type}_dependencies"
    code_col = f"{item_type}_code"

    sql = f"""
        INSERT INTO {table}
        (title, developer_id, developer_tier, {id_col}, schema, description,
         display, {version_col}, {price_col}, {deps_col}, {code_col})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        db = get_db(request)
        await db.prepare(sql).bind(
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
            str(body["code"]),
        ).run()
        return JSONResponse({
            "success": True,
            "item_type": item_type,
            "item_id": body["item_id"],
            "message": "Item queued successfully.",
        }, status_code=201)
    except Exception as exc:
        return JSONResponse({"error": "Could not queue item.", "detail": str(exc)}, status_code=500)

@app.get("/health")
async def health(request: Request):
    try:
        db = get_db(request)
        await db.prepare("SELECT 1").first()
        database = "online"
    except Exception:
        database = "offline"
    return {
        "status": "ok" if database == "online" else "degraded",
        "service": "engine-forge",
        "database": database,
        "inference_dependency": "none",
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

# Cloudflare Python Workers ASGI entrypoint.
worker = asgi.fetch(app)
