import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from workers import asgi


# ---------------------------------------------------------------------------
# Modulogical Admin Backend
#
# Cloudflare Python Worker / FastAPI backend.
#
# Bindings expected in wrangler.jsonc:
#   ATLAS -> modulogical-atlas
#   DB    -> modulogical-metadata
#
# Admin authentication:
#   1. Frontend sends the normal Modulogical session token as Bearer token.
#   2. Token is SHA-256 hashed.
#   3. Hash is looked up in ATLAS.sessions.
#   4. The session is joined to ATLAS.accounts.
#   5. account_subscription_status must equal "admin".
#
# This deliberately uses the existing Modulogical authentication/session
# system rather than creating a second password system.
# ---------------------------------------------------------------------------

app = FastAPI(title="Modulogical Admin Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def env_from(request: Request):
    return request.scope["env"]


def token_from(request: Request) -> Optional[str]:
    authorization = request.headers.get("authorization", "").strip()

    if not authorization.lower().startswith("bearer "):
        return None

    token = authorization[7:].strip()
    return token or None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def json_response(data, status: int = 200):
    return Response(
        content=json.dumps(data),
        status_code=status,
        media_type="application/json",
    )


async def d1_first(request: Request, binding: str, sql: str, *values):
    env = env_from(request)
    database = getattr(env, binding)
    return await database.prepare(sql).bind(*values).first()


async def d1_all(request: Request, binding: str, sql: str, *values):
    env = env_from(request)
    database = getattr(env, binding)
    result = await database.prepare(sql).bind(*values).all()
    return result.results or []


async def d1_run(request: Request, binding: str, sql: str, *values):
    env = env_from(request)
    database = getattr(env, binding)
    return await database.prepare(sql).bind(*values).run()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def authenticate_admin(request: Request):
    """
    Return the authenticated admin account, or a JSON error response.

    The account's subscription status is the source of truth for admin
    access. No hard-coded admin account ID is used.
    """

    token = token_from(request)

    if not token:
        return None, json_response(
            {"error": "Authentication required."},
            401,
        )

    try:
        account = await d1_first(
            request,
            "ATLAS",
            """
            SELECT
                a.id,
                a.username,
                a.name,
                a.account_subscription_status
            FROM sessions s
            JOIN accounts a ON a.id = s.account_id
            WHERE s.token_hash = ?
              AND (
                    s.expires_at IS NULL
                    OR s.expires_at > CURRENT_TIMESTAMP
                  )
            LIMIT 1
            """,
            token_hash(token),
        )
    except Exception as error:
        return None, json_response(
            {
                "error": "Could not verify session.",
                "detail": str(error),
            },
            500,
        )

    if not account:
        return None, json_response(
            {"error": "Invalid or expired session."},
            401,
        )

    if account["account_subscription_status"] != "admin":
        return None, json_response(
            {"error": "Admin access required."},
            403,
        )

    return account, None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RejectRequest(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(request: Request):
    try:
        metadata = await d1_first(
            request,
            "DB",
            "SELECT 1 AS ok",
        )

        accounts = await d1_first(
            request,
            "ATLAS",
            "SELECT 1 AS ok",
        )

        return {
            "status": "ok",
            "databases": {
                "metadata": bool(metadata),
                "accounts": bool(accounts),
            },
        }

    except Exception as error:
        return json_response(
            {
                "status": "error",
                "error": str(error),
            },
            500,
        )


# ---------------------------------------------------------------------------
# Admin identity
# ---------------------------------------------------------------------------

@app.get("/admin/me")
async def admin_me(request: Request):
    account, error = await authenticate_admin(request)

    if error:
        return error

    return {
        "admin": True,
        "account": {
            "id": account["id"],
            "username": account["username"],
            "name": account["name"],
            "account_subscription_status":
                account["account_subscription_status"],
        },
    }


@app.get("/api/auth/check")
async def auth_check(request: Request):
    account, error = await authenticate_admin(request)

    if error:
        return error

    return {
        "valid": True,
        "admin": True,
        "account_id": account["id"],
        "username": account["username"],
        "name": account["name"],
        "account_subscription_status":
            account["account_subscription_status"],
    }


# ---------------------------------------------------------------------------
# Marketplace moderation
# ---------------------------------------------------------------------------

@app.get("/admin/items")
async def list_items(
    request: Request,
    status: str = "pending",
    item_type: Optional[str] = None,
    search: Optional[str] = None,
):
    account, error = await authenticate_admin(request)

    if error:
        return error

    allowed_statuses = {"pending", "approved", "rejected", "all"}

    if status not in allowed_statuses:
        return json_response(
            {
                "error": (
                    "Invalid status. Use pending, approved, "
                    "rejected, or all."
                )
            },
            400,
        )

    clauses = []
    values = []

    if status != "all":
        clauses.append("m.marketplace_status = ?")
        values.append(status)

    if item_type:
        clauses.append("LOWER(m.item_type) = LOWER(?)")
        values.append(item_type.strip())

    if search and search.strip():
        clauses.append(
            """
            (
                LOWER(m.item_name) LIKE LOWER(?)
                OR LOWER(m.item_description) LIKE LOWER(?)
                OR LOWER(a.username) LIKE LOWER(?)
            )
            """
        )
        term = f"%{search.strip()}%"
        values.extend([term, term, term])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    sql = f"""
        SELECT
            m.item_id,
            m.item_type,
            m.developer_id,
            m.developer_tier,
            m.item_name,
            m.item_description,
            m.marketplace_status,
            m.submitted_at,
            m.moderated_at,
            m.moderated_by,
            m.rejection_reason,
            a.username AS developer_username,
            a.name AS developer_name
        FROM metadata m
        LEFT JOIN accounts a
            ON a.id = m.developer_id
        {where}
        ORDER BY
            CASE m.marketplace_status
                WHEN 'pending' THEN 0
                WHEN 'approved' THEN 1
                WHEN 'rejected' THEN 2
                ELSE 3
            END,
            m.submitted_at DESC,
            m.item_name ASC
        LIMIT 100
    """

    try:
        items = await d1_all(request, "DB", sql, *values)

        counts = await d1_first(
            request,
            "DB",
            """
            SELECT
                SUM(
                    CASE
                        WHEN marketplace_status = 'pending' THEN 1
                        ELSE 0
                    END
                ) AS pending,
                SUM(
                    CASE
                        WHEN marketplace_status = 'approved' THEN 1
                        ELSE 0
                    END
                ) AS approved,
                SUM(
                    CASE
                        WHEN marketplace_status = 'rejected' THEN 1
                        ELSE 0
                    END
                ) AS rejected
            FROM metadata
            """,
        )

        return {
            "items": items,
            "counts": {
                "pending": counts["pending"] or 0,
                "approved": counts["approved"] or 0,
                "rejected": counts["rejected"] or 0,
            },
            "admin": {
                "id": account["id"],
                "username": account["username"],
            },
        }

    except Exception as error:
        return json_response(
            {
                "error": "Could not load marketplace items.",
                "detail": str(error),
            },
            500,
        )


@app.get("/admin/items/{item_id}")
async def get_item(item_id: str, request: Request):
    account, error = await authenticate_admin(request)

    if error:
        return error

    item = await d1_first(
        request,
        "DB",
        """
        SELECT
            m.item_id,
            m.item_type,
            m.developer_id,
            m.developer_tier,
            m.item_name,
            m.item_description,
            m.marketplace_status,
            m.submitted_at,
            m.moderated_at,
            m.moderated_by,
            m.rejection_reason,
            a.username AS developer_username,
            a.name AS developer_name
        FROM metadata m
        LEFT JOIN accounts a
            ON a.id = m.developer_id
        WHERE m.item_id = ?
        LIMIT 1
        """,
        item_id,
    )

    if not item:
        return json_response(
            {"error": "Item not found."},
            404,
        )

    return {
        "item": item,
        "admin": {
            "id": account["id"],
            "username": account["username"],
        },
    }


@app.post("/admin/items/{item_id}/approve")
async def approve_item(item_id: str, request: Request):
    account, error = await authenticate_admin(request)

    if error:
        return error

    item = await d1_first(
        request,
        "DB",
        """
        SELECT item_id, marketplace_status
        FROM metadata
        WHERE item_id = ?
        LIMIT 1
        """,
        item_id,
    )

    if not item:
        return json_response(
            {"error": "Item not found."},
            404,
        )

    if item["marketplace_status"] != "pending":
        return json_response(
            {
                "error": (
                    "Only pending submissions can be approved."
                ),
                "marketplace_status": item["marketplace_status"],
            },
            409,
        )

    moderated_at = datetime.now(timezone.utc).isoformat()

    await d1_run(
        request,
        "DB",
        """
        UPDATE metadata
        SET
            marketplace_status = 'approved',
            moderated_at = ?,
            moderated_by = ?,
            rejection_reason = NULL
        WHERE item_id = ?
          AND marketplace_status = 'pending'
        """,
        moderated_at,
        account["id"],
        item_id,
    )

    updated = await d1_first(
        request,
        "DB",
        """
        SELECT
            item_id,
            item_type,
            item_name,
            marketplace_status,
            submitted_at,
            moderated_at,
            moderated_by,
            rejection_reason
        FROM metadata
        WHERE item_id = ?
        LIMIT 1
        """,
        item_id,
    )

    return {
        "message": "Item approved.",
        "item": updated,
    }


@app.post("/admin/items/{item_id}/reject")
async def reject_item(
    item_id: str,
    request: Request,
    payload: RejectRequest,
):
    account, error = await authenticate_admin(request)

    if error:
        return error

    item = await d1_first(
        request,
        "DB",
        """
        SELECT item_id, marketplace_status
        FROM metadata
        WHERE item_id = ?
        LIMIT 1
        """,
        item_id,
    )

    if not item:
        return json_response(
            {"error": "Item not found."},
            404,
        )

    if item["marketplace_status"] != "pending":
        return json_response(
            {
                "error": (
                    "Only pending submissions can be rejected."
                ),
                "marketplace_status": item["marketplace_status"],
            },
            409,
        )

    reason = (payload.reason or "").strip() or None
    moderated_at = datetime.now(timezone.utc).isoformat()

    await d1_run(
        request,
        "DB",
        """
        UPDATE metadata
        SET
            marketplace_status = 'rejected',
            moderated_at = ?,
            moderated_by = ?,
            rejection_reason = ?
        WHERE item_id = ?
          AND marketplace_status = 'pending'
        """,
        moderated_at,
        account["id"],
        reason,
        item_id,
    )

    updated = await d1_first(
        request,
        "DB",
        """
        SELECT
            item_id,
            item_type,
            item_name,
            marketplace_status,
            submitted_at,
            moderated_at,
            moderated_by,
            rejection_reason
        FROM metadata
        WHERE item_id = ?
        LIMIT 1
        """,
        item_id,
    )

    return {
        "message": "Item rejected.",
        "item": updated,
    }


# ---------------------------------------------------------------------------
# Cloudflare Workers ASGI entry point
# ---------------------------------------------------------------------------

entrypoint = asgi.fetch(app)
