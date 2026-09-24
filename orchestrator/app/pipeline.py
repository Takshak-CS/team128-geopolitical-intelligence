"""The orchestration pipeline behind ``POST /ask``.

    question
      -> parse          intent, ISO3 entities, time window, agents   (intent.py)
      -> align time     newest year every selected annual agent can serve
      -> fan out        all selected agents in parallel, per-agent timeouts
      -> normalise      each adapter returns the shared envelope    (agents/)
      -> fuse           dedupe, corroborate, diverge, rank          (fusion.py)
      -> brief          cited narrative                             (briefing.py)

A slow or down agent degrades the briefing - its status says why - instead of
failing the question.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from . import briefing, fusion, intent
from .agents.base import AgentAdapter, AgentCallError, AgentResult
from .agents.events import EventsAdapter
from .agents.policy_stance import PolicyStanceAdapter
from .agents.soft_power import SoftPowerAdapter
from .agents.trade import TradeAdapter
from .config import DEFAULT_LATEST_YEAR, AgentConfig, load_agents
from .contract import AGENT_LABELS

ADAPTERS: dict[str, type[AgentAdapter]] = {
    "soft_power": SoftPowerAdapter,
    "policy_stance": PolicyStanceAdapter,
    "trade_intelligence": TradeAdapter,
    "event_summarization": EventsAdapter,
}

# First year each annual agent's data supports.
COVERAGE_START = {"soft_power": 2000, "policy_stance": 1989, "trade_intelligence": 1995}


class Orchestrator:
    def __init__(self, configs: Optional[dict[str, AgentConfig]] = None, client: Optional[httpx.AsyncClient] = None):
        self.configs = configs or load_agents()
        self.client = client or httpx.AsyncClient(headers={"User-Agent": "team128-orchestrator/1.0"})
        self._caches: dict[str, dict] = {name: {} for name in ADAPTERS}

    def adapter(self, name: str) -> AgentAdapter:
        return ADAPTERS[name](self.configs[name], self.client, self._caches[name])

    async def close(self) -> None:
        await self.client.aclose()

    # ----------------------------------------------------------- alignment
    async def _latest_years(self, agents: list[str]) -> dict[str, int]:
        years: dict[str, int] = {}

        async def trade() -> None:
            year = await self.adapter("trade_intelligence").latest_year()
            if year:
                years["trade_intelligence"] = int(year)

        async def soft_power() -> None:
            try:
                board = await self.adapter("soft_power").leaderboard()
                latest = max((row.get("year") or 0 for row in board), default=0)
                if latest:
                    years["soft_power"] = int(latest)
            except AgentCallError:
                pass

        jobs = []
        if "trade_intelligence" in agents and self.configs["trade_intelligence"].enabled:
            jobs.append(trade())
        if "soft_power" in agents and self.configs["soft_power"].enabled:
            jobs.append(soft_power())
        if jobs:
            try:
                await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        for agent in agents:
            if agent in DEFAULT_LATEST_YEAR:
                years.setdefault(agent, DEFAULT_LATEST_YEAR[agent])
        return years

    async def align_time(self, plan: intent.QueryPlan) -> dict:
        annual = [a for a in plan.agents if a in DEFAULT_LATEST_YEAR]
        latest = await self._latest_years(annual)
        warnings: list[str] = []
        if plan.time.mode == "year":
            year = plan.time.year
            for agent in annual:
                start, end = COVERAGE_START.get(agent, 0), latest.get(agent, 9999)
                if not start <= year <= end:
                    warnings.append(f"{AGENT_LABELS[agent]} covers {start}-{end}; {year} is outside it.")
            aligned = year
        else:
            aligned = min(latest.values()) if latest else None
            if latest and len(set(latest.values())) > 1:
                warnings.append(
                    f"Annual agents aligned on {aligned}, the newest year all of them can serve "
                    f"({', '.join(f'{AGENT_LABELS[a]} to {y}' for a, y in sorted(latest.items()))})."
                )
        return {"mode": plan.time.mode, "aligned_year": aligned, "latest_by_agent": latest, "warnings": warnings}

    # --------------------------------------------------------------- ask
    async def _run_agent(self, name: str, plan: intent.QueryPlan, context: dict) -> AgentResult:
        config = self.configs[name]
        if not config.enabled:
            return AgentResult(agent=name, status="disabled", error="disabled by configuration", dashboard_url=config.dashboard_url)
        adapter = self.adapter(name)
        started = time.perf_counter()
        try:
            # A small margin over the per-call timeout, so the adapter's own
            # timeout reports first and the log says which call was slow.
            return await asyncio.wait_for(adapter.run(plan, context), timeout=config.timeout_s + 5.0)
        except asyncio.TimeoutError:
            result = AgentResult(agent=name, status="timeout", error=f"no answer within {config.timeout_s:.0f}s", dashboard_url=config.dashboard_url)
            result.calls = list(adapter._calls)
            result.latency_ms = (time.perf_counter() - started) * 1000
            return result
        except Exception as exc:  # noqa: BLE001 - one adapter bug must not sink the briefing
            return AgentResult(agent=name, status="error", error=f"adapter failure: {type(exc).__name__}: {exc}", dashboard_url=config.dashboard_url, latency_ms=(time.perf_counter() - started) * 1000)

    async def ask(self, question: str, overrides: Optional[dict] = None, include_envelopes: bool = True) -> dict:
        started = time.perf_counter()
        plan = intent.parse(question, overrides)
        alignment = await self.align_time(plan)
        context = {"aligned_year": alignment["aligned_year"]}

        results_list = await asyncio.gather(*(self._run_agent(name, plan, context) for name in plan.agents))
        results = {result.agent: result for result in results_list}

        alignment["served"] = _served(results)
        fused = fusion.fuse(plan, results)
        brief = briefing.compose(plan, fused, results, alignment)

        return {
            "question": question,
            "plan": plan.to_dict(),
            "time_alignment": alignment,
            "briefing": brief,
            "fused": fused,
            "agents": {name: result.to_dict(include_envelope=include_envelopes) for name, result in results.items()},
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ------------------------------------------------------------ status
    async def agents_health(self) -> dict:
        async def probe(name: str) -> tuple[str, dict]:
            config = self.configs[name]
            if not config.enabled:
                return name, {"status": "disabled"}
            started = time.perf_counter()
            health = await self.adapter(name).health()
            health.update({"base_url": config.base_url, "dashboard_url": config.dashboard_url, "label": AGENT_LABELS[name], "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
            return name, health

        pairs = await asyncio.gather(*(probe(name) for name in ADAPTERS))
        return dict(pairs)

    async def capabilities(self) -> dict:
        async def one(name: str) -> tuple[str, dict]:
            if not self.configs[name].enabled:
                return name, {"agent": name, "status": "disabled"}
            return name, await self.adapter(name).capabilities()

        pairs = await asyncio.gather(*(one(name) for name in ADAPTERS))
        return {
            "orchestrator": {
                "intents": list(intent.INTENTS),
                "join_key": "entity_iso3",
                "contract": "Team 128 shared four-agent response envelope",
                "fusion": ["dedupe", "corroboration", "divergence", "confidence ranking"],
            },
            "agents": dict(pairs),
        }


def _served(results: dict[str, AgentResult]) -> dict[str, str]:
    served: dict[str, str] = {}
    for name, result in results.items():
        meta = result.envelope.get("metadata") or {}
        if meta.get("date"):
            day = str(meta["date"])
            served[name] = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        elif meta.get("year"):
            served[name] = str(meta["year"])
    return served
