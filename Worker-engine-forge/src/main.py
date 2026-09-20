import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from workers import asgi

app = FastAPI(title="Modulogical Engine Forge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

ITEM_TYPES = {
    "module": {
        "table": "module_queue",
        "id_column": "module_id",
        "version_column": "module_version",
        "price_column": "module_price",
        "dependencies_column": "module_dependencies",
        "code_column": "module_code",
    },
    "personality": {
        "table": "personality_queue",
        "id_column": "personality_id",
        "version_column": "personality_version",
        "price_column": "personality_price",
        "dependencies_column": "personality_dependencies",
        "code_column": "personality_code",
    },
    "workflow": {
        "table": "workflow_queue",
        "id_column": "workflow_id",
        "version_column": "workflow_version",
        "price_column": "workflow_price",
        "dependencies_column": "workflow_dependencies",
        "code_column": "workflow_code",
    },
    "webvector": {
        "table": "webvector_queue",
        "id_column": "webvector_id",
        "version_column": "webvector_version",
        "price_column": "webvector_price",
        "dependencies_column": "webvector_dependencies",
        "code_column": "webvector_code",
    },
}

JSON_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def get_db(request: Request):
    env = request.scope.get("env")
    if env is None:
        raise RuntimeError("Cloudflare Worker environment is unavailable.")
    db = getattr(env, "DB", None)
    if db is None:
        raise RuntimeError("D1 binding DB is unavailable.")
    return db


async def d1_run(request: Request, sql: str, *values):
    return await get_db(request).prepare(sql).bind(*values).run()


async def d1_first(request: Request, sql: str, *values):
    return await get_db(request).prepare(sql).bind(*values).first()


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


def json_response(data, status: int = 200):
    return JSONResponse(data, status_code=status, headers=JSON_HEADERS)


async def produce_item(item_type: str, request: Request):
    config = ITEM_TYPES[item_type]

    try:
        body = await request.json()
    except Exception:
        return json_response({"error": "Request body must be valid JSON."}, 400)

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
        return json_response({"error": "Missing required fields.", "fields": missing}, 400)

    schema = parse_json(body.get("schema"), {})
    display = parse_json(body.get("display"), {})
    dependencies = parse_json(body.get("item_dependencies"), [])

    if schema is None:
        return json_response({"error": "schema must contain valid JSON."}, 400)
    if display is None:
        return json_response({"error": "display must contain valid JSON."}, 400)
    if dependencies is None:
        return json_response({"error": "item_dependencies must contain valid JSON."}, 400)

    if item_type == "webvector":
        information = parse_json(body.get("information"), {})
        if information is None:
            return json_response({"error": "information must contain valid JSON."}, 400)
        schema = information

    if item_type == "workflow" and body.get("flow") is not None:
        flow = parse_json(body.get("flow"), None)
        if flow is None:
            return json_response({"error": "flow must contain valid JSON."}, 400)
        if not isinstance(schema, dict) or isinstance(schema, list):
            schema = {"schema": schema}
        schema["flow"] = flow

    sql = f"""
        INSERT INTO {config['table']} (
            title,
            developer_id,
            developer_tier,
            {config['id_column']},
            schema,
            description,
            display,
            {config['version_column']},
            {config['price_column']},
            {config['dependencies_column']},
            {config['code_column']}
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    try:
        await d1_run(
            request,
            sql,
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
        )
    except Exception as exc:
        print(f"[Engine Forge] D1 INSERT ERROR: {type(exc).__name__}: {exc}")
        return json_response(
            {
                "error": "Could not queue item.",
                "detail": str(exc),
            },
            500,
        )

    return json_response(
        {
            "success": True,
            "item_type": item_type,
            "item_id": body["item_id"],
            "message": "Item queued successfully.",
        },
        201,
    )


@app.get("/health")
async def health(request: Request):
    try:
        await d1_first(request, "SELECT 1")
        database = "online"
        status = "ok"
    except Exception as exc:
        print(f"[Engine Forge] D1 HEALTH ERROR: {type(exc).__name__}: {exc}")
        database = "offline"
        status = "degraded"

    return json_response(
        {
            "status": status,
            "service": "engine-forge",
            "database": database,
            "inference_dependency": "none",
        }
    )


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


@app.get("/")
async def root():
    return json_response({
        "service": "modulogical-engine-forge",
        "status": "ok",
        "runtime": "python-worker",
        "database": "D1",
        "inference_dependency": "none",
    })


@app.options("/{path:path}")
async def options(path: str):
    return Response(status_code=204, headers=JSON_HEADERS)


Default = asgi.entrypoint(app)
