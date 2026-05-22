"""FastAPI application for the red agent service."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Query
from pydantic import BaseModel

from agent import RedAgent
from caldera_client import CalderaClient, CalderaError

CALDERA_URL = os.environ.get("CALDERA_URL", "http://localhost:8888")
CALDERA_API_KEY = os.environ.get("CALDERA_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

caldera_client: CalderaClient | None = None
red_agent: RedAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise Caldera client and red agent at startup."""
    global caldera_client, red_agent
    caldera_client = CalderaClient(CALDERA_URL, CALDERA_API_KEY)
    if ANTHROPIC_API_KEY:
        os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    red_agent = RedAgent(caldera_client)
    yield


app = FastAPI(title="Red Agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    message: str


class ChatResponse(BaseModel):
    """Response body for POST /chat."""

    reply: str


def _filter_abilities_by_tactic(
    abilities: list[dict], tactic: str | None
) -> list[dict]:
    """Filter abilities by tactic name if provided."""
    if not tactic:
        return abilities
    return [
        a
        for a in abilities
        if a.get("tactic") and a["tactic"].lower() == tactic.lower()
    ]


def _abilities_to_techniques(abilities: list[dict]) -> list[dict]:
    """Aggregate abilities into unique technique summaries."""
    techniques: dict[str, dict] = {}
    for ability in abilities:
        tid = ability.get("technique_id")
        if not tid:
            continue
        if tid not in techniques:
            techniques[tid] = {
                "technique_id": tid,
                "name": ability.get("technique_name") or tid,
                "tactic": ability.get("tactic"),
                "abilities": [],
            }
        techniques[tid]["abilities"].append(ability)
    return sorted(techniques.values(), key=lambda x: x["technique_id"])


@app.get("/health")
async def health() -> dict:
    """Health check with Caldera reachability."""
    caldera_reachable = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{CALDERA_URL.rstrip('/')}/api/v2/health",
                headers={"KEY": CALDERA_API_KEY},
            )
            caldera_reachable = response.is_success
    except Exception:
        caldera_reachable = False

    return {"status": "ok", "caldera_reachable": caldera_reachable}


@app.get("/agents")
async def list_agents() -> dict:
    """List active Caldera sandcat agents."""
    try:
        agents = await asyncio.to_thread(caldera_client.get_agents)
        return {"agents": agents}
    except CalderaError:
        return {"agents": [], "error": "Caldera unreachable"}
    except Exception as exc:
        return {"agents": [], "error": str(exc)}


@app.get("/techniques")
async def list_techniques(tactic: str | None = Query(None)) -> dict:
    """List ATT&CK techniques available via Caldera abilities."""
    try:
        abilities = await asyncio.to_thread(caldera_client.get_abilities)
        filtered = _filter_abilities_by_tactic(abilities, tactic)
        return {"techniques": _abilities_to_techniques(filtered)}
    except CalderaError:
        return {"techniques": [], "error": "Caldera unreachable"}
    except Exception as exc:
        return {"techniques": [], "error": str(exc)}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message to the red agent and receive a reply."""
    try:
        reply = await red_agent.chat(request.message)
        return ChatResponse(reply=reply)
    except Exception as exc:
        return ChatResponse(reply=f"Agent error: {exc}")
