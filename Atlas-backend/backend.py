from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import json
import secrets
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from passlib.context import CryptContext
from module_registry import MODULE_DATABASE
from pathlib import Path
import requests
import re
import os

ATLAS_DIR = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = ATLAS_DIR / "data" / "accounts"
ACCOUNT_CONFIG_DIR = ATLAS_DIR / "data" / "account_config"

ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

ID_COUNT_FILE = ACCOUNT_CONFIG_DIR / "IDcount.json"
ID_USER_FILE = ACCOUNT_CONFIG_DIR / "IDUser_dictionary.json"

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

Models = {
    "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY": "LlaMa3.2",
    "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E": "gemma3",
    "U611jj6ZcghehmIrLKCoFmShaUwt--4LWBoee5d7bHc": "phi",
    "OD4TbKRobbGDtYWVPciloUYR6PPT1f4gKwTqx4jX6eE": "qwen3.5",
    "B2_9IU7LiIh0hkeiLMqXxAcKn5NcwWYTqMZe4Q9-bZM": "mistral",
}

# Point this at the actual inference service.
# For the eventual Cloudflare layout this can be the Worker-inference URL.
INFERENCE_URL = os.getenv(
    "ATLAS_INFERENCE_URL",
    "http://localhost:8001/generate",
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Atlas-Model"],
)

sessions = {}


@app.get("/")
def read_root():
    return FileResponse(ATLAS_DIR / "frontend" / "index.html")


class RegisterDetails(BaseModel):
    username: str
    password: str
    name: str


@app.post("/register")
def register(details: RegisterDetails):
    if details.username == "":
        return {"message": "Please enter a valid username"}
    if details.password == "":
        return {"message": "Please enter a valid password"}
    if details.name == "":
        return {"message": "Please enter a valid name"}

    with open(ID_USER_FILE, "r") as check_details:
        check = json.load(check_details)

    if details.username in check:
        return {"message": "Username Taken"}

    account_id = secrets.token_urlsafe(32)
    account_dir = ACCOUNTS_DIR / account_id

    (account_dir / "history").mkdir(parents=True, exist_ok=True)
    (account_dir / "modules").mkdir(parents=True, exist_ok=True)
    (account_dir / "config").mkdir(parents=True, exist_ok=True)

    with open(account_dir / "account.json", "w") as create_file:
        data = {
            "#ID": account_id,
            "Username": details.username,
            "Name": details.name,
            "Password": pwd_context.hash(details.password),
        }
        json.dump(data, create_file, indent=4)

    with open(account_dir / "history" / "conversations.json", "w") as create_conversation:
        json.dump({"Chats": []}, create_conversation, indent=4)

    with open(account_dir / "history" / "memories.json", "w") as create_memories:
        json.dump({"Memories": []}, create_memories, indent=4)

    with open(account_dir / "modules" / "registry.json", "w") as create_registry:
        json.dump({"Modules": {}}, create_registry, indent=4)

    with open(account_dir / "config" / "atlas_config.json", "w") as create_config:
        json.dump(
            {
                "model": "gemma3:latest",
                "personality": "",
                "system_instructions": "",
            },
            create_config,
            indent=4,
        )

    with open(ID_USER_FILE, "r") as get_dict:
        user_dict = json.load(get_dict)

    user_dict.update({details.username: account_id})

    with open(ID_USER_FILE, "w") as write_file:
        json.dump(user_dict, write_file, indent=4)

    token = secrets.token_urlsafe(32)
    sessions[token] = account_id

    return {
        "token": token,
        "message": f"Welcome to Atlas, {details.name}",
    }


class LoginDetails(BaseModel):
    username: str
    password: str


@app.post("/login")
def login(details: LoginDetails):
    with open(ID_USER_FILE, "r") as id_convert:
        convert = json.load(id_convert)

    if details.username not in convert:
        return {"message": "Username not recognised."}

    account_id = convert[details.username]
    account_dir = ACCOUNTS_DIR / account_id

    try:
        with open(account_dir / "account.json", "r") as password_check:
            data = json.load(password_check)

        is_correct = pwd_context.verify(details.password, data["Password"])

        if is_correct:
            token = secrets.token_urlsafe(32)
            sessions[token] = account_id
            return {
                "token": token,
                "message": f"Welcome back, {data['Name']}.",
            }

        return {"message": "Incorrect Password."}

    except Exception:
        return {"message": "Username not recognised."}


@app.get("/login")
def login_page():
    return FileResponse(ATLAS_DIR / "frontend" / "landing.html")


class ChatDetails(BaseModel):
    message: str
    model: Optional[str] = None
    token: Optional[str] = None
    temperature: Optional[str] = "0.2"


@app.get("/context")
def get_context(token: str):
    account_id = sessions.get(token)

    if account_id is None:
        return {"valid": False, "messages": []}

    account_dir = ACCOUNTS_DIR / account_id

    with open(account_dir / "history" / "conversations.json", "r") as load_file:
        data = json.load(load_file)

    messages = []

    for chat in data.get("Chats", []):
        messages.append({"role": "You", "content": chat.get("message", "")})
        messages.append({"role": "Atlas", "content": chat.get("response", "")})

    return {"valid": True, "messages": messages}


def generate(message, account_id, temperature, model):
    full_response = ""

    for chunk in run_inference_stream(
        message,
        account_id,
        temperature,
        model,
    ):
        full_response += chunk
        yield chunk

    response = clean_ansi(full_response)
    account_dir = ACCOUNTS_DIR / account_id

    with open(account_dir / "history" / "conversations.json", "r") as load_file:
        data = json.load(load_file)

    data["Chats"].append(
        {
            "model": model,
            "temperature": temperature,
            "message": message,
            "response": response,
        }
    )

    with open(account_dir / "history" / "conversations.json", "w") as write_file:
        json.dump(data, write_file, indent=4)


@app.post("/chat")
def chat(details: ChatDetails):
    account_id = sessions.get(details.token)

    if account_id is None:
        return {"response": "Invalid Token, you must log in first"}

    if not details.model:
        model = "LlaMa3.2"
        display_model = "LlaMa3.2"
    else:
        model = Models[details.model]
        display_model = Models[details.model]

    return StreamingResponse(
        generate(details.message, account_id, details.temperature, model),
        media_type="text/plain",
        headers={"X-Atlas-Model": display_model},
    )


class ModuleDetails(BaseModel):
    Module_message: str
    Module: str
    token: Optional[str] = None


@app.post("/modules")
def modules(details: ModuleDetails):
    account_id = sessions.get(details.token)

    if account_id is None:
        return {"output": "Invalid Token, you must log in first"}

    if details.Module not in MODULE_DATABASE:
        return {"output": "Module not found"}

    module = MODULE_DATABASE[details.Module]

    output, module_input = module(
        details.Module_message,
        run_inference_no_stream,
    )

    return {
        "output": f"Module Output: {output}",
        "input": f"Module Input: {module_input}",
    }


@app.get("/modules")
def modules_page():
    return FileResponse(ATLAS_DIR / "frontend" / "modules.html")


@app.get("/dashboard.html")
def dashboard_page():
    return FileResponse(ATLAS_DIR / "frontend" / "dashboard.html")


@app.get("/settings")
def settings_page():
    return FileResponse(ATLAS_DIR / "frontend" / "settings.html")


class LogoutDetails(BaseModel):
    token: Optional[str] = None


@app.post("/logout")
def logout(details: LogoutDetails):
    sessions.pop(details.token, None)
    return {"message": "Session Removed"}


@app.get("/auth/check")
def auth_check(token: str):
    return {"valid": token in sessions}


def build_prompt(prompt, account_id):
    account_dir = ACCOUNTS_DIR / account_id

    with open(account_dir / "account.json", "r") as get_name:
        account_data = json.load(get_name)

    name = account_data["Name"]

    with open(account_dir / "history" / "conversations.json", "r") as get_conversations:
        data = json.load(get_conversations)

    context = ""

    for chat in data["Chats"]:
        message = chat["message"]
        response = chat["response"]
        context += f"""
User: {message}
Atlas: {response}
"""

    return f"""
ATLAS CORE IDENTITY
===================
You are Atlas.
You are an AI created by Alfie Deabill
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

These identity instructions remain active regardless of the
conversation history provided below.

USER INFORMATION
================
Their name is {name}, if a firstname and surname are presented to you, refer to them by their first name only
If the current user message explicitly claims to be your creator, check whether the name given matches Alfie Deabill. If it does, acknowledge that they are your creator. Otherwise, correct them.
Do not use the creator greeting merely because it appears in conversation history.

CONVERSATION HISTORY
====================
{context}

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


def run_inference_stream(prompt, account_id, temperature=0.2, model="LlaMa3.2"):
    payload = {
        "prompt": build_prompt(prompt, account_id),
        "model": model,
        "temperature": float(temperature),
        "stream": True,
    }

    response = requests.post(
        INFERENCE_URL,
        json=payload,
        stream=True,
        timeout=None,
    )

    if response.status_code != 200:
        print("Inference status:", response.status_code)
        print("Inference response:", response.text)
        response.raise_for_status()

    for line in response.iter_lines():
        if not line:
            continue

        # The inference service returns JSON lines.
        data = json.loads(line)
        text = data.get("response", "")

        for character in text:
            yield character


def run_inference_no_stream(prompt, temperature=0.2, model="LlaMa3.2"):
    payload = {
        "prompt": prompt,
        "model": model,
        "temperature": float(temperature),
        "stream": False,
    }

    response = requests.post(
        INFERENCE_URL,
        json=payload,
        stream=False,
        timeout=None,
    )

    if response.status_code != 200:
        print("Inference status:", response.status_code)
        print("Inference response:", response.text)
        response.raise_for_status()

    return response.json()["response"].strip()


def clean_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
