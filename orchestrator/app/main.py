"""Orchestrator API: one question in, one fused briefing out.

    POST /ask            question -> plan -> parallel fan-out -> fusion -> briefing
    POST /run            the same run streamed as NDJSON events (plan, each agent, fusion)
    POST /parse          question -> plan only (what /ask would do, without calling agents)
    GET  /agents         live health of all four agents
    GET  /capabilities   what the orchestrator and each agent can answer
    GET  /health         orchestrator liveness plus a one-word status per agent
    POST /reviews        a visitor's rating, review and suggestions (stored; see reviews.py)
    GET  /reviews/summary  how many reviews and their average rating
    GET  /reviews/public   reviews longer than 100 words: rating, text, name, date (no emails)
    GET  /               home: the two ways in
    GET  /features       the four module dashboards
    GET  /engine         the GEOINT Engine run console
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import intent, reviews
from .config import CORS_ORIGINS
from .pipeline import ADAPTERS, Orchestrator

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
IntentName = Literal["country_profile", "bilateral", "shock", "forecast", "blocs", "events", "ranking", "event_history"]
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
    # The trade agent's sectors (services/trade_intelligence/core/sector_mapper.py).
    sector: Optional[Literal[
        "all", "energy", "agriculture", "electronics", "minerals", "chemicals", "pharmaceuticals",
        "plastics", "metals", "precious_metals", "textiles", "wood_paper", "vehicles", "arms", "manufactures",
    ]] = None
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


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: Literal["features", "engine"]
    rating: int = Field(ge=1, le=5)
    review: str = Field(default="", max_length=4000)
    suggestions: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=80)
    email: str = Field(min_length=3, max_length=254, pattern=reviews.EMAIL_PATTERN)


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


@app.post("/run")
async def run(request: AskRequest) -> StreamingResponse:
    """One JSON object per line, as each step finishes: {"type": "plan"}, then one
    {"type": "agent"} per agent in the order they answer, then {"type": "fusion"}.
    A failure ends the stream with {"type": "error", "detail": ...}."""
    overrides = request.model_dump(exclude={"question", "include_envelopes"}, exclude_none=True)

    async def lines():
        try:
            async for event in _orchestrator().run_stream(request.question, overrides):
                yield json.dumps(jsonable_encoder(event), ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001
            yield json.dumps({"type": "error", "detail": f"Orchestration failed: {type(exc).__name__}: {exc}"}) + "\n"

    # no-transform keeps Caddy's gzip from holding lines back; X-Accel-Buffering
    # does the same for nginx-style proxies.
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post("/parse")
async def parse(request: ParseRequest) -> dict:
    plan = intent.parse(request.question)
    alignment = await _orchestrator().align_time(plan)
    return {"plan": plan.to_dict(), "time_alignment": alignment}


@app.post("/reviews")
async def post_review(body: ReviewRequest, request: Request) -> dict:
    # Behind Caddy the visitor is the first X-Forwarded-For address.
    visitor = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")).split(",")[0].strip()
    if not reviews.allow(visitor):
        raise HTTPException(status_code=429, detail="Thanks, but that is enough reviews from you for now. Try again in an hour.")
    saved = reviews.add(body.page, body.rating, body.review, body.suggestions, body.name, body.email)
    return {"saved": True, **saved}


@app.get("/reviews/summary")
async def review_summary() -> dict:
    return reviews.summary()


@app.get("/reviews/public")
async def review_public() -> dict:
    return {"min_words": reviews.PUBLIC_MIN_WORDS, "reviews": reviews.public()}


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

    def _page(name: str) -> FileResponse:
        # Revalidate on every load (a 304 when unchanged), so a deploy shows up
        # at once instead of after the browser's heuristic cache expires.
        return FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return _page("home.html")

    @app.get("/features", include_in_schema=False)
    async def features() -> FileResponse:
        return _page("features.html")

    @app.get("/engine", include_in_schema=False)
    async def engine() -> FileResponse:
        return _page("index.html")
