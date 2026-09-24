"""Shared machinery for agent adapters.

An adapter knows one agent's native API and turns what it returns into the shared
envelope. The base class handles the parts every adapter needs the same way:
HTTP calls with a per-agent timeout, a log of every call made (so a briefing can
show exactly what each claim rests on), a small TTL cache for reference data that
does not change between questions, and a uniform failure shape so one broken
agent degrades the briefing instead of failing it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ..config import AgentConfig
from ..contract import envelope as make_envelope
from ..intent import QueryPlan

# Statuses an agent result can carry. Only "ok" and "partial" contribute insights.
STATUSES = ("ok", "partial", "not_ready", "unavailable", "timeout", "error", "skipped", "disabled")


class AgentCallError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, unreachable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.unreachable = unreachable


class AgentNotReady(Exception):
    """The agent is up but still loading its data."""


@dataclass
class CallRecord:
    method: str
    path: str
    status: Optional[int]
    ms: float
    error: Optional[str] = None
    # An error the adapter expected and recovered from (e.g. GDELT has not yet
    # published a day, so it falls back to the previous one). Logged, but it
    # does not make the result "partial".
    handled: bool = False


@dataclass
class AgentResult:
    agent: str
    status: str
    envelope: dict = field(default_factory=dict)
    calls: list[CallRecord] = field(default_factory=list)
    latency_ms: float = 0.0
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    # Reference data fusion needs beyond the insights themselves, e.g. the full
    # country-to-bloc map from Policy Stance or the leaderboard from Soft Power.
    context: dict = field(default_factory=dict)
    dashboard_url: Optional[str] = None

    @property
    def insights(self) -> list[dict]:
        return list(self.envelope.get("insights", [])) if self.status in ("ok", "partial") else []

    def to_dict(self, include_envelope: bool = True) -> dict:
        payload = {
            "agent": self.agent,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
            "notes": self.notes,
            "calls": [call.__dict__ for call in self.calls],
            "dashboard_url": self.dashboard_url,
            "insight_count": len(self.insights),
        }
        if include_envelope:
            payload["envelope"] = self.envelope
        return payload


class AgentAdapter:
    name = "agent"
    label = "Agent"
    description = ""
    time_grain = "annual"

    def __init__(self, config: AgentConfig, client: httpx.AsyncClient, cache: Optional[dict] = None):
        # One adapter instance serves one question, so its call log is never
        # shared between concurrent requests. The cache is shared on purpose.
        self.config = config
        self.client = client
        self._cache: dict[str, tuple[float, Any]] = cache if cache is not None else {}
        self._calls: list[CallRecord] = []
        # Facts the pipeline resolved before fan-out, e.g. the aligned year.
        self.shared: dict = {}

    # ------------------------------------------------------------------ HTTP
    async def _request(self, method: str, path: str, *, params: Any = None, json: Any = None, timeout: Optional[float] = None) -> Any:
        url = f"{self.config.base_url}{path}"
        started = time.perf_counter()
        budget = timeout or self.config.timeout_s
        # A down agent should be reported in about a second, not after the
        # whole read budget meant for a slow-but-working one.
        limits = httpx.Timeout(budget, connect=min(1.5, budget))
        try:
            response = await self.client.request(method, url, params=params, json=json, timeout=limits)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            self._log(method, path, None, started, f"unreachable: {type(exc).__name__}")
            raise AgentCallError(f"{self.label} agent unreachable at {self.config.base_url}", unreachable=True) from exc
        except httpx.TimeoutException as exc:
            self._log(method, path, None, started, "timeout")
            raise AgentCallError(f"{self.label} agent timed out on {path}") from exc
        except httpx.HTTPError as exc:
            self._log(method, path, None, started, type(exc).__name__)
            raise AgentCallError(f"{self.label} agent request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = _error_detail(response)
            self._log(method, path, response.status_code, started, detail)
            raise AgentCallError(detail, status_code=response.status_code)
        self._log(method, path, response.status_code, started)
        try:
            return response.json()
        except ValueError as exc:
            raise AgentCallError(f"{self.label} agent returned non-JSON from {path}") from exc

    async def get(self, path: str, params: Any = None, **kwargs: Any) -> Any:
        return await self._request("GET", path, params=params, **kwargs)

    async def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return await self._request("POST", path, json=json, **kwargs)

    async def cached_get(self, path: str, params: Any = None, ttl_s: float = 300.0) -> Any:
        key = f"{path}?{params!r}"
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl_s:
            return hit[1]
        value = await self.get(path, params=params)
        self._cache[key] = (time.monotonic(), value)
        return value

    def mark_last_call_handled(self) -> None:
        if self._calls:
            self._calls[-1].handled = True

    def _log(self, method: str, path: str, status: Optional[int], started: float, error: Optional[str] = None) -> None:
        self._calls.append(CallRecord(method=method, path=path, status=status, ms=round((time.perf_counter() - started) * 1000, 1), error=error))

    # ------------------------------------------------------------- lifecycle
    async def health(self) -> dict:
        try:
            payload = await self.get("/health", timeout=min(5.0, self.config.timeout_s))
            return {"status": "ok", "detail": payload}
        except AgentCallError as exc:
            return {"status": "unavailable" if exc.unreachable else "error", "detail": str(exc)}

    async def capabilities(self) -> dict:
        """What this agent answers. Agents without a /capabilities endpoint describe themselves here."""
        return {"agent": self.name, "description": self.description, "time_grain": self.time_grain}

    async def run(self, plan: QueryPlan, context: dict) -> AgentResult:
        """Execute the plan against this agent. Subclasses implement ``collect``."""
        self._calls = []
        self.shared = dict(context or {})
        started = time.perf_counter()
        result = AgentResult(agent=self.name, status="ok", dashboard_url=self.config.dashboard_url)
        try:
            insights, metadata = await self.collect(plan, result)
            result.envelope = make_envelope(self.name, insights, metadata)
            failed = [call for call in self._calls if call.error and not call.handled]
            if not insights:
                result.status = "error" if failed else "ok"
                if failed and not result.error:
                    result.error = failed[0].error
                if not failed:
                    result.notes.append("No insights for this question.")
            elif failed:
                result.status = "partial"
        except AgentNotReady as exc:
            result.status = "not_ready"
            result.error = str(exc)
        except AgentCallError as exc:
            result.status = "unavailable" if exc.unreachable else "error"
            result.error = str(exc)
        result.calls = list(self._calls)
        result.latency_ms = (time.perf_counter() - started) * 1000
        return result

    async def collect(self, plan: QueryPlan, result: AgentResult) -> tuple[list[dict], dict]:
        raise NotImplementedError


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else body
        if isinstance(detail, list):
            detail = "; ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail)
        return f"HTTP {response.status_code}: {detail}"
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"


async def try_call(coro, fallback: Any = None) -> Any:
    """Await an optional call; a failure is already logged, so return the fallback."""
    try:
        return await coro
    except AgentCallError:
        return fallback
