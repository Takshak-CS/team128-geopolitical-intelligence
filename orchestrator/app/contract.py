"""The Team 128 shared four-agent response envelope.

    {
      "agent": "trade_intelligence",
      "metadata": { "query_type", "year", "sector", "data_quality", ... },
      "insights": [
        { "entity_iso3", "entity_name", "claim", "score", "confidence", "reason", "evidence" }
      ]
    }

The Trade agent emits this natively. The other three agents return their own
shapes, and the adapters in ``app.agents`` coerce them into it, so fusion only
ever sees one format.

Adapters add two optional fields the contract does not require: ``facet``, a
short label for *what aspect* of an entity the insight is about ("trade_alignment",
"diplomatic_alignment", ...), and ``caveat``, a sentence the reader must see next
to the claim (a known bias in how the number was produced, or a failed check).
Fusion uses ``facet`` to line up claims from different agents about the same
thing and carries ``caveat`` onto the finding. Consumers that only know the base
contract can ignore both.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from . import countries

REQUIRED_INSIGHT_FIELDS = ("entity_iso3", "entity_name", "claim", "score", "confidence", "reason", "evidence")

AGENT_LABELS = {
    "soft_power": "Soft Power",
    "policy_stance": "Policy Stance",
    "trade_intelligence": "Trade",
    "event_summarization": "Events",
}


def clamp01(value: float) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def insight(
    entity_iso3: Optional[str],
    claim: str,
    score: float,
    confidence: float,
    reason: str,
    evidence: Optional[Mapping[str, Any]] = None,
    facet: Optional[str] = None,
    entity_name: Optional[str] = None,
    caveat: Optional[str] = None,
) -> dict:
    """Build one insight in the shared shape."""
    iso3 = countries.resolve(entity_iso3) if entity_iso3 else None
    record = {
        "entity_iso3": iso3,
        "entity_name": entity_name or (countries.name_of(iso3) if iso3 else "global"),
        "claim": str(claim),
        "score": float(score) if score is not None and not (isinstance(score, float) and math.isnan(score)) else 0.0,
        "confidence": clamp01(confidence),
        "reason": str(reason),
        "evidence": dict(evidence or {}),
    }
    if facet:
        record["facet"] = facet
    if caveat:
        record["caveat"] = str(caveat)
    return record


def envelope(agent: str, insights: list[dict], metadata: Optional[Mapping[str, Any]] = None) -> dict:
    return {"agent": agent, "metadata": dict(metadata or {}), "insights": list(insights)}


def validate_envelope(payload: Mapping[str, Any]) -> list[str]:
    """Contract violations in an envelope, empty when it conforms."""
    problems: list[str] = []
    if not isinstance(payload, Mapping):
        return ["envelope is not an object"]
    if not payload.get("agent"):
        problems.append("missing agent")
    if not isinstance(payload.get("metadata", {}), Mapping):
        problems.append("metadata is not an object")
    items = payload.get("insights")
    if not isinstance(items, list):
        return problems + ["insights is not a list"]
    for position, item in enumerate(items):
        missing = [name for name in REQUIRED_INSIGHT_FIELDS if name not in item]
        if missing:
            problems.append(f"insight {position} missing {', '.join(missing)}")
            continue
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            problems.append(f"insight {position} confidence outside 0-1")
    return problems
