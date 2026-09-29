from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from uuid import uuid4

app = FastAPI(title="Modulogical Engine Forge")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PersonalityCommit(BaseModel):
    product_name: str
    personality_name: str
    system_prompt: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_string(value: str) -> str:
    return value.strip() if isinstance(value, str) else ""


async def get_account(request: Request):
    """
    Resolve the authenticated Modulogical account.

    The Engine Forge worker expects the authenticated upstream layer to
    provide X-Account-ID. The ID is then checked against the accounts D1
    binding (ATLAS), so developer_id is always tied to an existing account.

    The current Personality Forge HTML does not yet send this header; this
    backend is therefore ready for the authenticated request once the
    frontend/auth layer supplies it.
    """
    account_id = request.headers.get("X-Account-ID", "").strip()

    if not account_id:
        return None, JSONResponse(
            status_code=401,
            content={"error": "Authentication required."},
        )

    result = await request.app.state.env.ATLAS.prepare(
        """
        SELECT id, account_subscription_status
        FROM accounts
        WHERE id = ?
        LIMIT 1
        """
    ).bind(account_id).first()

    if not result:
        return None, JSONResponse(
            status_code=401,
            content={"error": "Invalid account."},
        )

    return result, None


def get_env(request: Request):
    return request.app.state.env


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(request: Request):
    env = get_env(request)

    try:
        metadata = await env.DB.prepare(
            "SELECT 1 AS ok"
        ).first()

        personalities = await env.PERSONALITIES.prepare(
            "SELECT 1 AS ok"
        ).first()

        accounts = await env.ATLAS.prepare(
            "SELECT 1 AS ok"
        ).first()

        return {
            "status": "ok",
            "databases": {
                "metadata": bool(metadata),
                "personalities": bool(personalities),
                "accounts": bool(accounts),
            },
        }
    except Exception as error:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(error),
            },
        )


# ---------------------------------------------------------------------------
# Personality Forge
# ---------------------------------------------------------------------------

@app.post("/produce/personality")
async def produce_personality(payload: PersonalityCommit, request: Request):
    """
    Create a Personality Forge item.

    D1 layout:
      ATLAS         -> account lookup / subscription tier
      PERSONALITIES -> personality-specific data
      DB            -> shared Engine Forge metadata

    Because the metadata and personality records live in separate D1
    databases, the operation uses compensation if the second write fails.
    """

    product_name = clean_string(payload.product_name)
    personality_name = clean_string(payload.personality_name)
    system_prompt = payload.system_prompt.strip()

    if not product_name:
        return JSONResponse(
            status_code=400,
            content={"error": "Product name is required."},
        )

    if not personality_name:
        return JSONResponse(
            status_code=400,
            content={"error": "Personality name is required."},
        )

    if not system_prompt:
        return JSONResponse(
            status_code=400,
            content={"error": "System prompt is required."},
        )

    account, auth_error = await get_account(request)
    if auth_error:
        return auth_error

    env = get_env(request)

    developer_id = account["id"]
    developer_tier = account["account_subscription_status"]

    # Server-generated identity. The client never chooses the item ID.
    item_id = str(uuid4())

    # The current Forge form has no description field. Keep metadata valid
    # without inventing description content.
    item_description = ""

    personality_inserted = False

    try:
        # 1. Store personality-specific data.
        await env.PERSONALITIES.prepare(
            """
            INSERT INTO personalities (
                item_id,
                chosen_name,
                chosen_system_prompt
            )
            VALUES (?, ?, ?)
            """
        ).bind(
            item_id,
            personality_name,
            system_prompt,
        ).run()

        personality_inserted = True

        # 2. Store shared metadata.
        await env.DB.prepare(
            """
            INSERT INTO metadata (
                item_id,
                item_type,
                developer_id,
                developer_tier,
                item_name,
                item_description
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """
        ).bind(
            item_id,
            "personality",
            developer_id,
            developer_tier,
            product_name,
            item_description,
        ).run()

        return {
            "success": True,
            "item": {
                "item_id": item_id,
                "item_type": "personality",
                "developer_id": developer_id,
                "developer_tier": developer_tier,
                "item_name": product_name,
                "personality_name": personality_name,
            },
        }

    except Exception as error:
        # D1 cannot atomically transact across two separate databases.
        # If metadata insertion failed after the personality was created,
        # remove the personality record to avoid leaving an orphan.
        if personality_inserted:
            try:
                await env.PERSONALITIES.prepare(
                    "DELETE FROM personalities WHERE item_id = ?"
                ).bind(item_id).run()
            except Exception:
                pass

        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to create personality.",
                "detail": str(error),
                "item_id": item_id,
            },
        )


# ---------------------------------------------------------------------------
# Unsupported/legacy endpoints
# ---------------------------------------------------------------------------

@app.post("/produce/module")
async def produce_module():
    return JSONResponse(
        status_code=501,
        content={
            "error": "Module Forge has not been implemented in this backend yet."
        },
    )


@app.post("/produce/workflow")
async def produce_workflow():
    return JSONResponse(
        status_code=501,
        content={
            "error": "Workflow Forge has not been implemented in this backend yet."
        },
    )


@app.post("/produce/webvector")
async def produce_webvector():
    return JSONResponse(
        status_code=501,
        content={
            "error": "WebVector Forge has not been implemented in this backend yet."
        },
    )


# ---------------------------------------------------------------------------
# Cloudflare Python Worker entrypoint
# ---------------------------------------------------------------------------

async def on_fetch(request, env):
    """
    Cloudflare Python Workers entrypoint.

    The ASGI adapter below is intentionally kept small so the Worker can
    expose the FastAPI application while making the Cloudflare bindings
    available through request.app.state.env.
    """
    request_scope = {
        "type": "http",
        "method": request.method,
        "path": request.url.path,
        "query_string": request.url.query.encode(),
        "headers": [
            (k.lower().encode(), v.encode())
            for k, v in request.headers.items()
        ],
        "scheme": request.url.scheme,
        "server": (request.url.hostname, request.url.port or 443),
    }

    # Cloudflare's Python Worker runtime supplies the ASGI bridge in the
    # deployment environment. The application itself is defined above.
    request.app.state.env = env

    return await app(request_scope)
