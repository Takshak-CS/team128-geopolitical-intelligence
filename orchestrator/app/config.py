"""Runtime configuration, all overridable through environment variables.

The four agents are separate HTTP services. Their addresses default to the
ports scripts/run_all.ps1 and docker-compose.yml assign:

    soft_power           8101
    policy_stance        8102
    trade_intelligence   8103
    event_summarization  8104
    orchestrator         8000
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class AgentConfig:
    name: str
    base_url: str
    timeout_s: float
    dashboard_url: str
    enabled: bool = True


def _agent(name: str, env_prefix: str, default_url: str, default_timeout: float, default_dashboard: str) -> AgentConfig:
    return AgentConfig(
        name=name,
        base_url=os.environ.get(f"{env_prefix}_URL", default_url).rstrip("/"),
        timeout_s=_env_float(f"{env_prefix}_TIMEOUT", default_timeout),
        dashboard_url=os.environ.get(f"{env_prefix}_DASHBOARD_URL", default_dashboard),
        enabled=os.environ.get(f"{env_prefix}_ENABLED", "1").strip().lower() not in ("0", "false", "no"),
    )


def load_agents() -> dict[str, AgentConfig]:
    agents = [
        _agent("soft_power", "SOFT_POWER", "http://127.0.0.1:8101", 10.0, "http://localhost:5174"),
        _agent("policy_stance", "POLICY_STANCE", "http://127.0.0.1:8102", 15.0, "http://localhost:5175"),
        _agent("trade_intelligence", "TRADE", "http://127.0.0.1:8103", 20.0, "http://localhost:8080/?api=http://127.0.0.1:8103"),
        # Events can download that day's GDELT export (~10-20 MB) and run spaCy on
        # the first request for a date, so it gets the longest budget.
        _agent("event_summarization", "EVENTS", "http://127.0.0.1:8104", 120.0, "http://localhost:5176"),
    ]
    return {agent.name: agent for agent in agents}


# Latest year each annual agent can serve when it cannot be asked. Used only as a
# fallback: the orchestrator prefers what an agent reports about itself.
DEFAULT_LATEST_YEAR = {
    "soft_power": 2024,
    "policy_stance": 2025,
    "trade_intelligence": 2024,
}

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ORCHESTRATOR_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]
