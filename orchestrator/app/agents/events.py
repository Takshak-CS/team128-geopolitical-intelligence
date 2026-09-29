"""Event Summarization adapter (Shreyas's module, FastAPI over GDELT V1 + GGE).

Native API:
    POST /analyze                {date: YYYYMMDD, country_code: CAMEO} -> metrics, partners, top events,
                                 KMeans themes with their validation (cluster_quality)
    GET  /historical-context     GGE bilateral alignment 1990-2024 for a CAMEO/ISO3 pair
    GET  /article-relevance      whether a source article actually names the event's two actors (no AI call)
    GET  /health                 ML layers and GGE availability

Claims, by facet:
    event_activity         the day's volume, tone, conflict/cooperation mix, share initiated
    event_partners         most active counterparts
    event_themes           KMeans themes, stated with the module's own cluster validation
    event_domestic_split   domestic vs international, with the module's counting caveat
    event_headline         the top three events, each checked against its source article
    relationship_baseline  GGE 1990-2024 baseline for the top three counterparts, next to today

GDELT's machine coding is noisy: an article about fuel prices can be coded as a
military clash. So each headline event is checked against its source article
before the briefing repeats it, and one the article does not support is flagged
as likely mis-tagged instead of being quoted as news.

Time alignment. GDELT is daily; the other three agents are annual. This adapter
keeps the day it analysed in ``metadata.date`` and, where it can, puts that day
next to the annual GGE baseline for the same pair, so fusion can say whether
today's coverage is out of character for the relationship rather than treating
one day as if it were a year.

"Latest" means the most recent day GDELT has published: yesterday (UTC) when
the export exists, otherwise the day before.
"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from .. import countries
from ..contract import insight
from ..intent import QueryPlan
from .base import AgentAdapter, AgentCallError, AgentResult, try_call

# CAMEO root codes 14-20 (EVENT_MAP labels in the module's preprocess.py).
CONFLICT_TYPES = {"Protest", "Exhibit Force", "Reduce Relations", "Coerce", "Assault", "Fight", "Mass Violence"}
COOPERATION_TYPES = {"Verbal Cooperation", "Material Cooperation", "Diplomatic Cooperation", "Consultation", "Mediation", "Engagement", "Provision of Aid", "Yield / Concession"}

HEADLINE_EVENTS = 3
BASELINE_PARTNERS = 3
RELEVANCE_TIMEOUT_S = 30.0

# /article-relevance "link" -> how far the article supports the event.
VERIFICATION = {
    "together": "verified",    # both actors named in the same, non-list sentence
    "listed": "weak",          # both named, but only in a list or apart
    "one_sided": "weak",       # only one actor named
    "none": "mistagged",       # neither actor named
}
HEADLINE_CONFIDENCE = {"verified": 0.55, "weak": 0.35, "unverified": 0.45, "mistagged": 0.15}

# Words in a URL path that say nothing about an article's subject.
_SLUG_NOISE = {"news", "article", "articles", "story", "stories", "world", "nation", "html", "index", "amp", "the", "and", "for",
               "with", "from", "that", "this", "what", "about", "after", "over", "into", "local", "national", "international"}
_GENERIC_ACTOR = re.compile(r"^(an? |the )?(unidentified|unknown|unnamed)\b", re.I)


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


def _slug_words(url: str) -> list[str]:
    """Subject words from the hyphenated slug segments of a URL path.

    Only hyphenated segments count, so opaque IDs ("article-909972",
    "article_82cca2f2-0bbc-...") contribute nothing."""
    words: list[str] = []
    for segment in urlsplit(url or "").path.lower().split("/"):
        if "-" not in segment:
            continue
        for part in segment.split("-"):
            if part.isalpha() and len(part) >= 3 and part not in _SLUG_NOISE:
                words.append(part)
    return words


def _slug_check(url: str, actor1: str, actor2: str) -> Optional[str]:
    """Fallback when the article itself cannot be fetched: "none" when the URL's
    slug is descriptive (4+ subject words) and names neither actor, "named" when
    it names one, None when the slug cannot settle it.

    Only country actors can be checked this way. A role label ("Police",
    "Gang") or a generic one ("an unidentified party") has no name a slug
    would carry, so any such actor leaves the event unverified."""
    words = _slug_words(url)
    actors = list(dict.fromkeys(a.strip() for a in (actor1, actor2) if a and a.strip()))
    if len(words) < 4 or not actors or any(_GENERIC_ACTOR.match(a) or not countries.resolve(a) for a in actors):
        return None
    for actor in actors:
        tokens = [t for t in re.findall(r"[a-z]+", actor.lower()) if len(t) >= 3]
        # Prefix match, so "iran" also finds "iranian" and "israel" finds "israeli".
        if any(word.startswith(token) for token in tokens for word in words):
            return "named"
    return "none"


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
            "native_endpoints": ["POST /analyze", "GET /historical-context", "GET /article-relevance", "POST /briefing", "POST /enrich-event", "WS /ws/pipeline"],
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
        partners = result.context.get("partners", [])
        if plan.intent == "bilateral" and len(plan.iso3s) >= 2:
            baseline_partners = [plan.iso3s[1]]
            insights.extend(self._pair_today(iso3, plan.iso3s[1], day, partners))
        else:
            baseline_partners = [p["iso3"] for p in partners[:BASELINE_PARTNERS]]

        headlines, baselines = await asyncio.gather(
            self._headline_insights(iso3, day, payload, _volume_confidence(int((payload.get("metrics") or {}).get("total_events") or 0))),
            asyncio.gather(*(self._baseline(iso3, other) for other in baseline_partners)),
        )
        insights.extend(headlines)
        today_by_partner = {p["iso3"]: p for p in partners}
        for other, baseline in zip(baseline_partners, baselines):
            if baseline and baseline.get("available"):
                insights.append(self._baseline_insight(iso3, other, baseline, today_by_partner.get(other)))
        # GGE has no series for some pairs (e.g. China-Taiwan): a gap in the
        # dataset, not a failure of the agent.
        for call in self._calls:
            if call.path == "/historical-context" and call.status == 404:
                call.handled = True
        missing = [other for other, baseline in zip(baseline_partners, baselines) if baseline and baseline.get("missing_pair")]
        if missing:
            result.notes.append("No GGE 1990-2024 series for: " + ", ".join(f"{countries.name_of(iso3)}-{countries.name_of(o)}" for o in missing) + ".")
        if baseline_partners and any(c.status == 503 for c in self._calls if c.path == "/historical-context"):
            result.notes.append("GGE 1990-2024 baseline unavailable: the Events service has no dyad_geopolitical_scores.csv (see docs/DATA.md).")
        return insights, metadata

    async def _baseline(self, iso3: str, other: str) -> Optional[dict]:
        try:
            return await self.get("/historical-context", params={"cc1": countries.to_cameo(iso3), "cc2": countries.to_cameo(other)})
        except AgentCallError as exc:
            # 404: the GGE file is loaded but has no series for this pair.
            return {"available": False, "missing_pair": True} if exc.status_code == 404 else None

    async def _relevance(self, event: dict) -> Optional[dict]:
        url = event.get("url") or ""
        if not url.startswith(("http://", "https://")):
            return None
        params = {"url": url, "term1": event.get("actor1") or "", "term2": event.get("actor2") or ""}
        return await try_call(self.get("/article-relevance", params=params, timeout=min(RELEVANCE_TIMEOUT_S, self.config.timeout_s)), None)

    async def _headline_insights(self, iso3: str, day: str, payload: dict, volume_confidence: float) -> list[dict]:
        events = (payload.get("top5_events") or [])[:HEADLINE_EVENTS]
        checks = await asyncio.gather(*(self._relevance(event) for event in events))
        # The check is optional: a site that refuses the fetch is reported on the
        # claim itself, not as a failure of the Events agent.
        for call in self._calls:
            if call.path == "/article-relevance" and call.error:
                call.handled = True
        return [self._headline_insight(iso3, day, event, check, volume_confidence) for event, check in zip(events, checks)]

    @staticmethod
    def _headline_insight(iso3: str, day: str, event: dict, check: Optional[dict], volume_confidence: float) -> dict:
        actor1, actor2 = event.get("actor1") or "", event.get("actor2") or ""
        url = event.get("url") or ""
        link = (check or {}).get("link")
        status = VERIFICATION.get(link, "unverified")
        method = "article_text" if link in VERIFICATION else None
        verdict = (check or {}).get("verdict_text") or ("The article relevance check did not answer." if check is None else "")
        if status == "unverified" and check is not None and not check.get("article_ok"):
            # The site refused the fetch (often HTTP 403 to non-browsers); fall back to the URL.
            slug = _slug_check(url, actor1, actor2)
            if slug == "none":
                status, method = "mistagged", "url_only"
                subject = " ".join(_slug_words(url))
                verdict = f"The article could not be fetched, and its URL (\"{subject}\") names neither {actor1} nor {actor2}."
        score = float(event.get("score") or 0.0)
        confidence = min(volume_confidence, HEADLINE_CONFIDENCE[status])
        if method == "url_only":
            confidence = min(confidence, 0.2)
        rank = event.get("rank")
        if status == "mistagged":
            claim = (f"Likely mis-tagged by GDELT: event #{rank} codes {actor1} vs {actor2} as \"{event.get('event_type')}\" "
                     f"(Goldstein {score:+.1f}), but the source does not support it.")
            reason = "source article check (no AI): " + ("URL only, article text unavailable" if method == "url_only" else "full article text")
        else:
            claim = f"Top event #{rank}: {event.get('sentence')}"
            reason = ("single machine-coded event, confirmed against its source article" if status == "verified"
                      else "single machine-coded event; GDELT often miscodes accidents and domestic politics, so verify against the source article")
        caveat = None if status == "verified" else verdict or None
        return insight(
            iso3,
            claim,
            score,
            confidence,
            reason,
            {
                "date": day,
                "rank": rank,
                "actor1": actor1,
                "actor2": actor2,
                "event_type": event.get("event_type"),
                "goldstein": score,
                "tone": event.get("tone"),
                "url": url,
                "num_articles": event.get("num_articles"),
                "verification": {
                    "status": status,
                    "method": method,
                    "link": link,
                    "verdict": verdict,
                    "snippet": (check or {}).get("best_snippet") or None,
                },
            },
            facet="event_headline",
            caveat=caveat,
        )

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
        initiated = metrics.get("initiator_pct")
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
                f"{conflict / typed_total:.0%} conflictual vs {cooperation / typed_total:.0%} cooperative event types"
                + (f"; {name} initiated {initiated}% of them." if isinstance(initiated, (int, float)) else "."),
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
                    "initiator_pct": initiated,
                    "tone_counts": payload.get("tone_counts") or {},
                    "event_type_counts": types,
                },
                facet="event_activity",
            )
        ]
        themes = self._themes_insight(iso3, day, payload, confidence)
        if themes:
            out.append(themes)
        split = self._domestic_insight(iso3, day, payload, total, confidence)
        if split:
            out.append(split)
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
        return out

    @staticmethod
    def _themes_insight(iso3: str, day: str, payload: dict, volume_confidence: float) -> Optional[dict]:
        counts = {k: int(v) for k, v in (payload.get("cluster_counts") or {}).items() if v}
        total = sum(counts.values())
        if not total:
            return None
        themes = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        shares = ", ".join(f"{label} {count / total:.0%}" for label, count in themes)
        quality = payload.get("cluster_quality") or None
        silhouette = quality.get("silhouette") if quality else None
        caveat = None
        if isinstance(silhouette, (int, float)):
            null = quality.get("silhouette_null")
            ari = quality.get("stability_ari")
            validation = f"cluster quality: silhouette {silhouette:.2f}"
            if isinstance(null, (int, float)):
                validation += f" vs {null:.2f} on shuffled data"
            if isinstance(ari, (int, float)):
                validation += f", stability across seeds {ari:.2f}"
            validation += f" ({quality.get('label')})"
            # Separation above the shuffled baseline, scaled to the event-volume ceiling.
            confidence = min(volume_confidence, 0.35 + 0.5 * max(0.0, silhouette - max(0.0, null or 0.0)))
            if quality.get("weak"):
                confidence = min(confidence, 0.35)
                caveat = "The module rates today's clusters as weak, so treat these themes as tentative."
        else:
            validation = "cluster quality: not available" + (f" ({quality.get('reason')})" if quality and quality.get("reason") else "")
            confidence = min(volume_confidence, 0.4)
            caveat = "The module did not validate today's clustering, so the themes are unscored."
        return insight(
            iso3,
            f"{countries.name_of(iso3)}'s coverage on {day[:4]}-{day[4:6]}-{day[6:]} falls into {len(themes)} themes: {shares}; {validation}.",
            themes[0][1] / total,
            confidence,
            "KMeans themes over the day's events, validated by the module (silhouette vs a shuffled baseline, seed stability)",
            {"date": day, "themes": [{"label": label, "count": count, "share": round(count / total, 3)} for label, count in themes], "cluster_quality": quality},
            facet="event_themes",
            caveat=caveat,
        )

    @staticmethod
    def _domestic_insight(iso3: str, day: str, payload: dict, total: int, volume_confidence: float) -> Optional[dict]:
        domestic, international = payload.get("domestic") or {}, payload.get("international") or {}
        n_dom, n_int = int(domestic.get("total") or 0), int(international.get("total") or 0)
        if not (n_dom or n_int):
            return None
        name = countries.name_of(iso3)
        g_dom, g_int = float(domestic.get("avg_goldstein") or 0.0), float(international.get("avg_goldstein") or 0.0)
        return insight(
            iso3,
            f"{n_dom} of {total or n_dom + n_int} events are domestic to {name} (mean Goldstein {g_dom:+.2f}) "
            f"and {n_int} international ({g_int:+.2f}).",
            n_dom / max(1, n_dom + n_int),
            # The split is biased by construction (see caveat), so it never outranks the day's totals.
            min(volume_confidence, 0.4),
            "the module counts an event as domestic only when both actors carry the country's code",
            {
                "date": day,
                "domestic": {"total": n_dom, "avg_goldstein": round(g_dom, 3), "event_type_counts": domestic.get("event_type_counts") or {}},
                "international": {"total": n_int, "avg_goldstein": round(g_int, 3), "event_type_counts": international.get("event_type_counts") or {}},
            },
            facet="event_domestic_split",
            caveat=(f"GDELT often leaves the counterpart uncoded, and the module counts those events as international, "
                    f"so {n_dom} is a floor for domestic activity, not an estimate."),
        )

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
    def _baseline_insight(iso3: str, other: str, baseline: dict, today: Optional[dict] = None) -> dict:
        claim = (f"{countries.name_of(iso3)}-{countries.name_of(other)} 1990-2024 baseline (GGE): {baseline.get('baseline_label')}, "
                 f"10-year average {baseline.get('avg_10yr', 0):+.3f}, trend {baseline.get('trend')}")
        if today:
            claim += f"; today {today['count']} events at mean Goldstein {today['avg_goldstein']:+.1f} ({_tone(today['avg_goldstein'])})"
        evidence = {"pair": [iso3, other], **{k: baseline.get(k) for k in ("baseline_label", "avg_10yr", "latest_static", "latest_dynamic", "trend", "earliest_year", "latest_year")}}
        evidence["series"] = [{"year": p.get("year"), "score": p.get("score")} for p in baseline.get("sparkline") or [] if p.get("year") is not None]
        if today:
            evidence["today"] = {"count": today["count"], "avg_goldstein": round(today["avg_goldstein"], 3), "tone": _tone(today["avg_goldstein"])}
        return insight(
            iso3,
            claim + ".",
            float(baseline.get("avg_10yr") or 0.0),
            0.75,
            "annual bilateral alignment scores from the Global Geopolitical Events database (Fan, 2025)",
            evidence,
            facet="relationship_baseline",
        )
