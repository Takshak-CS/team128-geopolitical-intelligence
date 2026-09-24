"""Event Summarization adapter (Shreyas's module, FastAPI over GDELT V1 + GGE).

Native API:
    POST /analyze                {date: YYYYMMDD, country_code: CAMEO} -> metrics, partners, top events
    GET  /historical-context     GGE bilateral alignment 1990-2024 for a CAMEO/ISO3 pair
    GET  /health                 ML layers and GGE availability

Time alignment. GDELT is daily; the other three agents are annual. This adapter
keeps the day it analysed in ``metadata.date`` and, where it can, puts that day
next to the annual GGE baseline for the same pair, so fusion can say whether
today's coverage is out of character for the relationship rather than treating
one day as if it were a year.

"Latest" means the most recent day GDELT has published: yesterday (UTC) when
the export exists, otherwise the day before.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import countries
from ..contract import insight
from ..intent import QueryPlan
from .base import AgentAdapter, AgentCallError, AgentResult, try_call

# CAMEO root codes 14-20 (EVENT_MAP labels in the module's preprocess.py).
CONFLICT_TYPES = {"Protest", "Exhibit Force", "Reduce Relations", "Coerce", "Assault", "Fight", "Mass Violence"}
COOPERATION_TYPES = {"Verbal Cooperation", "Material Cooperation", "Diplomatic Cooperation", "Consultation", "Mediation", "Engagement", "Provision of Aid", "Yield / Concession"}


def _tone(goldstein: float) -> str:
    if goldstein >= 2:
        return "cooperative"
    if goldstein >= 0.5:
        return "mildly cooperative"
    if goldstein > -0.5:
        return "neutral"
    if goldstein > -2:
        return "mildly conflictual"
    return "conflictual"


def _volume_confidence(n: int) -> float:
    # More events make the day's aggregate steadier, but GDELT's coding noise
    # caps how far that goes.
    return min(0.7, 0.3 + 0.1 * math.log10(1 + max(0, n)))


class EventsAdapter(AgentAdapter):
    name = "event_summarization"
    label = "Events"
    description = "Daily GDELT V1 events for a country: CAMEO event types, Goldstein tone, counterparts, spaCy-resolved actors, KMeans themes, GGE 1990-2024 baseline."
    time_grain = "daily (GDELT V1, 2013-present)"

    async def capabilities(self) -> dict:
        return {
            "agent": self.name,
            "description": self.description,
            "time_grain": self.time_grain,
            "join_key": "CAMEO actor country code -> ISO3",
            "native_endpoints": ["POST /analyze", "GET /historical-context", "POST /briefing", "POST /enrich-event", "WS /ws/pipeline"],
        }

    async def _analyze(self, iso3: str, day: str) -> dict:
        return await self.post("/analyze", json={"date": day, "country_code": countries.to_cameo(iso3), "limit": 25})

    async def _latest_analysis(self, iso3: str, plan: QueryPlan, result: AgentResult) -> Optional[tuple[str, dict]]:
        if plan.time.mode == "date" and plan.time.date:
            candidates = [plan.time.date]
        else:
            today = datetime.now(timezone.utc).date()
            candidates = [(today - timedelta(days=offset)).strftime("%Y%m%d") for offset in (1, 2, 3)]
        last_error: Optional[AgentCallError] = None
        for day in candidates:
            try:
                return day, await self._analyze(iso3, day)
            except AgentCallError as exc:
                last_error = exc
                text = str(exc)
                if exc.status_code == 404 and "No GDELT data" in text:
                    self.mark_last_call_handled()
                    result.notes.append(f"GDELT export for {day} not published; trying the previous day.")
                    continue
                if exc.status_code == 404:
                    self.mark_last_call_handled()
                    result.notes.append(f"No GDELT events for {countries.name_of(iso3)} on {day}.")
                    return None
                raise
        if last_error:
            raise last_error
        return None

    async def collect(self, plan: QueryPlan, result: AgentResult) -> tuple[list[dict], dict]:
        if not plan.entities:
            result.notes.append("Events answers questions about a specific country; none was given.")
            return [], {"query_type": plan.intent, "time_grain": "daily"}

        iso3 = plan.primary
        if plan.time.mode == "year":
            # A past year has no "today": answer from the annual GGE series only.
            return await self._historical_year(plan, result)
        found = await self._latest_analysis(iso3, plan, result)
        metadata: dict = {"query_type": plan.intent, "time_grain": "daily", "method": "GDELT V1 daily export; CAMEO roots; Goldstein scale"}
        if not found:
            return [], metadata
        day, payload = found
        metadata.update({"date": day, "year": int(day[:4]), "data_quality": {"events": (payload.get("metrics") or {}).get("total_events")}})

        insights = self._day_insights(iso3, day, payload, result)
        partner_iso3 = None
        if plan.intent == "bilateral" and len(plan.iso3s) >= 2:
            partner_iso3 = plan.iso3s[1]
            insights.extend(self._pair_today(iso3, partner_iso3, day, result.context.get("partners", [])))
        elif result.context.get("partners"):
            partner_iso3 = result.context["partners"][0]["iso3"]

        if partner_iso3:
            baseline = await try_call(self.get("/historical-context", params={"cc1": countries.to_cameo(iso3), "cc2": countries.to_cameo(partner_iso3)}), None)
            if baseline and baseline.get("available"):
                insights.append(self._baseline_insight(iso3, partner_iso3, baseline))
            elif baseline is None and any(c.status == 503 for c in self._calls if c.path == "/historical-context"):
                result.notes.append("GGE 1990-2024 baseline unavailable: the Events service has no dyad_geopolitical_scores.csv (see docs/DATA.md).")
        return insights, metadata

    async def _historical_year(self, plan: QueryPlan, result: AgentResult) -> tuple[list[dict], dict]:
        year = plan.time.year
        metadata = {"query_type": plan.intent, "time_grain": "annual (GGE)", "year": year, "method": "GGE bilateral alignment scores (Fan, 2025)"}
        if len(plan.iso3s) < 2:
            result.notes.append(f"Daily GDELT events do not describe {year}; a second country is needed for the GGE annual baseline.")
            return [], metadata
        a, b = plan.iso3s[:2]
        baseline = await try_call(self.get("/historical-context", params={"cc1": countries.to_cameo(a), "cc2": countries.to_cameo(b)}), None)
        if not baseline or not baseline.get("available"):
            result.notes.append("No GGE baseline for this pair.")
            return [], metadata
        insights = [self._baseline_insight(a, b, baseline)]
        point = next((p for p in baseline.get("sparkline") or [] if p.get("year") == year), None)
        if point is not None:
            score = float(point.get("score") or 0.0)
            insights.append(
                insight(
                    a,
                    f"In {year} the GGE alignment score for {countries.name_of(a)}-{countries.name_of(b)} was {score:+.3f} "
                    f"(10-year average to {baseline.get('latest_year')}: {baseline.get('avg_10yr', 0):+.3f}).",
                    score,
                    0.75,
                    "annual bilateral alignment score from the Global Geopolitical Events database (Fan, 2025)",
                    {"pair": [a, b], "year": year, "score": score},
                    facet="bilateral_events",
                )
            )
        return insights, metadata

    def _day_insights(self, iso3: str, day: str, payload: dict, result: AgentResult) -> list[dict]:
        name = countries.name_of(iso3)
        metrics = payload.get("metrics") or {}
        total = int(metrics.get("total_events") or 0)
        goldstein = float(metrics.get("avg_goldstein") or 0.0)
        types = payload.get("event_type_counts") or {}
        typed_total = sum(types.values()) or 1
        conflict = sum(v for k, v in types.items() if k in CONFLICT_TYPES)
        cooperation = sum(v for k, v in types.items() if k in COOPERATION_TYPES)
        domestic = (payload.get("domestic") or {}).get("total", 0)
        pretty_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        confidence = _volume_confidence(total)
        reason = f"{total} machine-coded GDELT events; coverage carries publication-location bias"

        partners = []
        for p in payload.get("partners") or []:
            partner_iso3 = countries.from_cameo(p.get("code"))
            if partner_iso3:
                partners.append({"iso3": partner_iso3, "count": int(p.get("count") or 0), "avg_goldstein": float(p.get("avg_goldstein") or 0.0)})
        result.context["partners"] = partners
        result.context["date"] = day

        out = [
            insight(
                iso3,
                f"{pretty_day}: {total} GDELT events involve {name}, mean Goldstein {goldstein:+.2f} ({_tone(goldstein)}); "
                f"{conflict / typed_total:.0%} conflictual vs {cooperation / typed_total:.0%} cooperative event types.",
                (goldstein + 10.0) / 20.0,
                confidence,
                reason,
                {
                    "date": day,
                    "total_events": total,
                    "avg_goldstein": round(goldstein, 3),
                    "tone": _tone(goldstein),
                    "conflict_share": round(conflict / typed_total, 3),
                    "cooperation_share": round(cooperation / typed_total, 3),
                    "domestic_events": domestic,
                    "international_events": (payload.get("international") or {}).get("total", 0),
                    # The module counts an event as domestic only when both actors
                    # carry this country's code, so events whose counterpart GDELT
                    # left uncoded land in "international".
                    "domestic_split_note": "events with an uncoded counterpart are counted as international by the module",
                    "event_type_counts": types,
                },
                facet="event_activity",
            )
        ]
        if partners:
            text = ", ".join(f"{countries.name_of(p['iso3'])} ({p['count']} events, {p['avg_goldstein']:+.1f})" for p in partners[:3])
            out.append(
                insight(
                    iso3,
                    f"Most active counterparts for {name} on {pretty_day}: {text}.",
                    partners[0]["count"] / max(1, total),
                    confidence,
                    reason,
                    {"date": day, "partners": partners[:8]},
                    facet="event_partners",
                )
            )
        top = (payload.get("top5_events") or [])[:1]
        if top:
            event = top[0]
            out.append(
                insight(
                    iso3,
                    f"Top event: {event.get('sentence')}",
                    float(event.get("score") or 0.0),
                    min(confidence, 0.45),
                    "single machine-coded event; GDELT often miscodes accidents and domestic politics, so verify against the source article",
                    {"date": day, "event_type": event.get("event_type"), "tone": event.get("tone"), "url": event.get("url"), "num_articles": event.get("num_articles")},
                    facet="event_headline",
                )
            )
        return out

    @staticmethod
    def _pair_today(iso3: str, other: str, day: str, partners: list[dict]) -> list[dict]:
        a, b = countries.name_of(iso3), countries.name_of(other)
        match = next((p for p in partners if p["iso3"] == other), None)
        if not match:
            return [
                insight(iso3, f"{b} is not among {a}'s eight most active counterparts in GDELT on {day[:4]}-{day[4:6]}-{day[6:]}.", 0.0, 0.45, "absence from the top counterparts on one day", {"pair": [iso3, other], "date": day}, facet="bilateral_events")
            ]
        return [
            insight(
                iso3,
                f"{a}-{b} coverage on {day[:4]}-{day[4:6]}-{day[6:]}: {match['count']} events, mean Goldstein {match['avg_goldstein']:+.2f} ({_tone(match['avg_goldstein'])}).",
                (match["avg_goldstein"] + 10.0) / 20.0,
                _volume_confidence(match["count"]),
                f"{match['count']} machine-coded events for the pair on one day",
                {"pair": [iso3, other], "date": day, **match, "tone": _tone(match["avg_goldstein"])},
                facet="bilateral_events",
            )
        ]

    @staticmethod
    def _baseline_insight(iso3: str, other: str, baseline: dict) -> dict:
        return insight(
            iso3,
            f"{countries.name_of(iso3)}-{countries.name_of(other)} 1990-2024 baseline (GGE): {baseline.get('baseline_label')}, "
            f"10-year average {baseline.get('avg_10yr', 0):+.3f}, trend {baseline.get('trend')}.",
            float(baseline.get("avg_10yr") or 0.0),
            0.75,
            "annual bilateral alignment scores from the Global Geopolitical Events database (Fan, 2025)",
            {"pair": [iso3, other], **{k: baseline.get(k) for k in ("baseline_label", "avg_10yr", "latest_static", "latest_dynamic", "trend", "earliest_year", "latest_year")}},
            facet="relationship_baseline",
        )
