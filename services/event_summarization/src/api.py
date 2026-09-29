"""
api.py — FastAPI backend for GDELT Video Intelligence
=======================================================
Wraps the existing preprocess.py pipeline behind a JSON API, and adds the
Phase 3 layer: Gemini script polish -> gTTS voice -> ffmpeg video brief.

Run from the project root (same place you run `streamlit run app.py`):
    uvicorn src.api:app --reload --port 8000

Interactive docs (also a quick way to test without a frontend yet):
    http://localhost:8000/docs

Phase 3 (/briefing) additionally needs:
    pip install google-genai gTTS Pillow python-dotenv
  - ffmpeg installed and on PATH
  - GEMINI_API_KEY set (free, no credit card — see src/narration.py)
  See src/narration.py for details.
"""

import json
import math
import asyncio
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.preprocess import (
    preprocess, get_top5_events, summarize, fetch_gdelt_file,
    get_cached_dates, warmup_models,
    NER_AVAILABLE, SENTIMENT_AVAILABLE, CLUSTER_AVAILABLE,
)
from src.utils import get_country_display_list, get_country_name
from src.narration import generate_briefing, MEDIA_DIR
from src.enricher import enrich_event
from src.gge import load_gge, build_historical_context, is_available as gge_available


# ---------------------------------------------------------------------------
# Warm up ML models on startup so the FIRST real request isn't the slow one
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup_models()
    load_gge()   # pre-processes GGE CSV on first run
    yield


app = FastAPI(title="GDELT Video Intelligence API", lifespan=lifespan)

# Dev-friendly CORS so a local React dev server (Vite, CRA, etc.) can call
# this freely. Tighten allow_origins before deploying anywhere public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves generated briefing audio/video at /media/<file> — e.g. a video at
# media/briefings/20260327_USA.mp4 becomes http://localhost:8000/media/20260327_USA.mp4
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


# ---------------------------------------------------------------------------
# Tiny in-memory result cache — last N (date, country) analyses.
# Streamlit's problem was recomputing the full ML pipeline on every click;
# a long-lived FastAPI process lets us just remember the answer instead.
# ---------------------------------------------------------------------------
_RESULT_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_MAX = 20


def _cache_get(key):
    if key in _RESULT_CACHE:
        _RESULT_CACHE.move_to_end(key)
        return _RESULT_CACHE[key]
    return None


def _cache_set(key, value):
    _RESULT_CACHE[key] = value
    _RESULT_CACHE.move_to_end(key)
    while len(_RESULT_CACHE) > _CACHE_MAX:
        _RESULT_CACHE.popitem(last=False)


# ---------------------------------------------------------------------------
# JSON-safety — numpy scalars and NaN don't serialize cleanly on their own.
# This walks any nested dict/list payload and converts leaves to plain
# Python types, so we don't have to hand-convert every field by hand.
# ---------------------------------------------------------------------------
def _clean_scalar(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):       # numpy scalar -> python scalar
        return value.item()
    return value


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return _clean_scalar(obj)


def _compute_partners(df: pd.DataFrame, cc: str, limit: int = 8) -> list:
    """
    Aggregates which other countries this country's events involved, by
    event count and average Goldstein score — feeds the world map's arcs.
    """
    is_initiator = df["CountryRole"] == "Initiator"
    is_recipient = df["CountryRole"] == "Recipient"
    is_both = df["CountryRole"] == "Both"

    partner_code = pd.Series(pd.NA, index=df.index, dtype="object")
    partner_code[is_initiator] = df.loc[is_initiator, "Actor2CountryCode"]
    partner_code[is_recipient] = df.loc[is_recipient, "Actor1CountryCode"]
    partner_code[is_both] = df.loc[is_both, "Actor2CountryCode"]

    work = pd.DataFrame({"partner": partner_code, "goldstein": df["GoldsteinScale"]})
    work = work.dropna(subset=["partner"])
    work = work[work["partner"].str.match(r"^[A-Z]{3}$", na=False)]
    # preprocess() upper-cases missing codes to the string "NAN"; those are
    # events with no coded counterpart, not a country called NAN.
    work = work[~work["partner"].isin(["NAN", "NONE"])]
    work = work[work["partner"] != cc.upper()]

    if work.empty:
        return []

    agg = (
        work.groupby("partner")["goldstein"]
        .agg(["count", "mean"])
        .reset_index()
        .sort_values("count", ascending=False)
        .head(limit)
    )

    return [
        {
            "code": row["partner"],
            "name": get_country_name(row["partner"]),
            "count": int(row["count"]),
            "avg_goldstein": float(row["mean"]),
        }
        for _, row in agg.iterrows()
    ]


# ---------------------------------------------------------------------------
# Shared analysis builder — used by both /analyze and /briefing so the
# pipeline only ever runs once per (date, country), regardless of which
# endpoint asks for it first.
# ---------------------------------------------------------------------------
def _build_or_get_analysis(date: str, country_code: str, limit: int = 300) -> dict:
    cache_key = (date, country_code.upper())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    df = preprocess(date, country_code)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No events found for {country_code} on {date}.",
        )

    country_name = get_country_name(country_code)
    top5 = get_top5_events(df, country_name)
    summary_text = summarize(df, country_name, date, top5)
    partners = _compute_partners(df, country_code, limit=8)

    table_cols = [
        "SQLDATE", "Actor1Name", "Actor1CountryCode", "Actor2Name",
        "Actor2CountryCode", "EventType", "GoldsteinScale", "Tone", "CountryRole",
        "SOURCEURL", "NumArticles",
    ]
    if SENTIMENT_AVAILABLE and "SentimentLabel" in df.columns:
        table_cols += ["SentimentLabel", "SentimentScore", "SentimentAgreement"]
    if CLUSTER_AVAILABLE and "EventCluster" in df.columns:
        table_cols += ["EventCluster"]

    table_records = df[table_cols].head(limit).to_dict(orient="records")

    # Domestic vs international split (mirrors the WebSocket pipeline's
    # payload shape) — both actors from the analyzed country = domestic.
    is_domestic = (
        (df["Actor1CountryCode"].fillna("") == df["Actor2CountryCode"].fillna("")) &
        (df["Actor1CountryCode"].fillna("") != "") &
        (df["Actor1CountryCode"].fillna("") == country_code.upper())
    )
    df_intl = df[~is_domestic]
    df_dom  = df[is_domestic]

    payload = {
        "country_code": country_code.upper(),
        "country_name": country_name,
        "date": date,
        "metrics": {
            "total_events": len(df),
            "avg_goldstein": df["GoldsteinScale"].mean(),
            "initiator_pct": round((df["CountryRole"] == "Initiator").sum() / len(df) * 100),
            "ambiguous_count": int((df.get("SentimentAgreement", pd.Series(dtype=str)) == "⚠ Ambiguous").sum()),
        },
        "event_type_counts": df["EventType"].value_counts().to_dict(),
        "tone_counts": df["Tone"].value_counts().to_dict(),
        "sentiment_counts": (
            df["SentimentLabel"].value_counts().to_dict()
            if SENTIMENT_AVAILABLE and "SentimentLabel" in df.columns else {}
        ),
        "cluster_counts": (
            df["EventCluster"].value_counts().to_dict()
            if CLUSTER_AVAILABLE and "EventCluster" in df.columns else {}
        ),
        "cluster_quality": df.attrs.get("cluster_quality") if CLUSTER_AVAILABLE else None,
        "partners": partners,
        "top5_events": top5,
        "table": table_records,
        "table_rows_shown": len(table_records),
        "table_rows_total": len(df),
        "narration_script": summary_text,
        "domestic": {
            "total": len(df_dom),
            "avg_goldstein": round(float(df_dom["GoldsteinScale"].mean()), 4) if not df_dom.empty else 0.0,
            "event_type_counts": df_dom["EventType"].value_counts().to_dict() if not df_dom.empty else {},
        },
        "international": {
            "total": len(df_intl),
            "avg_goldstein": round(float(df_intl["GoldsteinScale"].mean()), 4) if not df_intl.empty else 0.0,
            "event_type_counts": df_intl["EventType"].value_counts().to_dict() if not df_intl.empty else {},
        },
    }

    payload = _jsonable(payload)
    _cache_set(cache_key, payload)
    return payload


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    date: str
    country_code: str
    limit: Optional[int] = 300   # cap on rows returned in "table"


class BriefingRequest(BaseModel):
    date: str
    country_code: str
    force: bool = False          # bypass the on-disk media cache and re-render


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "ml_layers": {
            "ner": NER_AVAILABLE,
            "sentiment": SENTIMENT_AVAILABLE,
            "clustering": CLUSTER_AVAILABLE,
        },
        "gge_database": gge_available(),
        # Model chosen by the enricher so far (null until first AI call).
        "gemini_model": _gemini_model_name(),
    }


def _gemini_model_name():
    try:
        from src.enricher import get_cached_model_name
        return get_cached_model_name()
    except Exception:
        return None


@app.get("/dates")
def cached_dates():
    return {"dates": get_cached_dates()}


@app.get("/countries")
def countries(date: str = Query(..., min_length=8, max_length=8)):
    try:
        fetch_gdelt_file(date)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    codes = get_country_display_list(date)
    return {
        "countries": [
            {"code": c.split(" ")[0], "name": get_country_name(c.split(" ")[0])}
            for c in codes
        ]
    }


@app.get("/raw-preview")
def raw_preview(date: str = Query(..., min_length=8, max_length=8), n: int = 5):
    try:
        path = fetch_gdelt_file(date)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    raw = pd.read_csv(path, sep="\t", header=None, low_memory=False, nrows=n)
    return {"rows": raw.astype(str).values.tolist()}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        return _build_or_get_analysis(req.date, req.country_code, req.limit or 300)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")


@app.post("/briefing")
def briefing(req: BriefingRequest):
    """
    Phase 3: takes the same analysis /analyze would return, then runs it
    through Gemini (script polish), gTTS (voice), and ffmpeg (video).
    """
    try:
        analysis = _build_or_get_analysis(req.date, req.country_code)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")

    try:
        result = generate_briefing(
            raw_summary=analysis["narration_script"],
            country_name=analysis["country_name"],
            date=req.date,
            country_code=req.country_code,
            total_events=analysis["metrics"]["total_events"],
            avg_goldstein=analysis["metrics"]["avg_goldstein"],
            force=req.force,
        )
    except RuntimeError as e:
        # Missing API key / ffmpeg / package — a setup problem, not a bug.
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Briefing generation failed: {e}")

    return {
        "polished_script": result["polished_script"],
        "audio_url": f"/media/{result['audio_file']}",
        "video_url": f"/media/{result['video_file']}",
        "cached": result["cached"],
    }


# ---------------------------------------------------------------------------
# WebSocket — streaming pipeline with live stage-by-stage progress
# ---------------------------------------------------------------------------

async def _send(ws: WebSocket, stage: str, status: str, message: str, pct: int, payload=None):
    """Send a pipeline stage update over the WebSocket."""
    await ws.send_text(json.dumps({
        "stage": stage,
        "status": status,   # "running" | "done" | "error"
        "message": message,
        "pct": pct,
        "payload": payload,
    }))



class EnrichRequest(BaseModel):
    url: str
    actor1: str
    actor2: str
    event_type: str
    country: str
    score: float


# Successful /enrich-event results, so re-opening the same event card
# doesn't spend Gemini quota again. Failures are never cached.
_ENRICH_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_ENRICH_CACHE_MAX = 500
_ENRICH_CACHE_LOCK = threading.Lock()


@app.post("/enrich-event")
def enrich_event_route(req: EnrichRequest):
    """
    On-demand article enrichment for vague GDELT actor names.
    Fetches the source article, extracts text, and asks Gemini
    to identify the real actors and summarise what happened.
    Only called when the user explicitly requests it (per-event button).
    """
    cache_key = (req.url, req.actor1, req.actor2, req.event_type)
    with _ENRICH_CACHE_LOCK:
        if cache_key in _ENRICH_CACHE:
            _ENRICH_CACHE.move_to_end(cache_key)
            return _ENRICH_CACHE[cache_key]
    try:
        result = enrich_event(
            url=req.url,
            actor1=req.actor1,
            actor2=req.actor2,
            event_type=req.event_type,
            country=req.country,
            score=req.score,
        )
        if isinstance(result, dict) and result.get("enriched"):
            with _ENRICH_CACHE_LOCK:
                _ENRICH_CACHE[cache_key] = result
                _ENRICH_CACHE.move_to_end(cache_key)
                while len(_ENRICH_CACHE) > _ENRICH_CACHE_MAX:
                    _ENRICH_CACHE.popitem(last=False)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/article-headline")
def article_headline(url: str = Query(...)):
    """
    Fetches just the headline from a news article URL.
    Fast path — no AI call, just BeautifulSoup extraction.
    Used by the frontend to show the real article headline
    instead of a GDELT-generated template sentence.
    """
    from src.enricher import _fetch_article
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    result = _fetch_article(url, timeout=6)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return {
        "headline": result.get("headline", ""),
        "domain": result.get("domain", ""),
    }


@app.get("/article-context")
def article_context(
    url: str = Query(...),
    term: str = Query(..., min_length=1, max_length=200),
):
    """
    Returns the sentence(s) of the source article that mention `term`
    (plus one sentence of context either side). No AI call — full-text
    fetch + regex. See src/article_context.py.
    """
    from src.article_context import find_mentions
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")
    return find_mentions(url, term)


@app.get("/article-relevance")
def article_relevance(
    url: str = Query(...),
    term1: str = Query("", max_length=200),
    term2: str = Query("", max_length=200),
    headline: Optional[str] = Query(None, max_length=1000),
):
    """
    Judges from the full article text how well the source article supports
    the event's two actors (prominence of each, co-occurrence, places and
    main people/orgs named, a best_snippet sentence, and a link of
    together/listed/one_sided/none/unavailable with a one-line verdict_text).
    No AI call — see analyze_relevance in src/article_context.py, which
    also rejects loopback/private hosts.
    """
    from src.article_context import analyze_relevance
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")
    return analyze_relevance(url, term1, term2, headline)



@app.get("/historical-context")
def historical_context(
    cc1: str = Query(..., min_length=2, max_length=3),
    cc2: str = Query(..., min_length=2, max_length=3),
):
    """
    Returns the GGE bilateral alignment history for a country pair.
    Provides 1990-2024 annual scores, 10-year average, trend, and a
    plain-English summary of the historical relationship.
    Used by the partner panel to add historical context to GDELT events.
    """
    if not gge_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "GGE database not loaded. Download dyad_geopolitical_scores.csv "
                "from https://github.com/tianyufan-econ/global-geopolitics "
                "and place it in your data/ folder, then restart the server."
            )
        )
    from src.utils import get_country_name
    c1 = get_country_name(cc1)
    c2 = get_country_name(cc2)
    ctx = build_historical_context(cc1, cc2, c1, c2)
    if not ctx["available"]:
        raise HTTPException(
            status_code=404,
            detail=f"No GGE data found for pair {cc1.upper()}-{cc2.upper()}."
        )
    return ctx


@app.websocket("/ws/pipeline")
async def pipeline_ws(websocket: WebSocket):
    """
    Streams the full analysis pipeline stage-by-stage so the frontend can
    animate each step as it completes, instead of showing a frozen spinner.

    Message format:
      { stage, status, message, pct, payload }

    Stages (in order):
      fetch → filter → ner → sentiment → cluster → summarize → done

    On completion, 'payload' on the 'done' stage contains the full
    analysis result identical to what /analyze returns.
    """
    await websocket.accept()
    try:
        raw = await websocket.receive_text()
        req = json.loads(raw)
        date = req.get("date", "")
        country_code = req.get("country_code", "").upper()

        if not date or not country_code:
            await _send(websocket, "error", "error", "date and country_code are required", 0)
            return

        # Check cache first — if we already have this result, stream
        # through the stages quickly so the animation still plays but
        # doesn't make the user wait.
        cache_key = (date, country_code)
        cached = _cache_get(cache_key)
        if cached:
            stages = [
                ("fetch",     "Fetching GDELT data",           10),
                ("filter",    "Filtering & deduplicating",     25),
                ("ner",       "Running NER entity extraction", 45),
                ("sentiment", "Running DistilBERT sentiment",  60),
                ("cluster",   "KMeans clustering",             75),
                ("summarize", "Building narration script",     90),
            ]
            for stage, msg, pct in stages:
                await _send(websocket, stage, "done", msg, pct)
                await asyncio.sleep(0.12)
            await _send(websocket, "done", "done", "Complete (cached)", 100, payload=cached)
            return

        # ── Stage 1: Fetch ────────────────────────────────────────────
        await _send(websocket, "fetch", "running", "Downloading GDELT daily export…", 5)
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, fetch_gdelt_file, date)
        except FileNotFoundError as e:
            await _send(websocket, "fetch", "error", str(e), 5)
            return
        await _send(websocket, "fetch", "done", "GDELT file ready", 12)

        # ── Stage 2: Filter & clean ───────────────────────────────────
        await _send(websocket, "filter", "running", f"Filtering events for {country_code}…", 15)
        try:
            df = await loop.run_in_executor(None, preprocess, date, country_code)
        except Exception as e:
            await _send(websocket, "filter", "error", f"Pipeline error: {e}", 15)
            return

        if df.empty:
            await _send(websocket, "filter", "error",
                        f"No events found for {country_code} on {date}.", 15)
            return

        total = len(df)
        await _send(websocket, "filter", "done",
                    f"{total:,} events matched after deduplication", 30)

        # ── Stage 3: NER ──────────────────────────────────────────────
        await _send(websocket, "ner", "running" if NER_AVAILABLE else "done",
                    "spaCy NER enrichment applied" if NER_AVAILABLE
                    else "NER skipped (spaCy not installed)", 40)
        await asyncio.sleep(0.05)
        await _send(websocket, "ner", "done",
                    "Actor names extracted and cleaned", 50)

        # ── Stage 4: Sentiment ────────────────────────────────────────
        await _send(websocket, "sentiment", "running" if SENTIMENT_AVAILABLE else "done",
                    "DistilBERT cross-validating Goldstein scores…" if SENTIMENT_AVAILABLE
                    else "Sentiment skipped (transformers not installed)", 55)
        await asyncio.sleep(0.05)
        await _send(websocket, "sentiment", "done",
                    "Sentiment analysis complete" if SENTIMENT_AVAILABLE
                    else "Sentiment layer inactive", 62)

        # ── Stage 5: Cluster ──────────────────────────────────────────
        await _send(websocket, "cluster", "running" if CLUSTER_AVAILABLE else "done",
                    "KMeans grouping events into themes…" if CLUSTER_AVAILABLE
                    else "Clustering skipped (scikit-learn not installed)", 65)
        await asyncio.sleep(0.05)
        await _send(websocket, "cluster", "done",
                    "Events clustered into activity themes", 75)

        # ── Stage 6: Summarize ────────────────────────────────────────
        await _send(websocket, "summarize", "running",
                    "Building narration script…", 80)
        country_name = get_country_name(country_code)
        top5 = get_top5_events(df, country_name)
        summary_text = summarize(df, country_name, date, top5)
        await _send(websocket, "summarize", "done",
                    "Narration script ready", 90)

        # ── Build full payload (same shape as /analyze) ───────────────
        from src.api import _compute_partners
        partners = _compute_partners(df, country_code, limit=8)

        table_cols = [
            "SQLDATE", "Actor1Name", "Actor1CountryCode", "Actor2Name",
            "Actor2CountryCode", "EventType", "GoldsteinScale", "Tone", "CountryRole",
            "SOURCEURL", "NumArticles",
        ]
        if SENTIMENT_AVAILABLE and "SentimentLabel" in df.columns:
            table_cols += ["SentimentLabel", "SentimentScore", "SentimentAgreement"]
        if CLUSTER_AVAILABLE and "EventCluster" in df.columns:
            table_cols += ["EventCluster"]

        # ── Domestic vs International split ──────────────────────────────
        # Domestic: both actors from the same country (internal events)
        # International: cross-border events
        is_domestic = (
            (df["Actor1CountryCode"].fillna("") == df["Actor2CountryCode"].fillna("")) &
            (df["Actor1CountryCode"].fillna("") != "") &
            (df["Actor1CountryCode"].fillna("") == country_code.upper())
        )
        df_intl = df[~is_domestic]
        df_dom  = df[is_domestic]

        dom_type_counts  = df_dom["EventType"].value_counts().to_dict()  if not df_dom.empty  else {}
        intl_type_counts = df_intl["EventType"].value_counts().to_dict() if not df_intl.empty else {}
        dom_avg_gs  = float(df_dom["GoldsteinScale"].mean())  if not df_dom.empty  else 0.0
        intl_avg_gs = float(df_intl["GoldsteinScale"].mean()) if not df_intl.empty else 0.0

        payload = {
            "country_code": country_code,
            "country_name": country_name,
            "date": date,
            "metrics": {
                "total_events": total,
                "avg_goldstein": df["GoldsteinScale"].mean(),
                "initiator_pct": round(
                    (df["CountryRole"] == "Initiator").sum() / total * 100),
                "ambiguous_count": int(
                    (df.get("SentimentAgreement", pd.Series(dtype=str)) == "⚠ Ambiguous").sum()),
            },
            "event_type_counts": df["EventType"].value_counts().to_dict(),
            "tone_counts": df["Tone"].value_counts().to_dict(),
            "sentiment_counts": (
                df["SentimentLabel"].value_counts().to_dict()
                if SENTIMENT_AVAILABLE and "SentimentLabel" in df.columns else {}
            ),
            "cluster_counts": (
                df["EventCluster"].value_counts().to_dict()
                if CLUSTER_AVAILABLE and "EventCluster" in df.columns else {}
            ),
            "cluster_quality": df.attrs.get("cluster_quality") if CLUSTER_AVAILABLE else None,
            "partners": partners,
            "top5_events": top5,
            "table": df[table_cols].head(300).to_dict(orient="records"),
            "table_rows_shown": min(300, total),
            "table_rows_total": total,
            "narration_script": summary_text,
        "domestic": {
            "total": len(df_dom),
            "avg_goldstein": round(dom_avg_gs, 4),
            "event_type_counts": dom_type_counts,
        },
        "international": {
            "total": len(df_intl),
            "avg_goldstein": round(intl_avg_gs, 4),
            "event_type_counts": intl_type_counts,
        },
        }

        payload = _jsonable(payload)
        _cache_set(cache_key, payload)

        await _send(websocket, "done", "done", f"Pipeline complete — {total:,} events", 100,
                    payload=payload)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await _send(websocket, "error", "error", str(e), 0)
        except Exception:
            pass