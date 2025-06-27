from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, validator, Field
from dotenv import load_dotenv
from typing import List
import os
import httpx

import aiofiles
import time

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Default voice ID

async def generate_voice_audio(text: str, filename_prefix="confession") -> str:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to generate audio")

        audio_bytes = response.content
        timestamp = int(time.time())
        filename = f"{filename_prefix}_{timestamp}.mp3"
        filepath = f"static/audio/{filename}"

        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(audio_bytes)

        return f"/static/audio/{filename}"

app = FastAPI()

class ConfessionRequest(BaseModel):
    text: str

@app.post("/generate-audio")
async def generate_audio(confession: ConfessionRequest):
    audio_url = await generate_voice_audio(confession.text)
    return {"audio_url": audio_url}

from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")


# Load environment variables
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}


app = FastAPI()

### Player Models ###
class Player(BaseModel):
    username: str
    session_id: str

class Confession(BaseModel):
    username: str
    session_id: str
    confession: str

    @validator("confession")
    def must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Confession cannot be empty or just whitespace")
        return v

### Join Endpoint ###
@app.post("/join")
async def join_game(player: Player):
    player_data = player.dict()
    player_data["is_ready"] = False  # ✅ default value for new player

    async with httpx.AsyncClient() as client:
        # Check if player already exists in session
        check_resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/players",
            headers=SUPABASE_HEADERS,
            params={
                "username": f"eq.{player.username}",
                "session_id": f"eq.{player.session_id}"
            }
        )
        if check_resp.status_code == 200 and check_resp.json():
            return {"message": "Player already in session"}

        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/players",
            headers=SUPABASE_HEADERS,
            json=player_data
        )
        try:
            response.raise_for_status()
            return {"message": "Player joined successfully"}
        except httpx.HTTPStatusError:
            return {
                "error": "Join failed",
                "details": response.text,
                "status_code": response.status_code
            }

### Confession Endpoint ###
@app.post("/confess")
async def submit_confession(confession: Confession):
    async with httpx.AsyncClient() as client:
        # ✅ 1. Check if session exists and is active
        session_check = await client.get(
            f"{SUPABASE_URL}/rest/v1/sessions",
            headers=SUPABASE_HEADERS,
            params={
                "id": f"eq.{confession.session_id}",
                "select": "status"
            }
        )
        if session_check.status_code != 200 or not session_check.json():
            raise HTTPException(status_code=404, detail="Session not found")

        status = session_check.json()[0]["status"]
        if status != "active":
            raise HTTPException(status_code=403, detail="Session not active yet")

        # ✅ 2. Check if user already submitted a confession in this session
        check_resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/confessions",
            headers=SUPABASE_HEADERS,
            params={
                "username": f"eq.{confession.username}",
                "session_id": f"eq.{confession.session_id}"
            }
        )
        if check_resp.status_code == 200 and check_resp.json():
            raise HTTPException(status_code=409, detail="You’ve already submitted a confession")

        # ✅ 3. Save confession
        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/confessions",
            headers=SUPABASE_HEADERS,
            json=confession.dict()
        )

        try:
            response.raise_for_status()
            return {"message": "Confession submitted successfully"}
        except httpx.HTTPStatusError:
            return {
                "error": "Confession failed",
                "details": response.text,
                "status_code": response.status_code
            }


@app.get("/players")
async def get_players(session_id: str = None):
    async with httpx.AsyncClient() as client:
        url = f"{SUPABASE_URL}/rest/v1/players"
        params = {}
        if session_id:
            params = {
                "session_id": f"eq.{session_id}",
                "select": "username,is_ready"
            }
        else:
            params = {"select": "username,is_ready"}

        response = await client.get(url, headers=SUPABASE_HEADERS, params=params)

        if response.status_code == 200:
            return {"players": response.json()}
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to fetch players"
            )
     
        

import random

@app.get("/confessions/{session_id}")
async def get_confessions(session_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/confessions",
            headers=SUPABASE_HEADERS,
            params={"session_id": f"eq.{session_id}", "select": "confession"}
        )
        if response.status_code == 200:
            confessions = response.json()
            confession_texts = [c["confession"] for c in confessions]
            random.shuffle(confession_texts)  # 🔀 Shuffle the list
            return {"confessions": confession_texts}
        return {
            "error": "Failed to fetch confessions",
            "details": response.text,
            "status_code": response.status_code
        }



class Guess(BaseModel):
    guesser: str
    session_id: str
    confession: str
    guessed_username: str

@app.post("/guess")
async def make_guess(guess: Guess):
    async with httpx.AsyncClient() as client:
        # 🔐 Block if session not active
        session_check = await client.get(
            f"{SUPABASE_URL}/rest/v1/sessions",
            headers=SUPABASE_HEADERS,
            params={"id": f"eq.{guess.session_id}", "select": "status"}
        )

        if session_check.status_code != 200 or not session_check.json():
            raise HTTPException(status_code=404, detail="Session not found")

        if session_check.json()[0]["status"] != "active":
            raise HTTPException(status_code=403, detail="Guessing not allowed — session not active")

        # ✅ Check if guess already exists
        existing = await client.get(
            f"{SUPABASE_URL}/rest/v1/guesses",
            headers=SUPABASE_HEADERS,
            params={
                "session_id": f"eq.{guess.session_id}",
                "confession": f"eq.{guess.confession}",
                "guesser": f"eq.{guess.guesser}"
            }
        )

        if existing.status_code == 200 and existing.json():
            return {"error": "You've already guessed this confession"}

        # ✅ Get actual confession author
        confession_resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/confessions",
            headers=SUPABASE_HEADERS,
            params={
                "session_id": f"eq.{guess.session_id}",
                "confession": f"eq.{guess.confession}",
                "select": "username"
            }
        )

        if confession_resp.status_code != 200:
            return {
                "error": "Failed to fetch confession",
                "details": confession_resp.text,
                "status_code": confession_resp.status_code
            }

        data = confession_resp.json()
        if not data:
            return {"error": "Confession not found"}

        actual_username = data[0]["username"]
        is_correct = actual_username == guess.guessed_username

        # ✅ Scoring logic
        score = 2 if is_correct else 0
        # ✅ Enhanced scoring logic
    if actual_username == "AI 🤖" and guess.guessed_username == "AI 🤖":
     score = 5  # 🧠 Bonus points for catching the AI
    elif is_correct:
     score = 2
    else:
     score = 0

        # ✅ Save guess with score
     guess_data = guess.dict()
     guess_data["correct"] = is_correct
     guess_data["score"] = score
     save_resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/guesses",
            headers=SUPABASE_HEADERS,
            json=guess_data
        )
     try:
            save_resp.raise_for_status()
            return {
                "message": "Guess recorded",
                "correct": is_correct,
                "score": score
            }
     except httpx.HTTPStatusError:
            return {
                "error": "Guess save failed",
                "details": save_resp.text,
                "status_code": save_resp.status_code
            }

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with actual frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScoreInput(BaseModel):
    username: str
    score: int
    session_id: str = None  # Optional

@app.post("/submit-score")
async def submit_score(data: ScoreInput):
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{SUPABASE_URL}/rest/v1/leaderboard",
            headers=SUPABASE_HEADERS,
            json=data.dict()
        )
        if res.status_code != 201:
            raise HTTPException(status_code=400, detail="Score not saved")
    return {"message": "Score saved"}


@app.get("/leaderboard")
async def get_leaderboard(limit: int = 10):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/leaderboard",
            headers=SUPABASE_HEADERS,
            params={
                "select": "username,score",
                "order": "score.desc",
                "limit": limit
            }
        )
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch leaderboard")
    return res.json()

@app.get("/leaderboard/{session_id}")
async def get_session_leaderboard(session_id: str, limit: int = 10):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/leaderboard",
            headers=SUPABASE_HEADERS,
            params={
                "select": "username,score",
                "session_id": f"eq.{session_id}",
                "order": "score.desc",
                "limit": limit
            }
        )
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch session leaderboard")
    return res.json()


import uuid

@app.post("/create-session")
async def create_session():
    session_id = str(uuid.uuid4())
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{SUPABASE_URL}/rest/v1/sessions",
            headers=SUPABASE_HEADERS,
            json={
                "id": session_id,
                "status": "waiting",
                "current_round": 1
            }
        )
        res.raise_for_status()
        return {"session_id": session_id}

@app.post("/start-session/{session_id}")
async def start_session(session_id: str):
    async with httpx.AsyncClient() as client:
        res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/sessions?id=eq.{session_id}",
            headers=SUPABASE_HEADERS,
            json={"status": "active"}
        )
        res.raise_for_status()
        return {"message": "Session started"}

@app.post("/end-session/{session_id}")
async def end_session(session_id: str):
    async with httpx.AsyncClient() as client:
        res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/sessions?id=eq.{session_id}",
            headers=SUPABASE_HEADERS,
            json={"status": "ended"}
        )
        res.raise_for_status()
        return {"message": "Session ended"}

@app.get("/session-status/{session_id}")
async def get_status(session_id: str):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/sessions",
            headers=SUPABASE_HEADERS,
            params={
                "id": f"eq.{session_id}",
                "select": "status,current_round"
            }
        )
        res.raise_for_status()
        return res.json()[0]

@app.post("/next-round/{session_id}")
async def next_round(session_id: str):
    async with httpx.AsyncClient() as client:
        # 🔍 Fetch current round
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/sessions",
            headers=SUPABASE_HEADERS,
            params={"id": f"eq.{session_id}", "select": "current_round"}
        )
        if res.status_code != 200 or not res.json():
            raise HTTPException(status_code=404, detail="Session not found")

        current_round = res.json()[0]["current_round"]
        new_round = current_round + 1

        # 🔁 Update round
        update = await client.patch(
            f"{SUPABASE_URL}/rest/v1/sessions?id=eq.{session_id}",
            headers=SUPABASE_HEADERS,
            json={"current_round": new_round}
        )
        update.raise_for_status()

        return {"message": f"Advanced to round {new_round}"}
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

async def generate_ai_confession():
    prompt = (
        "Generate a short, funny, or embarrassing anonymous confession that sounds realistic "
        "but is entirely fictional. Keep it casual and under 25 words."
    )

    response = await openai.ChatCompletion.acreate(
        model="gpt-3.5-turbo",  # or "gpt-4" if you have access
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()

# import openai

# openai.api_key = os.getenv("OPENAI_API_KEY")

# async def generate_ai_confession():
#     prompt = "Write a short, anonymous and mysterious confession that sounds like a real person wrote it."
#     response = await openai.ChatCompletion.acreate(
#         model="gpt-4",
#         messages=[{"role": "user", "content": prompt}],
#         max_tokens=80,
#         temperature=0.9,
#     )
#     return response.choices[0].message["content"].strip()

@app.post("/inject-ai-confession/{session_id}")
async def inject_ai_confession(session_id: str):
    ai_confession = await generate_ai_confession()
    payload = {
        "username": "AI 🤖",  # special identifier
        "session_id": session_id,
        "confession": ai_confession
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{SUPABASE_URL}/rest/v1/confessions",
            headers=SUPABASE_HEADERS,
            json=payload
        )
        res.raise_for_status()
    return {"message": "AI confession added", "confession": ai_confession}


@app.post("/toggle-ready")
async def toggle_ready(username: str, session_id: str, is_ready: bool):
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/players",
            headers=SUPABASE_HEADERS,
            params={
                "username": f"eq.{username}",
                "session_id": f"eq.{session_id}"
            },
            json={"is_ready": is_ready}
        )
        if resp.status_code != 204:
            raise HTTPException(status_code=400, detail="Could not update ready status")
    return {"message": "Player readiness updated"}
