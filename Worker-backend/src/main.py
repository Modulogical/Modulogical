import ast
import hashlib
import json
import os
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from pyodide.ffi import to_js
from js import Object, fetch
from workers import asgi 
#imports; external libraries that the code depends on



try: #load module registry
    from module_registry import MODULE_DATABASE
except Exception: #if an error occurs, do this instead
    MODULE_DATABASE = {}

INFERENCE_URL = os.getenv( #holds the url that connects to the AI server
    "INFERENCE_URL",
    "https://inference.modulogical.com/generate",
)

THEME_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
DEFAULT_THEME = "Company-Colours"

pwd_hasher = PasswordHasher() #hashes the passwords to make them secure

Models = { #tokens that are authenticated from the frontend and point to a specific model
    "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY": "LlaMa3.2:latest",
    "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E": "gemma3:latest",
    "Af3hf8E0SbC0_o44yQnhvFtpMtjOq73wU_iKquZL2AA": "gemma4:26b",
    "Ik0LpuQXHGpAsl6EtTJDzq09SyTAxBh9rdZvQ4UZkpU": "gpt-oss:20b"
}

app = FastAPI() #defines the app
app.add_middleware( #adds CORS middleware 
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["X-Atlas-Model"],
)

def env_from(request: Request):
    return request.scope["env"]

def token_from(request: Request, token: Optional[str] = None): #grabs token from frontend
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None

def token_hash(token: str) -> str: 
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def new_token() -> str: #generates a hashed token
    return secrets.token_urlsafe(32)

def new_account_id() -> str: #generates a new account id
    return secrets.token_urlsafe(32)

async def d1_first(request: Request, sql: str, *values): 
    env = env_from(request)
    return await env.DB.prepare(sql).bind(*values).first()

async def d1_all(request: Request, sql: str, *values): #connects to D1 database and performs multiple operations
    env = env_from(request)
    result = await env.DB.prepare(sql).bind(*values).all()
    return result.results or []

async def d1_run(request: Request, sql: str, *values): #connects to D1 database and performs an SQL query
    env = env_from(request)
    return await env.DB.prepare(sql).bind(*values).run()

async def ensure_account_preferences(request: Request):
    """Create the small per-account preferences table if this deployment has not
    created it yet. This keeps theme preferences separate from core account data
    and makes the endpoint safe for existing accounts.
    """
    await d1_run(
        request,
        """CREATE TABLE IF NOT EXISTS account_preferences (
               account_id TEXT PRIMARY KEY,
               theme TEXT NOT NULL DEFAULT 'holographic',
               FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
           )""",
    )

async def authenticate(request: Request, token: Optional[str] = None): #verifies the token sent by the frontend
    actual = token_from(request, token)
    if not actual:
        return None
    return await d1_first(
        request,
        """SELECT a.id, a.username, a.name, a.account_subscription_status
           FROM sessions s JOIN accounts a ON a.id = s.account_id
           WHERE s.token_hash = ?""",
        token_hash(actual),
    )

@app.get("/auth/me")
async def auth_me(request: Request, token: Optional[str] = None):
    account = await authenticate(request, token)

    if not account:
        return JSONResponse(
            status_code=401,
            content={"valid": False},
        )

    return {
        "valid": True,
        "account_id": account["id"],
        "username": account["username"],
        "name": account["name"],
        "account_subscription_status":
            account["account_subscription_status"],
    }

JSON_HEADERS = { #configurations for frontend
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}
#change check
def json_response(data, status=200): #sends data to frontend for display
    return Response(
        content=json.dumps(data),
        status_code=status,
        media_type="application/json",
        headers=JSON_HEADERS,
    )

async def fetch_json(url: str, payload: dict):
    # Cloudflare's Python Workers use the JS Fetch API.
    # Use Object.fromEntries as the dict converter so nested Python dicts
    # become real JavaScript objects rather than Python objects.
    options = to_js(
        {
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "body": json.dumps(payload),
        },
        dict_converter=Object.fromEntries,
    )

    print(f"[Atlas] inference request -> {url}")
    response = await fetch(url, options)
    text = await response.text()
    print(f"[Atlas] inference response <- {response.status}")

    if not response.ok:
        raise RuntimeError(
            f"Inference service returned HTTP {response.status}: {text[:1000]}"
        )

    if not text:
        raise RuntimeError("Inference service returned an empty response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"response": text}

# ------- Classes ------- #
# Classes define the schema that comes from the frontend to the backend

class RegisterDetails(BaseModel):
    username: str
    password: str
    name: str

class LoginDetails(BaseModel):
    username: str
    password: str

class ChatDetails(BaseModel):
    message: str
    model: Optional[str] = None
    token: Optional[str] = None
    temperature: Optional[float] = 0.2

class ModuleDetails(BaseModel):
    Module_message: str
    Module: str
    token: Optional[str] = None

class UsernameChange(BaseModel):
    username: str
    token: Optional[str] = None
    old_username: str

class PasswordChange(BaseModel):
    pw : str
    confirm: str
    token: Optional[str] = None
    username: str

class LogoutDetails(BaseModel):
    token: Optional[str] = None

class ThemeDetails(BaseModel):
    theme: str
    token: Optional[str] = None

# ----- Endpoints ----- #
# Called by the browser /api; verifies and performs the action
# Methods:
# POST -- adds information
# GET -- retrieves information
# PATCH -- makes a change to existing information

@app.post("/register") # "/register" defines the endpoint
async def register(details: RegisterDetails, request: Request): 
    # async means it can run alongside other things
    # 'details' links to the class variables, request determines the request coming through
    username, name = details.username.strip(), details.name.strip()
    if not username: # checks if the variable exists
        return json_response({"message": "Please enter a valid username"})
    if not details.password: # details defines from which class it belongs to; checks for existing variable
        return json_response({"message": "Please enter a valid password"})
    if not name:
        return json_response({"message": "Please enter a valid name"})

    if await d1_first(request, "SELECT id FROM accounts WHERE username = ?", username):
        return json_response({"message": "Username Taken"})

    account_id = new_account_id()
    await d1_run(
        request,
        "INSERT INTO accounts (id, username, name, password_hash) VALUES (?, ?, ?, ?)",
        account_id, username, name, pwd_hasher.hash(details.password),
    )
    await d1_run(
        request,
        """INSERT INTO account_config
           (account_id, model, personality, system_instructions)
           VALUES (?, 'gemma3:latest', '', '')""",
        account_id,
    )
    await ensure_account_preferences(request)
    await d1_run(
        request,
        "INSERT OR IGNORE INTO account_preferences (account_id, theme) VALUES (?, ?)",
        account_id,
        DEFAULT_THEME,
    )

    token = new_token()
    await d1_run(
        request, "INSERT INTO sessions (token_hash, account_id) VALUES (?, ?)",
        token_hash(token), account_id,
    )
    return json_response({"token": token, "message": f"Welcome to Atlas, {name}"}, 201)

@app.post("/login")
async def login(details: LoginDetails, request: Request):
    account = await d1_first(
        request,
        "SELECT id, username, name, password_hash FROM accounts WHERE username = ?",
        details.username.strip(),
    )
    if not account:
        return json_response({"message": "Username not recognised."})
    try:
        correct = pwd_hasher.verify(account["password_hash"], details.password)
    except (VerifyMismatchError, VerificationError, ValueError, TypeError):
        correct = False
    if not correct:
        return json_response({"message": "Incorrect Password."})

    token = new_token()
    await d1_run(
        request, "INSERT INTO sessions (token_hash, account_id) VALUES (?, ?)",
        token_hash(token), account["id"],
    )
    return json_response({"token": token, "message": f"Welcome back, {account['name']}."})

@app.get("/auth/check")
async def auth_check(request: Request, token: Optional[str] = None):
    return json_response({"valid": await authenticate(request, token) is not None})

@app.post("/logout")
async def logout(details: LogoutDetails, request: Request):
    token = token_from(request, details.token)
    if token:
        await d1_run(request, "DELETE FROM sessions WHERE token_hash = ?", token_hash(token))
    return json_response({"message": "Session Removed"})

@app.patch("/settings/ChangeUsername")
async def settings_changeusername(details: UsernameChange, request: Request):
    token = token_from(request, details.token)
    if not token:
        return json_response({"username-notice": "You are not logged in",
                              "status" : "pending"}, 401)

    account = await authenticate(request, token)
    if not account:
        return json_response({"username-notice": "Could not find account",
                              "status" : "pending"}, 401)

    new_username = details.username.strip()
    if not new_username:
        return json_response({"username-notice": "Please enter a valid username",
                              "status" : "pending"}, 400)

    existing = await d1_first(
        request, "SELECT id FROM accounts WHERE username = ?", new_username
    )

    old = await d1_first(
        request, "SELECT id, username FROM accounts where username = ?", details.old_username
    )

    if old["username"] == new_username:
        return json_response({"username-notice" : "New username cannot be the same as the old username",
                              "status" : "pending"}, 400)
    if existing and existing["id"] != account["id"]:
        return json_response({"username-notice": "Username Taken",
                              "status" : "pending"}, 409)

    await d1_run(
        request,
        "UPDATE accounts SET username = ? WHERE id = ?",
        new_username,
        account["id"],
    )
    return json_response({"username-notice": "Username changed successfully!",
                          "status" : "success"})

@app.patch("/settings/ChangePassword")
async def settings_changepassword(request: Request, details: PasswordChange):
    token = token_from(request, details.token)
    if not token:
        return json_response({"password-notice": "You are not logged in"}, 401)

    account = await authenticate(request, token)
    if not account:
        return json_response({"password-notice": "Could not find account"}, 401)

    new_pw = details.pw.strip()
    confirm = details.confirm.strip()

    if len(new_pw) < 8:
        return json_response({"password-notice": "Password must be at least 8 characters",
                              "status" : "error"}, 400)
    if new_pw != confirm:
        return json_response({"password-notice": "Entered passwords must match",
                              "status" : "error"}, 400)

    existing = await d1_first(
        request, "SELECT password_hash FROM accounts WHERE id = ?", account["id"]
    )
    try:
        same = pwd_hasher.verify(existing["password_hash"], new_pw)
    except (VerifyMismatchError, VerificationError):
        same = False
    if same:
        return json_response({"password-notice": "New password must be different from your old one",
                              "status" : "pending"}, 400)

    await d1_run(
        request,
        "UPDATE accounts SET password_hash = ? WHERE id = ?",
        pwd_hasher.hash(new_pw),
        account["id"],
    )
    return json_response({"password-notice": "Password changed successfully!",
                          "status" : "success"})

@app.get("/settings/theme")
async def get_theme(request: Request, token: Optional[str] = None):
    account = await authenticate(request, token)
    if not account:
        return json_response({"message": "You are not logged in."}, 401)

    await ensure_account_preferences(request)
    preference = await d1_first(
        request,
        "SELECT theme FROM account_preferences WHERE account_id = ?",
        account["id"],
    )

    stored_theme = preference["theme"] if preference else None
    theme = stored_theme if stored_theme and THEME_KEY_PATTERN.fullmatch(stored_theme) else DEFAULT_THEME
    return json_response({"theme": theme})


@app.patch("/settings/theme")
async def set_theme(request: Request, details: ThemeDetails):
    # Authenticate the session token; never trust an account ID from the browser
    # when deciding whose preference should be changed.
    token = token_from(request, details.token)
    account = await authenticate(request, token)
    if not account:
        return json_response({"message": "You are not logged in."}, 401)

    theme = details.theme
    if not isinstance(theme, str) or not THEME_KEY_PATTERN.fullmatch(theme):
        return json_response(
            {"message": "Invalid theme key."},
            400,
        )

    await ensure_account_preferences(request)
    await d1_run(
        request,
        """INSERT INTO account_preferences (account_id, theme)
           VALUES (?, ?)
           ON CONFLICT(account_id) DO UPDATE SET theme = excluded.theme""",
        account["id"],
        theme,
    )

    return json_response({"theme": theme, "message": "Theme saved successfully."})


@app.get("/context")
async def get_context(request: Request, token: Optional[str] = None):
    account = await authenticate(request, token)
    if not account:
        return json_response({"valid": False, "messages": []})

    config = await d1_first(
        request,
        "SELECT model, personality, system_instructions FROM account_config WHERE account_id = ?",
        account["id"],
    )
    await ensure_account_preferences(request)
    preference = await d1_first(
        request,
        "SELECT theme FROM account_preferences WHERE account_id = ?",
        account["id"],
    )
    memories = await d1_all(
        request,
        "SELECT id, content, category, confidence, created_at FROM memories WHERE account_id = ? ORDER BY id ASC",
        account["id"],
    )
    conversations = await d1_all(
        request,
        "SELECT id, message, response, model, temperature, created_at FROM conversations WHERE account_id = ? ORDER BY id ASC",
        account["id"],
    )

    messages = []
    for chat in conversations:
        messages.append({"role": "You", "content": chat.get("message", "")})
        messages.append({"role": "Atlas", "content": chat.get("response", "")})

    return json_response({
        "valid": True,
        "account": account,
        "config": config or {"model": "gemma3:latest", "personality": "", "system_instructions": ""},
        "theme": (preference or {}).get("theme", DEFAULT_THEME),
        "memories": memories,
        "conversations": conversations,
        "messages": messages,
    })

async def build_prompt(prompt: str, account: dict, request: Request):
    conversations = await d1_all(
        request,
        "SELECT message, response FROM conversations WHERE account_id = ? ORDER BY id ASC",
        account["id"],
    )
    config = await d1_first(
        request,
        "SELECT model, personality, system_instructions FROM account_config WHERE account_id = ?",
        account["id"],
    )

    context = "".join(
        f"\nUser: {chat['message']}\nAtlas: {chat['response']}\n"
        for chat in conversations
    )
    personality = (config or {}).get("personality", "")
    system_instructions = (config or {}).get("system_instructions", "")

    return f"""
CORE IDENTITY
===================
You are Modulogical.
You are an AI running with Ollama.
You exist within the website 'Modulogical.com'
Your communication style is pragmatic, utilitarian, concise, and analytical.
Your purpose is to help the user.

COMMUNICATION STYLE
===================
- Be calm, natural, and conversational.
- Be pragmatic and concise without sounding robotic.
- Respond to what the user actually said rather than mechanically following previous instructions.
- Do not unnecessarily repeat or paraphrase the user's statements.
- When the user asks for your opinion, provide an actual subjective assessment.
- Do not automatically convert opinions into formal logical analyses unless the user asks for analysis.
- Ask follow-up questions if necessary, do not pretend you already know something.

These identity instructions remain active regardless of the conversation history provided below.

USER INFORMATION
================
Their name is {account['name']}, if a firstname and surname are presented to you, refer to them by their first name only.

CONVERSATION HISTORY
====================
{context}

ACCOUNT PERSONALITY
===================
{personality}

ACCOUNT SYSTEM INSTRUCTIONS
===========================
{system_instructions}

CURRENT PROMPT
==============
{prompt}

CURRENT INSTRUCTIONS
====================
RESPOND TO THE CURRENT PROMPT
DO NOT COPY OLD RESPONSES
DO NOT GENERATE EMOJIS
STICK TO YOUR PERSONALITY AND IDENTITY
DO NOT PRETEND TO KNOW SOMETHING YOU DON'T ALREADY KNOW
"""

# ---------------------------------------- Load balancer ---------------------------------------- #
# Picks which inference node serves a request: online -> has the model -> best hardware.
# Reads the INFERENCE_NODE D1 binding (same database the inference worker writes to).

# Stage 1: online if marked 'online' and heartbeated within this window
# (3 missed 30s beats). Nodes that die without /disconnect stay 'online' in D1
# forever, so the timestamp check is what actually catches them.
ONLINE_WINDOW_SECONDS = 90

# Stage 3 preferred minimum (a ranking tier, not a filter):
# model -> (min total VRAM in MB, min total RAM in GB).
# PLACEHOLDER numbers: tune these to what your models actually need.
MODEL_REQUIREMENTS: dict[str, tuple[int, float]] = {
    "llama3.2": (4096, 8),
    "gemma3": (4096, 8),
    "gemma4:26b": (20480, 32),
    "gpt-oss:20b": (16384, 24),
}
DEFAULT_REQUIREMENT = (0, 0)  # unknown model: no hardware floor

# Stage 3 ranking weights (higher score = better node). Each term is 0..1.
W_IDLE = 0.5         # GPU idleness right now
W_VRAM_FREE = 0.3    # free VRAM, relative to the best candidate
W_VRAM_TOTAL = 0.2   # total VRAM (capability), relative to the best candidate
JITTER = 0.05        # random tie-break so near-equal nodes share bursts
TIER_BONUS = 2.0     # meeting the hardware floor always beats not meeting it

_QUERY = """
SELECT n.node_id, n.status, n.last_heartbeat, n.tunnel_hostname,
       n.vram, n.ram, n.models AS node_models,
       h.models AS hb_models, h.gpu_vram_available, h.gpu_utilisation_percent
FROM inference_nodes n
LEFT JOIN heartbeats h ON h.node_id = n.node_id
WHERE n.status = 'online'
"""

# ------------------------------- parsing ------------------------------- #

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _norm(model: str) -> str:
    m = str(model).strip().lower()
    return m if ":" in m else f"{m}:latest"


def _requirement(model: str) -> tuple[int, float]:
    m = _norm(model)
    return (
        MODEL_REQUIREMENTS.get(m)
        or MODEL_REQUIREMENTS.get(m.split(":")[0])
        or DEFAULT_REQUIREMENT
    )


def _num(value: Any, default: float = 0.0) -> float:
    """First number in a TEXT value; 'not recorded' etc. -> default."""
    match = _NUMBER.search(str(value)) if value is not None else None
    return float(match.group()) if match else default


def _mb(value: Any, default: float = 0.0) -> float:
    """Like _num, but converts values written as '12.5 GB' to MB."""
    n = _num(value, default)
    return n * 1024 if isinstance(value, str) and "gb" in value.lower() else n


def _models(value: Any) -> list[str]:
    """Parse a models column. Handles JSON, Python-repr (str(list)), or junk."""
    if isinstance(value, (list, tuple)):
        items: Any = value
    elif isinstance(value, str):
        items = None
        for parse in (json.loads, ast.literal_eval):
            try:
                items = parse(value)
                break
            except (ValueError, SyntaxError):
                continue
    else:
        items = None
    if not isinstance(items, (list, tuple)):
        return []
    return [m for m in items if isinstance(m, str)]


def _rows(result: Any) -> list:
    rows = result.get("results") if isinstance(result, dict) else getattr(result, "results", result)
    if hasattr(rows, "to_py"):  # JS proxy -> Python
        rows = rows.to_py()
    return list(rows or [])


def _fresh(value: Any, cutoff: datetime) -> bool:
    try:
        t = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t >= cutoff


# -------------------------------- stages -------------------------------- #

def stage_online(rows: list[dict], now: datetime | None = None) -> list[dict]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    return [
        r for r in rows
        if r.get("status") == "online"
        and r.get("tunnel_hostname")
        and _fresh(r.get("last_heartbeat"), cutoff)
    ]


def stage_model(rows: list[dict], model: str) -> list[dict]:
    wanted = _norm(model)
    out = []
    for r in rows:
        installed = _models(r.get("hb_models")) or _models(r.get("node_models"))
        match = {_norm(m): m for m in installed}.get(wanted)
        if match:
            out.append({**r, "model": match})  # node's own name for the model
    return out


def stage_hardware(rows: list[dict], model: str) -> list[dict]:
    """Rank best-first. The hardware floor is a tier, not a filter: nodes that
    meet it always outrank nodes that don't, but under-spec nodes stay in the
    list as a last resort, so a lone weak node can still serve."""
    need_vram, need_ram = _requirement(model)
    ranked = []
    for r in rows:
        vram_total = _mb(r.get("vram"))
        util = min(max(_num(r.get("gpu_utilisation_percent"), 50.0), 0.0), 100.0)
        ranked.append({
            **r,
            "meets_floor": vram_total >= need_vram and _num(r.get("ram")) >= need_ram,
            "_idle": 1.0 - util / 100.0,
            "_vram_free": _mb(r.get("gpu_vram_available")),
            "_vram_total": vram_total,
        })
    if not ranked:
        return []

    max_free = max(e["_vram_free"] for e in ranked) or 1.0
    max_total = max(e["_vram_total"] for e in ranked) or 1.0
    for e in ranked:
        e["score"] = (
            (TIER_BONUS if e["meets_floor"] else 0.0)
            + W_IDLE * e["_idle"]
            + W_VRAM_FREE * e["_vram_free"] / max_free
            + W_VRAM_TOTAL * e["_vram_total"] / max_total
            + random.random() * JITTER
        )
    return sorted(ranked, key=lambda e: e["score"], reverse=True)


# ------------------------------ public API ------------------------------ #

async def ranked_nodes(db: Any, model: str, exclude: Iterable[str] = ()) -> list[dict]:
    """All eligible nodes for `model`, best first: [{node_id, hostname, model, score}]."""
    skip = set(exclude)
    result = await db.prepare(_QUERY).all()
    rows = [dict(r) for r in _rows(result) if r["node_id"] not in skip]

    rows = stage_online(rows)
    rows = stage_model(rows, model)
    rows = stage_hardware(rows, model)

    return [
        {
            "node_id": r["node_id"],
            "hostname": r["tunnel_hostname"],
            "model": r["model"],
            "score": r["score"],
            "meets_floor": r["meets_floor"],
        }
        for r in rows
    ]


async def select_node(db: Any, model: str, exclude: Iterable[str] = ()) -> dict | None:
    """Best node for `model`, or None if no node qualifies."""
    nodes = await ranked_nodes(db, model, exclude)
    return nodes[0] if nodes else None


# --- Online model list (feeds the chat's model picker, and "auto") ---
_ONLINE_MODELS_QUERY = """
SELECT m.model AS model, n.node_id AS node_id, n.status AS status,
       n.last_heartbeat AS last_heartbeat, n.tunnel_hostname AS tunnel_hostname
FROM models m
JOIN inference_nodes n ON n.node_id = m.node_id
WHERE n.status = 'online'
"""
_MODEL_NAME = re.compile(r"[a-z0-9][a-z0-9._/:+-]{0,99}")  # same rule the heartbeat enforces

# "auto" takes the first of these that is online, else the model with most nodes.
AUTO_PREFERENCE = ["gemma3:latest", "llama3.2:latest"]


async def online_models(db: Any) -> dict[str, int]:
    """Models served by at least one online node: {model name: number of nodes}.
    Uses the same online test as the balancer, so the picker never offers a
    model the balancer would refuse. Each model appears once."""
    result = await db.prepare(_ONLINE_MODELS_QUERY).all()
    rows = stage_online([dict(r) for r in _rows(result)])
    nodes: dict[str, set] = {}
    for r in rows:
        name = str(r["model"]).strip().lower()
        if _MODEL_NAME.fullmatch(name):
            nodes.setdefault(name, set()).add(r["node_id"])
    return {name: len(ids) for name, ids in nodes.items()}


def pick_auto(counts: dict[str, int]) -> str | None:
    for name in AUTO_PREFERENCE:
        if name in counts:
            return name
    return sorted(counts, key=lambda n: (-counts[n], n))[0] if counts else None


async def run_inference(prompt: str, temperature: float, model: str, url: str = INFERENCE_URL):
    result = await fetch_json(
        url,
        {"prompt": prompt, "model": model, "temperature": float(temperature), "stream": False},
    )
    response = result.get("response") or result.get("text") or result.get("output")
    if response is None:
        raise RuntimeError(f"Inference service returned no response field: {result}")
    return str(response)


async def stream_inference(prompt: str, temperature: float, model: str, url: str = INFERENCE_URL):
    """Yield text from the PC inference NDJSON stream as it arrives."""
    payload = {
        "prompt": prompt,
        "model": model,
        "temperature": float(temperature),
        "stream": True,
    }

    options = to_js(
        {
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "body": json.dumps(payload),
        },
        dict_converter=Object.fromEntries,
    )

    print(f"[Atlas] streaming inference request -> {url}")
    response = await fetch(url, options)
    print(f"[Atlas] streaming inference response <- {response.status}")

    if not response.ok:
        body = await response.text()
        raise RuntimeError(
            f"Inference service returned HTTP {response.status}: {body[:1000]}"
        )

    reader = response.body.getReader()
    decoder = __import__("js").TextDecoder.new()
    buffer = ""

    try:
        while True:
            chunk = await reader.read()
            if chunk.done:
                break

            buffer += str(decoder.decode(chunk.value, {"stream": True}))

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[Atlas] Ignoring invalid inference chunk: {line[:500]}")
                    continue

                piece = (
                    data.get("response")
                    or data.get("text")
                    or data.get("output")
                    or ""
                )

                if piece:
                    yield str(piece)

        # Process a final line if the upstream didn't end with a newline.
        line = buffer.strip()
        if line:
            try:
                data = json.loads(line)
                piece = (
                    data.get("response")
                    or data.get("text")
                    or data.get("output")
                    or ""
                )
                if piece:
                    yield str(piece)
            except json.JSONDecodeError:
                pass
    finally:
        try:
            await reader.cancel()
        except Exception:
            pass

@app.post("/chat")
async def chat(details: ChatDetails, request: Request):
    token = token_from(request, details.token)
    account = await authenticate(request, token)
    if not account:
        return json_response({"response": "Invalid Token, you must log in first"}, 401)

    model = Models.get(details.model, details.model) if details.model else "LlaMa3.2"
    if str(model).strip().lower() == "auto":  # frontend "Auto": pick from what is online now
        try:
            model = pick_auto(await online_models(env_from(request).INFERENCE_NODE))
        except Exception as exc:
            print(f"[Atlas] AUTO MODEL ERROR: {type(exc).__name__}: {exc}")
            return json_response({"error": "Could not look up inference nodes."}, 502)
        if not model:
            return json_response({"error": "No inference node is currently available."}, 503)
    temperature = details.temperature if details.temperature is not None else 0.2

    try:
        prompt = await build_prompt(details.message, account, request)
    except Exception as exc:
        print(f"[Atlas] CHAT PROMPT ERROR: {type(exc).__name__}: {exc}")
        return json_response(
            {"error": "Could not prepare chat request."},
            502,
        )

    # Load balancer: online -> has the model -> best hardware. Needs the
    # INFERENCE_NODE D1 binding (same database the inference worker uses).
    try:
        candidates = await ranked_nodes(env_from(request).INFERENCE_NODE, model)
    except Exception as exc:
        print(f"[Atlas] LOAD BALANCER ERROR: {type(exc).__name__}: {exc}")
        return json_response({"error": "Could not look up inference nodes."}, 502)
    if not candidates:
        return json_response({"error": "No inference node is currently available for this model."}, 503)

    async def generate_stream():
        chunks = []

        # Try the best node first; on failure before any text was sent, fall
        # through to the next one (max 3). Once text has streamed we can't switch.
        for node in candidates[:3]:
            url = f"https://{node['hostname']}/generate"
            try:
                async for piece in stream_inference(prompt, temperature, node["model"], url):
                    piece = clean_ansi(piece)
                    if piece:
                        chunks.append(piece)
                        yield piece
                break
            except Exception as exc:
                print(f"[Atlas] STREAM ERROR via {node['node_id']}: {type(exc).__name__}: {exc}")
                if chunks:
                    break  # partial reply already delivered; keep it
        else:
            # Keep internal exception details out of the client response.
            yield "Could not reach inference server."
            return

        response_text = "".join(chunks)

        try:
            await d1_run(
                request,
                """INSERT INTO conversations
                   (account_id, message, response, model, temperature)
                   VALUES (?, ?, ?, ?, ?)""",
                account["id"], details.message, response_text, model, float(temperature),
            )
        except Exception as exc:
            print(f"[Atlas] D1 SAVE ERROR: {type(exc).__name__}: {exc}")

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain; charset=utf-8",
        headers={
            **JSON_HEADERS,
            "X-Atlas-Model": model,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/modules")
async def get_modules(request: Request, token: Optional[str] = None):
    account = await authenticate(request, token)
    if not account:
        return json_response({"error": "Unauthorized"}, 401)
    rows = await d1_all(
        request,
        "SELECT module_name, module_data, created_at FROM account_modules WHERE account_id = ? ORDER BY id ASC",
        account["id"],
    )
    return json_response({"modules": rows})

@app.post("/modules")
async def modules(details: ModuleDetails, request: Request):
    account = await authenticate(request, details.token)
    if not account:
        return json_response({"output": "Invalid Token, you must log in first"}, 401)
    if details.Module not in MODULE_DATABASE:
        return json_response({"output": "Module not found"}, 404)
    return json_response({"output": "Module execution is not enabled in this Worker build."}, 501)

@app.get("/models/online")
async def get_online_models(request: Request, token: Optional[str] = None):
    account = await authenticate(request, token)
    if not account:
        return json_response({"error": "Unauthorized"}, 401)
    try:
        counts = await online_models(env_from(request).INFERENCE_NODE)
    except Exception as exc:
        print(f"[Atlas] ONLINE MODELS ERROR: {type(exc).__name__}: {exc}")
        return json_response({"error": "Could not look up online models."}, 502)
    return json_response({"models": [{"name": name, "nodes": counts[name]} for name in sorted(counts)]})

@app.get("/")
async def root():
    return json_response({
        "service": "modulogical-backend",
        "status": "ok",
        "runtime": "python-worker",
        "database": "D1",
    })

@app.options("/{path:path}")
async def options(path: str):
    return Response(status_code=204, headers=JSON_HEADERS)

def clean_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)

Default = asgi.entrypoint(app)
