from fastapi import FastAPI, Form
from pydantic import BaseModel
from typing import Optional
import json
import secrets
from fastapi.middleware.cors import CORSMiddleware
import random
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
import subprocess
import re
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from module_registry import MODULE_DATABASE
from pathlib import Path
import requests
import time
import os
#hi
ATLAS_DIR = Path(__file__).resolve().parent.parent

ACCOUNTS_DIR = ATLAS_DIR / "data" / "accounts"
ACCOUNT_CONFIG_DIR = ATLAS_DIR / "data" / "account_config"

ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

ID_COUNT_FILE = ACCOUNT_CONFIG_DIR / "IDcount.json"
ID_USER_FILE = ACCOUNT_CONFIG_DIR / "IDUser_dictionary.json"

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

Models={
    "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY" : "LlaMa3.2",
    "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E" : "gemma3",
    "U611jj6ZcghehmIrLKCoFmShaUwt--4LWBoee5d7bHc" : "phi",
    "OD4TbKRobbGDtYWVPciloUYR6PPT1f4gKwTqx4jX6eE" : "qwen3.5",
    "B2_9IU7LiIh0hkeiLMqXxAcKn5NcwWYTqMZe4Q9-bZM" : "mistral"
}

app = FastAPI()

app.mount("/assets", StaticFiles(directory=ATLAS_DIR / "frontend" / "assets"), name="assets")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Atlas-Model"],
)



sessions={}

@app.get("/")
def read_root():
    return FileResponse(ATLAS_DIR / "frontend" / "index.html") #swap out for user

class RegisterDetails(BaseModel):
    username : str
    password : str
    name: str
@app.post("/register")
def register(details: RegisterDetails):
    if details.username == "":
        return {"message" : "Please enter a valid username"}
    if details.password == "":
        return {"message" : "Please enter a valid password"}
    if details.name == "":
        return {"message" : "Please enter a valid name"}
    with open(ID_USER_FILE, "r") as Check_details:
        check=json.load(Check_details)
        if details.username in check:
            return {"message" : "Username Taken"}
    ID=secrets.token_urlsafe(32)
    account_dir = Path(ATLAS_DIR / "data/accounts") / ID
    (account_dir / "history").mkdir(parents=True, exist_ok=True)
    (account_dir / "modules").mkdir(parents=True, exist_ok=True)
    (account_dir / "config").mkdir(parents=True, exist_ok=True)
    with open(account_dir / "account.json", "w") as Create_file:
     data={
        "#ID" : ID,
        "Username" : details.username,
        "Name" : details.name,
        "Password" : pwd_context.hash(details.password)
    }
     json.dump(data, Create_file, indent=4)
     with open(account_dir / "history" / "conversations.json", "w") as Create_conversation:
         chats={
             "Chats" : []
         }
         json.dump(chats, Create_conversation, indent=4)
     with open(account_dir / "history" / "memories.json", "w") as Create_memories:
         memories={
             "Memories" : []
         }
         json.dump(memories, Create_memories, indent=4)
     with open(account_dir / "modules" / "registry.json", "w") as Create_registry:
         registry={
             "Modules" : {}
         }
         json.dump(registry, Create_registry, indent=4)
     with open(account_dir / "config" / "atlas_config.json", "w") as Create_config:
         config={
                 "model" : "gemma3:latest",
                 "personality" : "",
                 "system_instructions": ""
         }
         json.dump(config, Create_config, indent=4)
     with open(ID_USER_FILE, "r") as get_dict:
        user_dict=json.load(get_dict)
        with open(ID_USER_FILE, "w") as Write_file:
            user_dict.update({details.username : ID})
            json.dump(user_dict, Write_file, indent=4)
            token=secrets.token_urlsafe(32)
            sessions[token] = ID
            return {"token" : token, "message" : f"Welcome to Atlas, {details.name}"}

class LoginDetails(BaseModel):
    username : str
    password : str
@app.post("/login")
def login(details : LoginDetails):
    with open(ID_USER_FILE, "r") as IDconvert:
        convert=json.load(IDconvert)
        if details.username not in convert.keys():
            return {"message" : "Username not recognised."}
        else:
            ID=convert[details.username]
            account_dir = Path(ATLAS_DIR / "data/accounts") / ID
            try:
             with open(account_dir / "account.json", "r") as password_check:
                data=json.load(password_check)
                is_correct = pwd_context.verify(details.password, data['Password'])
                if is_correct is True:
                    token=secrets.token_urlsafe(32)
                    sessions[token] = ID
                    return {"token" : token,
                            "message" : f"Welcome back, {data['Name']}."}
                else:
                    return {"message" : "Incorrect Password."}
            except Exception as e:
                return {"message" : "Username not recognised."}
@app.get("/login")
def login_page():
    return FileResponse(
        ATLAS_DIR / "frontend" / "landing.html"
    )
                
class ChatDetails(BaseModel):
    message : str
    model : Optional[str]
    token : Optional[str]
    temperature : Optional[str]
@app.get("/context")
def get_context(token: str):
    account_id = sessions.get(token)

    if account_id is None:
        return {"valid": False, "messages": []}
    account_dir = Path(ATLAS_DIR / "data/accounts") / account_id
    with open(account_dir / "history" / "conversations.json", "r") as ID_data_load:
        data = json.load(ID_data_load)

    messages = []

    for chat in data.get("Chats", []):
        messages.append({
            "role": "You",
            "content": chat.get("message", "")
        })
        messages.append({
            "role": "Atlas",
            "content": chat.get("response", "")
        })

    return {"valid": True, "messages": messages}
def generate(message, account_id, temperature, model):
                                full_response = ""
                                for chunk in run_ollama_stream(message, account_id, temperature, model, stream=True):
                                    full_response += chunk
                                    yield chunk
                                response = clean_ansi(full_response)
                                account_dir = Path(ATLAS_DIR / "data/accounts") / account_id
                                with open(account_dir / f"history" / "conversations.json", "r") as ID_data_load:
                                    data=json.load(ID_data_load)
                                    data["Chats"].append({
                                        "model": model,
                                        "temperature" : temperature,
                                        "message" : message,
                                        "response" : response
                                    })
                                    with open(account_dir / f"history" / "conversations.json", "w") as ID_data_write:
                                        json.dump(data, ID_data_write, indent=4)

               

@app.post("/chat")
def chat(details : ChatDetails):
    temp=details.temperature
    account_id = sessions.get(details.token)
    if account_id is None:
        return {"response" : "Invalid Token, you must log in first"}
    else:
        if not details.model:
            Model = "LlaMa3.2"
            display_model = "LlaMa3.2"
        else:
            Model = Models[details.model]
            display_model = Models[details.model]
        queue(account_id, details.message, Model, temp)
        generate(details.message, account_id, temp, Model)
        return StreamingResponse(
            generate(details.message, account_id, temp, Model),
            media_type="text/plain",
            headers={"X-Atlas-Model": display_model}
        )
def queue(account_id, message, model, temperature):
    with open(ATLAS_DIR / "data" / "queue.json", "r") as Read_queue:
        queue=json.load(Read_queue)
        queue["queue"].append({
            "id" : account_id,
            "model": model,
            "temperature" : temperature,
            "message" : message
        })
        with open(ATLAS_DIR / "data" / "queue.json", "w") as Write_queue:
            json.dump(queue, Write_queue, indent=4)
@app.get("/chat")
def chat_page():
    return FileResponse(
        ATLAS_DIR / "frontend" / "chat.html"
    )

class ModuleDetails(BaseModel):
    Module_message : str
    Module : str
    token : Optional[str]
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
        run_ollama_no_stream
    )
    return {
        "output": f"Module Output: {output}",
        "input": f"Module Input: {module_input}"
    }
@app.get("/modules")
def modules_page():
    return FileResponse(
        ATLAS_DIR / "frontend" / "modules.html"
    )


@app.get("/dashboard.html")
def dashboard_page():
    return FileResponse(
        ATLAS_DIR / "frontend" / "dashboard.html"
    ) 

@app.get("/settings")
def settings_page():
    return FileResponse(
        ATLAS_DIR / "frontend" / "settings.html"
    )
class LogoutDetails(BaseModel):
    token : Optional[str]
@app.post("/logout")
def logout(details : LogoutDetails):
    sessions.pop(details.token, None)
    return {"message" : "Session Removed"}

@app.get("/auth/check")
def auth_check(token: str):
    if token in sessions:
        return {"valid": True}

    return {"valid": False}

def run_ollama_stream(prompt, account_id, temperature=0.2, model="LlaMa3.2", stream=True):
    context="""
"""
    account_dir = Path(ATLAS_DIR / "data/accounts") / account_id
    with open(account_dir / f"account.json", "r") as get_name:
        data=json.load(get_name)
        name=data["Name"]
    with open(account_dir / "history" / "conversations.json", "r") as get_conversations:
        data=json.load(get_conversations)
        for i in range(len(data["Chats"])):
            message=data["Chats"][i]["message"]
            response=data["Chats"][i]["response"]
            message_pair=f"""
User: {message}
Atlas: {response}
"""
            context += message_pair

    prompt_engineering=f"""
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
=================
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
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt_engineering,
            "stream": True,
            "options": {
                "temperature": float(temperature),
                "repeat_penalty": 1.15,
                "repeat_last_n": 64
            }
        },
        stream=stream
    )

    if response.status_code != 200:
       print("Ollama status:", response.status_code)
       print("Ollama response:", response.text)
       response.raise_for_status()

    if stream:
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                text = data["response"]
                for character in text:
                    yield character
    else:
        return response.json()["response"].strip()


def run_ollama_no_stream(prompt, temperature=0.2, model="LlaMa3.2"):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "repeat_penalty": 1.15,
                "repeat_last_n": 64
            }
        }
    )

    if response.status_code != 200:
       print("Ollama status:", response.status_code)
       print("Ollama response:", response.text)
       response.raise_for_status()

    return response.json()["response"].strip()

def clean_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '',  text)
    


    
    
      
