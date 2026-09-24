"""Orchestrator API: one question in, one fused briefing out.

    POST /ask            question -> plan -> parallel fan-out -> fusion -> briefing
    POST /parse          question -> plan only (what /ask would do, without calling agents)
    GET  /agents         live health of all four agents
    GET  /capabilities   what the orchestrator and each agent can answer
    GET  /health         orchestrator liveness plus a one-word status per agent
    GET  /               unified briefing UI
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import intent
from .config import CORS_ORIGINS
from .pipeline import ADAPTERS, Orchestrator

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
IntentName = Literal["country_profile", "bilateral", "shock", "forecast", "blocs", "events", "ranking"]
AgentName = Literal["soft_power", "policy_stance", "trade_intelligence", "event_summarization"]
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.orchestrator = Orchestrator()
    yield
    await app.state.orchestrator.close()


app = FastAPI(
    title="Team 128 Orchestrator",
    description="Decomposes a geopolitical question, fans it out to the Soft Power, Policy Stance, Trade and Events agents, and fuses their answers.",
    version=VERSION,
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class AskRequest(BaseModel):
    # Same rule as the Trade agent: a misspelled field is a 422, not a silently
    # ignored parameter that changes the answer.
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=500)
    agents: Optional[list[AgentName]] = None
    countries: Optional[list[str]] = Field(default=None, max_length=4)
    intent: Optional[IntentName] = None
    year: Optional[int] = Field(default=None, ge=1989, le=2030)
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD or YYYYMMDD, for the Events agent")
    sector: Optional[Literal["all", "energy", "agriculture", "electronics"]] = None
    severity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    include_envelopes: bool = True

    @field_validator("date")
    @classmethod
    def _date(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        compact = value.replace("-", "")
        if not re.fullmatch(r"20\d{6}", compact):
            raise ValueError("date must be YYYY-MM-DD or YYYYMMDD")
        return compact


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=500)


def _orchestrator() -> Orchestrator:
    return app.state.orchestrator


@app.post("/ask")
async def ask(request: AskRequest) -> dict:
    overrides = request.model_dump(exclude={"question", "include_envelopes"}, exclude_none=True)
    try:
        return await _orchestrator().ask(request.question, overrides, include_envelopes=request.include_envelopes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Orchestration failed: {type(exc).__name__}: {exc}") from exc


@app.post("/parse")
async def parse(request: ParseRequest) -> dict:
    plan = intent.parse(request.question)
    alignment = await _orchestrator().align_time(plan)
    return {"plan": plan.to_dict(), "time_alignment": alignment}


@app.get("/agents")
async def agents() -> dict:
    return await _orchestrator().agents_health()


@app.get("/capabilities")
async def capabilities() -> dict:
    return await _orchestrator().capabilities()


@app.get("/health")
async def health() -> dict:
    statuses = await _orchestrator().agents_health()
    summary = {name: info.get("status") for name, info in statuses.items()}
    up = sum(1 for status in summary.values() if status == "ok")
    return {"status": "ok", "version": VERSION, "agents_up": up, "agents_total": len(ADAPTERS), "agents": summary}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
