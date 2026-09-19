import hashlib
import json
import os
import re
import secrets
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from pyodide.ffi import to_js
from js import Object, fetch
from workers import asgi

try:
    from module_registry import MODULE_DATABASE
except Exception:
    MODULE_DATABASE = {}

INFERENCE_URL = os.getenv(
    "INFERENCE_URL",
    "https://inference.modulogical.com/generate",
)

pwd_hasher = PasswordHasher()

Models = {
    "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY": "LlaMa3.2:latest",
    "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E": "gemma3:latest",
    "U611jj6ZcghehmIrLKCoFmShaUwt--4LWBoee5d7bHc": "phi:latest",
    "OD4TbKRobbGDtYWVPciloUYR6PPT1f4gKwTqx4jX6eE": "qwen3.5:latest",
    "B2_9IU7LiIh0hkeiLMqXxAcKn5NcwWYTqMZe4Q9-bZM": "mistral:latest"
}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["X-Atlas-Model"],
)

def env_from(request: Request):
    return request.scope["env"]

def token_from(request: Request, token: Optional[str] = None):
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def new_token() -> str:
    return secrets.token_urlsafe(32)

def new_account_id() -> str:
    return secrets.token_urlsafe(32)

async def d1_first(request: Request, sql: str, *values):
    env = env_from(request)
    return await env.DB.prepare(sql).bind(*values).first()

async def d1_all(request: Request, sql: str, *values):
    env = env_from(request)
    result = await env.DB.prepare(sql).bind(*values).all()
    return result.results or []

async def d1_run(request: Request, sql: str, *values):
    env = env_from(request)
    return await env.DB.prepare(sql).bind(*values).run()

async def authenticate(request: Request, token: Optional[str] = None):
    actual = token_from(request, token)
    if not actual:
        return None
    return await d1_first(
        request,
        """SELECT a.id, a.username, a.name
           FROM sessions s JOIN accounts a ON a.id = s.account_id
           WHERE s.token_hash = ?""",
        token_hash(actual),
    )

JSON_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

def json_response(data, status=200):
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

class LogoutDetails(BaseModel):
    token: Optional[str] = None

@app.post("/register")
async def register(details: RegisterDetails, request: Request):
    username, name = details.username.strip(), details.name.strip()
    if not username:
        return json_response({"message": "Please enter a valid username"})
    if not details.password:
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
    modules = await d1_all(
        request,
        "SELECT module_name, module_data, created_at FROM account_modules WHERE account_id = ? ORDER BY id ASC",
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
        "memories": memories,
        "conversations": conversations,
        "modules": modules,
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
ATLAS CORE IDENTITY
===================
You are Atlas.
You are an AI created by Alfie
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
"""

async def run_inference(prompt: str, temperature: float, model: str):
    result = await fetch_json(
        INFERENCE_URL,
        {"prompt": prompt, "model": model, "temperature": float(temperature), "stream": False},
    )
    response = result.get("response") or result.get("text") or result.get("output")
    if response is None:
        raise RuntimeError(f"Inference service returned no response field: {result}")
    return str(response)


async def stream_inference(prompt: str, temperature: float, model: str):
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

    print(f"[Atlas] streaming inference request -> {INFERENCE_URL}")
    response = await fetch(INFERENCE_URL, options)
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
    temperature = details.temperature if details.temperature is not None else 0.2

    try:
        prompt = await build_prompt(details.message, account, request)
    except Exception as exc:
        print(f"[Atlas] CHAT PROMPT ERROR: {type(exc).__name__}: {exc}")
        return json_response(
            {"error": "Could not prepare chat request."},
            502,
        )

    async def generate_stream():
        chunks = []

        try:
            async for piece in stream_inference(prompt, temperature, model):
                piece = clean_ansi(piece)
                if piece:
                    chunks.append(piece)
                    yield piece
        except Exception as exc:
            print(f"[Atlas] STREAM ERROR: {type(exc).__name__}: {exc}")
            # Keep internal exception details out of the client response.
            # The client receives the text already generated, if any.
            if not chunks:
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
