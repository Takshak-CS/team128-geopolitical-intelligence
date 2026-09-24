"""Soft Power Index adapter (Anushree's module, FastAPI over model artifacts).

Native API (read-only, ISO3-keyed):
    GET /api/latest            leaderboard: score, 95% interval, rank, stability class
    GET /api/timeseries        per-country yearly score and rank
    GET /api/drivers/{iso3}    top SHAP-attributed indicators
    GET /api/forecast/{iso3}   5-year Kalman forecast with 95% interval
    GET /api/peers/{iso3}      nearest countries in the embedding space

The module publishes uncertainty (Kalman intervals) but not a per-claim
confidence, so this adapter derives one from the published interval width and
says so in ``evidence.confidence_basis``. That is a translation of the module's
own uncertainty, not a new judgement.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .. import countries
from ..contract import insight
from ..intent import QueryPlan
from .base import AgentAdapter, AgentResult, try_call

# The composite is 0-100. A 95% interval this many points wide is treated as
# uninformative for ranking purposes.
_UNINFORMATIVE_INTERVAL = 30.0
_BASIS = "orchestrator: derived from the module's published 95% interval width"
# Model inputs that are not country indicators: the target's own rolling
# statistics and a time trend.
_META_FEATURES = {"score_roll3_mean", "score_roll3_std", "year_norm"}


def _interval_confidence(lo: Optional[float], hi: Optional[float], ceiling: float = 0.92) -> tuple[float, str]:
    if lo is None or hi is None:
        return 0.6, "no interval published for this estimate"
    width = max(0.0, float(hi) - float(lo))
    confidence = ceiling - min(0.5, width / _UNINFORMATIVE_INTERVAL * 0.5)
    return confidence, f"95% interval is {width:.1f} points wide on the 0-100 composite"


def _direction(delta: Optional[float], tolerance: float = 0.5) -> str:
    if delta is None:
        return "unknown"
    if delta > tolerance:
        return "rising"
    if delta < -tolerance:
        return "falling"
    return "flat"


class SoftPowerAdapter(AgentAdapter):
    name = "soft_power"
    label = "Soft Power"
    description = "Composite soft-power index (5 dimensions, 23 KPIs, PCA weights), Kalman-smoothed with 5-year forecasts, SHAP drivers and FAISS peers."
    time_grain = "annual (2000-2024)"

    async def capabilities(self) -> dict:
        return {
            "agent": self.name,
            "description": self.description,
            "time_grain": self.time_grain,
            "join_key": "iso3",
            "native_endpoints": ["/api/latest", "/api/timeseries", "/api/drivers/{iso3}", "/api/forecast/{iso3}", "/api/peers/{iso3}"],
        }

    async def leaderboard(self) -> list[dict]:
        rows = await self.cached_get("/api/latest", ttl_s=600)
        return rows if isinstance(rows, list) else []

    async def collect(self, plan: QueryPlan, result: AgentResult) -> tuple[list[dict], dict]:
        board = await self.leaderboard()
        by_iso3 = {str(row.get("iso3", "")).upper(): row for row in board}
        latest_year = max((row.get("year") or 0 for row in board), default=None)
        result.context["leaderboard"] = [
            {"iso3": row.get("iso3"), "rank": row.get("rank"), "score": row.get("score")} for row in board
        ]
        metadata = {
            "query_type": plan.intent,
            "year": plan.time.year if plan.time.mode == "year" else latest_year,
            "time_grain": "annual",
            "method": "PCA-weighted composite, Kalman-smoothed; SHAP drivers; FAISS peers",
            "data_quality": {"countries_scored": len(board)},
        }

        if plan.intent == "ranking" or not plan.entities:
            return self._ranking(board, plan), metadata

        targets = plan.iso3s[:2] if plan.intent == "bilateral" else plan.iso3s[:1]
        insights: list[dict] = []
        for iso3 in targets:
            insights.extend(await self._profile(iso3, by_iso3, len(board), plan))
        # The head-to-head uses the latest interval; for a past year each side's
        # own point-in-time insight above already carries the comparison.
        if plan.intent == "bilateral" and len(targets) == 2 and plan.time.mode != "year":
            insights.extend(self._compare(targets, by_iso3))
        return insights, metadata

    # ---------------------------------------------------------------- views
    def _ranking(self, board: list[dict], plan: QueryPlan) -> list[dict]:
        out = []
        for row in board[: plan.limit]:
            confidence, why = _interval_confidence(row.get("ci_lower"), row.get("ci_upper"))
            out.append(
                insight(
                    row.get("iso3"),
                    f"#{row.get('rank')} on the Soft Power Index {row.get('year')}: {row.get('name')} scores {row.get('score', 0):.1f}/100.",
                    (row.get("score") or 0) / 100.0,
                    confidence,
                    why,
                    {"rank": row.get("rank"), "score": row.get("score"), "year": row.get("year"), "confidence_basis": _BASIS},
                    facet="influence",
                )
            )
        return out

    async def _profile(self, iso3: str, by_iso3: dict, total: int, plan: QueryPlan) -> list[dict]:
        row = by_iso3.get(iso3)
        name = countries.name_of(iso3)
        if not row:
            return [
                insight(iso3, f"{name} is not covered by the Soft Power Index.", 0.0, 0.9, "country absent from the model's scored panel", {"covered": False}, facet="influence")
            ]

        want_forecast = plan.intent in ("country_profile", "forecast")
        want_peers = plan.intent in ("country_profile", "blocs")
        y_end = plan.time.year if plan.time.mode == "year" else (row.get("year") or 2024)
        calls = [
            try_call(self.get("/api/timeseries", params={"iso3": iso3, "yStart": max(2000, y_end - 10), "yEnd": y_end}), {}),
            try_call(self.get(f"/api/drivers/{iso3}"), []) if plan.intent == "country_profile" else _none(),
            try_call(self.get(f"/api/forecast/{iso3}"), []) if want_forecast else _none(),
            try_call(self.get(f"/api/peers/{iso3}", params={"limit": 5}), []) if want_peers else _none(),
        ]
        series_map, drivers, forecast, peers = await asyncio.gather(*calls)
        series = [p for p in (series_map or {}).get(iso3, []) if p.get("score") is not None]

        out: list[dict] = []
        # 1. Level and rank, at the requested year when there is one.
        if plan.time.mode == "year":
            point = next((p for p in series if p.get("year") == plan.time.year), None)
            if point:
                out.append(
                    insight(
                        iso3,
                        f"In {point['year']}, {name} ranked #{point.get('rank')} on the Soft Power Index with a score of {point['score']:.1f}/100.",
                        point["score"] / 100.0,
                        0.75,
                        "historical Kalman-smoothed score; no interval is published for past years",
                        {"year": point["year"], "rank": point.get("rank"), "score": point["score"], "confidence_basis": "orchestrator: fixed for historical points"},
                        facet="influence",
                    )
                )
        else:
            confidence, why = _interval_confidence(row.get("ci_lower"), row.get("ci_upper"))
            out.append(
                insight(
                    iso3,
                    f"{name} ranks #{row.get('rank')} of {total} on the Soft Power Index {row.get('year')} with a score of "
                    f"{row.get('score', 0):.1f}/100 (95% interval {row.get('ci_lower', 0):.1f}-{row.get('ci_upper', 0):.1f}).",
                    (row.get("score") or 0) / 100.0,
                    confidence,
                    why,
                    {
                        "year": row.get("year"),
                        "rank": row.get("rank"),
                        "of": total,
                        "score": row.get("score"),
                        "ci_lower": row.get("ci_lower"),
                        "ci_upper": row.get("ci_upper"),
                        "stability_class": row.get("stability_class"),
                        "volatility_tier": row.get("volatility_tier"),
                        "confidence_basis": _BASIS,
                    },
                    facet="influence",
                )
            )

        # 2. Trajectory over the last decade of the series.
        if len(series) >= 3:
            first, last = series[0], series[-1]
            delta = last["score"] - first["score"]
            direction = _direction(delta)
            rank_move = ""
            if first.get("rank") and last.get("rank"):
                rank_move = f", rank {first['rank']} -> {last['rank']}"
            out.append(
                insight(
                    iso3,
                    f"{name}'s soft power is {direction}: {first['score']:.1f} in {first['year']} to {last['score']:.1f} in {last['year']} ({delta:+.1f} points{rank_move}).",
                    delta / 100.0,
                    0.8 if abs(delta) > 2 else 0.65,
                    f"{len(series)} annual Kalman-smoothed observations; small moves sit inside year-to-year noise" if abs(delta) <= 2 else f"{len(series)} annual Kalman-smoothed observations",
                    {"direction": direction, "delta": round(delta, 2), "from_year": first["year"], "to_year": last["year"], "momentum_5y": row.get("momentum_5y"), "trend_slope": row.get("trend_slope")},
                    facet="influence_trend",
                )
            )

        # 3. Forecast.
        if forecast:
            horizon = forecast[-1]
            confidence, why = _interval_confidence(horizon.get("lo"), horizon.get("hi"), ceiling=0.85)
            current = row.get("score") or 0
            change = (horizon.get("score") or 0) - current
            out.append(
                insight(
                    iso3,
                    f"Kalman forecast puts {name} at {horizon.get('score', 0):.1f} by {horizon.get('year')} "
                    f"(95% interval {horizon.get('lo', 0):.1f}-{horizon.get('hi', 0):.1f}), {change:+.1f} from today.",
                    change / 100.0,
                    confidence,
                    why,
                    {"direction": _direction(change), "forecast": forecast, "confidence_basis": _BASIS},
                    facet="influence_outlook",
                )
            )

        # 4. Drivers. The model's inputs include the score's own rolling mean and
        # a time trend; those dominate SHAP but are not indicators a reader can
        # act on, so they are reported as a share rather than listed as drivers.
        if drivers:
            indicators = [d for d in drivers if d.get("raw") not in _META_FEATURES]
            meta = [d for d in drivers if d.get("raw") in _META_FEATURES]
            total = sum(abs(d.get("shap") or 0) for d in drivers) or 1.0
            meta_share = sum(abs(d.get("shap") or 0) for d in meta) / total
            if indicators:
                top = indicators[:3]
                parts = [f"{d['feature']} ({'+' if d.get('direction') == 'up' else '-'})" for d in top]
                claim = f"Largest indicator drivers of {name}'s score: {', '.join(parts)}."
                if meta_share >= 0.25:
                    claim += f" The model's own lagged-score and time terms carry {meta_share:.0%} of the attribution shown."
                out.append(
                    insight(
                        iso3,
                        claim,
                        abs(top[0].get("shap") or 0),
                        0.6 if meta_share < 0.5 else 0.45,
                        "SHAP values explain the ensemble model's prediction, not causation"
                        + ("; most of the prediction comes from the score's own recent history" if meta_share >= 0.5 else ""),
                        {"drivers": top, "meta_feature_share": round(meta_share, 3), "meta_features": [d.get("raw") for d in meta]},
                        facet="influence_drivers",
                    )
                )

        # 5. Peers.
        if peers:
            named = [f"{countries.name_of(p['iso3'])} ({p['similarity']:.2f})" for p in peers[:4]]
            out.append(
                insight(
                    iso3,
                    f"Closest soft-power profiles to {name}: {', '.join(named)}.",
                    peers[0].get("similarity") or 0,
                    0.7,
                    "cosine similarity in the standardised indicator embedding",
                    {"peers": [{"iso3": p["iso3"], "similarity": p["similarity"], "rank": p.get("rank")} for p in peers[:5]]},
                    facet="influence_peers",
                )
            )
        return out

    def _compare(self, pair: list[str], by_iso3: dict) -> list[dict]:
        a, b = (by_iso3.get(code) for code in pair)
        if not a or not b:
            return []
        gap = (a.get("score") or 0) - (b.get("score") or 0)
        leader, trailer = (pair[0], pair[1]) if gap >= 0 else (pair[1], pair[0])
        overlap = not (a.get("ci_upper", 0) < b.get("ci_lower", 0) or b.get("ci_upper", 0) < a.get("ci_lower", 0))
        return [
            insight(
                leader,
                f"{countries.name_of(leader)} out-ranks {countries.name_of(trailer)} on soft power by {abs(gap):.1f} points"
                + (" - but their 95% intervals overlap, so the ordering is not decisive." if overlap else "."),
                abs(gap) / 100.0,
                0.55 if overlap else 0.85,
                "intervals overlap" if overlap else "intervals do not overlap",
                {"pair": pair, "gap": round(gap, 2), "intervals_overlap": overlap},
                facet="bilateral_influence",
            )
        ]


async def _none():
    return None
