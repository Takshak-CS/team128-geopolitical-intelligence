"""Trade Intelligence adapter (Takshak's module, FastAPI over CEPII BACI HS92).

This agent already speaks the shared envelope natively (``POST /query``), so the
adapter's job is selection and tagging, not translation: pick which of the six
query types answer the plan, run them in parallel, and label each insight with
the facet fusion lines it up against.

    risk       -> trade_exposure        structural risk, HHI concentration, top partners
    blocs      -> trade_alignment       Louvain bloc membership and its anchor
    leverage   -> trade_dependence      who depends on whom more, most critical partner
    fragility  -> supply_fragility      per-sector supplier concentration
    shock      -> shock_impact          export disruption propagated through the graph
    forecast   -> trade_outlook         projection with model selection by rolling MAPE
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .. import countries
from ..contract import insight
from ..intent import QueryPlan
from .base import AgentAdapter, AgentCallError, AgentResult

FACETS = {
    "risk": "trade_exposure",
    "blocs": "trade_alignment",
    "leverage": "trade_dependence",
    "fragility": "supply_fragility",
    "shock": "shock_impact",
    "forecast": "trade_outlook",
}


def _strip_reason(claim: str, reason: str) -> str:
    """The module appends its confidence reason to the claim; the envelope already carries it."""
    if reason and claim.rstrip().endswith(reason.strip()):
        return claim.rstrip()[: -len(reason.strip())].rstrip()
    return claim


class TradeAdapter(AgentAdapter):
    name = "trade_intelligence"
    label = "Trade"
    description = "Directed weighted trade graph over CEPII BACI HS92: risk, shock propagation, forecast, leverage, blocs, sector fragility."
    time_grain = "annual (1995-2024)"

    async def capabilities(self) -> dict:
        try:
            native = await self.cached_get("/capabilities", ttl_s=600)
        except AgentCallError as exc:
            return {"agent": self.name, "description": self.description, "time_grain": self.time_grain, "error": str(exc)}
        native = dict(native)
        native.setdefault("time_grain", self.time_grain)
        # The country list is long and the UI does not need it.
        coverage = dict(native.get("coverage") or {})
        coverage.pop("countries", None)
        native["coverage"] = coverage
        return native

    async def latest_year(self) -> Optional[int]:
        try:
            caps = await self.cached_get("/capabilities", ttl_s=600)
            return (caps.get("coverage") or {}).get("last_year")
        except AgentCallError:
            return None

    async def _query(self, body: dict) -> dict:
        return await self.post("/query", json={key: value for key, value in body.items() if value is not None})

    async def collect(self, plan: QueryPlan, result: AgentResult) -> tuple[list[dict], dict]:
        year = plan.time.year if plan.time.mode == "year" else self.shared.get("aligned_year")
        base = {"year": year, "sector": plan.sector}
        jobs: list[tuple[str, dict]] = []

        if plan.intent == "shock" and plan.primary:
            jobs.append(("shock", {**base, "query_type": "shock", "country": plan.primary, "severity": plan.severity or 0.5, "limit": 8}))
            jobs.append(("blocs", {**base, "query_type": "blocs", "country": plan.primary}))
        elif plan.intent == "forecast" and plan.primary:
            periods = None
            if plan.time.horizon_year:
                periods = max(1, min(10, plan.time.horizon_year - (await self.latest_year() or 2024)))
            jobs.append(("forecast", {"query_type": "forecast", "country": plan.primary, "sector": plan.sector, "metric": plan.metric, "periods": periods}))
            jobs.append(("risk", {**base, "query_type": "risk", "country": plan.primary}))
        elif plan.intent in ("ranking",) or not plan.entities:
            query_type = plan.trade_query or "risk"
            jobs.append((query_type, {**base, "query_type": query_type, "limit": plan.limit}))
        elif plan.intent == "blocs":
            for iso3 in plan.iso3s[:2]:
                jobs.append(("blocs", {**base, "query_type": "blocs", "country": iso3}))
        elif plan.intent == "bilateral":
            for iso3 in plan.iso3s[:2]:
                jobs.append(("blocs", {**base, "query_type": "blocs", "country": iso3}))
                jobs.append(("leverage", {**base, "query_type": "leverage", "country": iso3}))
        elif plan.intent == "events" and plan.primary:
            jobs.append(("leverage", {**base, "query_type": "leverage", "country": plan.primary}))
        else:  # country_profile
            iso3 = plan.primary
            for query_type in ("risk", "blocs", "leverage", "fragility"):
                jobs.append((query_type, {**base, "query_type": query_type, "country": iso3}))

        responses = await asyncio.gather(*(self._query(body) for _, body in jobs), return_exceptions=True)
        insights: list[dict] = []
        metadata: dict = {"query_type": plan.intent, "time_grain": "annual", "sub_queries": []}
        for (query_type, body), response in zip(jobs, responses):
            if isinstance(response, AgentCallError):
                metadata["sub_queries"].append({"query_type": query_type, "country": body.get("country"), "error": str(response)})
                continue
            if isinstance(response, Exception):
                raise response
            meta = response.get("metadata") or {}
            metadata["sub_queries"].append({"query_type": query_type, "country": body.get("country"), "year": meta.get("year"), "method": meta.get("method")})
            metadata.setdefault("year", meta.get("year"))
            metadata.setdefault("sector", meta.get("sector"))
            metadata.setdefault("data_quality", meta.get("data_quality"))
            for item in self._select(query_type, response.get("insights") or [], plan):
                tagged = dict(item)
                tagged["claim"] = _strip_reason(tagged.get("claim", ""), tagged.get("reason", ""))
                tagged["facet"] = FACETS[query_type]
                tagged.setdefault("evidence", {})["query_type"] = query_type
                insights.append(tagged)

        if plan.intent == "bilateral" and len(plan.iso3s) >= 2:
            insights.extend(self._bilateral(plan.iso3s[:2], insights))
        return insights, metadata

    @staticmethod
    def _select(query_type: str, items: list[dict], plan: QueryPlan) -> list[dict]:
        if query_type == "fragility" and plan.entities:
            # One insight per sector; the brittle ones matter most for a profile.
            return sorted(items, key=lambda i: i.get("score") or 0, reverse=True)[:3]
        if query_type == "shock":
            return items[: plan.limit + 1]
        return items[: max(plan.limit, 1)] if not plan.entities else items[:1]

    @staticmethod
    def _bilateral(pair: list[str], found: list[dict]) -> list[dict]:
        """Direct dependence between the two countries, read from each side's leverage lists."""
        a, b = pair
        name_a, name_b = countries.name_of(a), countries.name_of(b)
        blocs = {i["entity_iso3"]: i.get("evidence", {}) for i in found if i.get("facet") == "trade_alignment"}
        out: list[dict] = []
        if a in blocs and b in blocs:
            anchor_a, anchor_b = blocs[a].get("bloc_anchor_iso3"), blocs[b].get("bloc_anchor_iso3")
            same = anchor_a is not None and anchor_a == anchor_b
            out.append(
                insight(
                    a,
                    f"{name_a} and {name_b} are in the same trading bloc (anchored by {countries.name_of(anchor_a)})." if same
                    else f"{name_a} and {name_b} sit in different trading blocs ({countries.name_of(anchor_a)}-anchored vs {countries.name_of(anchor_b)}-anchored).",
                    1.0 if same else 0.0,
                    0.85,
                    "Louvain communities on the undirected trade projection",
                    {"pair": pair, "same_bloc": same, "anchors": [anchor_a, anchor_b]},
                    facet="bilateral_trade_bloc",
                )
            )
        for holder, other in ((a, b), (b, a)):
            lev = next((i for i in found if i.get("facet") == "trade_dependence" and i["entity_iso3"] == holder), None)
            if not lev:
                continue
            ev = lev.get("evidence", {})
            other_name = countries.name_of(other)
            rows = (ev.get("holds_leverage_over") or []) + (ev.get("vulnerable_to") or [])
            for row in rows:
                names = {countries.resolve(row.get("leverage_holder")), countries.resolve(row.get("exposed_country"))}
                if other in names:
                    exposed = countries.resolve(row.get("exposed_country"))
                    out.append(
                        insight(
                            exposed,
                            f"{countries.name_of(exposed)} is the more dependent side of the {name_a}-{name_b} trade relationship: "
                            f"{(row.get('exposed_dependence') or 0) * 100:.1f}% of its trade vs {(row.get('holder_dependence') or 0) * 100:.1f}% for the other side.",
                            row.get("asymmetry") or 0,
                            lev.get("confidence", 0.8),
                            lev.get("reason", ""),
                            {"pair": pair, **row},
                            facet="bilateral_trade_dependence",
                        )
                    )
                    return out
            if ev.get("most_critical_partner_iso3") == other:
                out.append(
                    insight(
                        holder,
                        f"{other_name} is {countries.name_of(holder)}'s most critical trade relationship ({(ev.get('critical_partner_dependence') or 0) * 100:.1f}% of its trade).",
                        ev.get("critical_partner_dependence") or 0,
                        lev.get("confidence", 0.8),
                        lev.get("reason", ""),
                        {"pair": pair, "critical_partner_dependence": ev.get("critical_partner_dependence")},
                        facet="bilateral_trade_dependence",
                    )
                )
        return out
