"""
gge.py — Global Geopolitical Events (GGE) Database integration
===============================================================
Loads the GGE bilateral alignment scores (Fan 2025) and enriches GDELT
analysis with historical bilateral relationship context.

Setup:
  1. Download dyad_geopolitical_scores.zip from:
     https://github.com/tianyufan-econ/global-geopolitics
  2. Unzip → dyad_geopolitical_scores.csv (~93 MB)
  3. Place CSV in your data/ folder
  4. Restart uvicorn — auto-processes on first run (~15 sec), then instant
"""

import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR  = Path("data")
GGE_CSV   = DATA_DIR / "dyad_geopolitical_scores.csv"
GGE_CACHE = DATA_DIR / ".gge_cache.json"

_GGE: dict = {}
_LOADED = False


def _dyad_key(cc1: str, cc2: str) -> str:
    a, b = sorted([cc1.upper().strip(), cc2.upper().strip()])
    return f"{a}-{b}"


def load_gge() -> bool:
    global _GGE, _LOADED
    if _LOADED:
        return True

    if GGE_CACHE.exists():
        try:
            _GGE = json.loads(GGE_CACHE.read_text())
            _LOADED = True
            logger.info(f"GGE cache loaded: {len(_GGE)} dyads")
            return True
        except Exception as e:
            logger.warning(f"GGE cache corrupt, rebuilding: {e}")

    if not GGE_CSV.exists():
        logger.warning(
            "GGE CSV not found. Download dyad_geopolitical_scores.csv from "
            "https://github.com/tianyufan-econ/global-geopolitics "
            "and place it in your data/ folder."
        )
        return False

    logger.info("Processing GGE CSV (first run, ~15 sec)...")
    try:
        df = pd.read_csv(GGE_CSV, header=0, low_memory=True)
        df = df.iloc[:, :7]
        df.columns = ["dyad", "ccode1", "ccode2", "year", "static", "n_events", "dynamic"]
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df["static"] = pd.to_numeric(df["static"], errors="coerce")
        df["dynamic"] = pd.to_numeric(df["dynamic"], errors="coerce")
        df = df[df["year"] >= 1990].dropna(subset=["static"])

        store: dict = {}
        for _, row in df.iterrows():
            key = _dyad_key(str(row["ccode1"]), str(row["ccode2"]))
            if key not in store:
                store[key] = []
            store[key].append({"year": int(row["year"]), "s": round(float(row["static"]), 4), "d": round(float(row["dynamic"]), 4)})

        for key in store:
            store[key].sort(key=lambda x: x["year"])

        GGE_CACHE.write_text(json.dumps(store, separators=(",", ":")))
        _GGE = store
        _LOADED = True
        logger.info(f"GGE processed and cached: {len(_GGE)} dyads")
        return True
    except Exception as e:
        logger.error(f"GGE load failed: {e}")
        return False


def is_available() -> bool:
    return _LOADED and bool(_GGE)


def get_dyad_history(cc1: str, cc2: str) -> list:
    if not _LOADED:
        return []
    return _GGE.get(_dyad_key(cc1, cc2), [])


def build_historical_context(cc1: str, cc2: str, c1_name: str, c2_name: str) -> dict:
    history = get_dyad_history(cc1, cc2)
    if not history:
        return {"available": False}

    by_year = sorted(history, key=lambda x: x["year"])
    recent  = sorted(history, key=lambda x: x["year"], reverse=True)[:10]
    avg10   = round(sum(r["s"] for r in recent) / len(recent), 4)
    latest  = by_year[-1]

    last3  = [r["s"] for r in recent[:3]]
    prior7 = [r["s"] for r in recent[3:10]]
    if prior7:
        d = sum(last3)/len(last3) - sum(prior7)/len(prior7)
        trend = "improving" if d > 0.05 else "deteriorating" if d < -0.05 else "stable"
    else:
        trend = "stable"

    if avg10 >= 0.3:   baseline = "strongly cooperative"
    elif avg10 >= 0.1: baseline = "moderately cooperative"
    elif avg10 >= -0.1:baseline = "broadly neutral"
    elif avg10 >= -0.3:baseline = "moderately tense"
    else:              baseline = "historically adversarial"

    earliest = by_year[0]["year"]
    latest_y = latest["year"]

    return {
        "available": True,
        "cc1": cc1.upper(), "cc2": cc2.upper(),
        "country1": c1_name, "country2": c2_name,
        "earliest_year": earliest, "latest_year": latest_y,
        "avg_10yr": avg10,
        "latest_static": round(latest["s"], 4),
        "latest_dynamic": round(latest["d"], 4),
        "trend": trend,
        "baseline_label": baseline,
        "summary": (
            f"Based on {earliest}–{latest_y} GGE data, {c1_name}–{c2_name} relations are "
            f"{baseline} (10-year avg: {avg10:+.3f}). Trend: {trend}."
        ),
        "sparkline": [
            {"year": r["year"], "score": round(r["s"], 3)}
            for r in by_year if r["year"] >= 2000
        ],
    }