"""Re-record the agent fixtures from the live services.

    cd orchestrator
    ../.venv/Scripts/python tests/record_fixtures.py

Needs all four agents running (scripts/run_all.ps1). Events questions are pinned
to one GDELT day so the recording is reproducible.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import Orchestrator  # noqa: E402
from tests.replay import FIXTURES, RecordingTransport  # noqa: E402

EVENTS_DAY = "20260922"
SCENARIOS = [
    ("How exposed is India right now?", {"date": EVENTS_DAY}),
    ("India and China relations", {"date": EVENTS_DAY}),
    ("What if China stops exporting electronics?", {"date": EVENTS_DAY}),
    ("Which countries are most dependent on trade?", {}),
    ("Forecast Brazil exports to 2030", {}),
    ("Which bloc is Vietnam in?", {}),
    ("What is happening in Iran?", {"date": EVENTS_DAY}),
    ("Compare the US and Russia in 2015", {}),
]


async def main() -> None:
    transport = RecordingTransport()
    orchestrator = Orchestrator(client=httpx.AsyncClient(transport=transport))
    for question, overrides in SCENARIOS:
        result = await orchestrator.ask(question, overrides, include_envelopes=False)
        statuses = {name: agent["status"] for name, agent in result["agents"].items()}
        print(f"{question!r}: {statuses}")
    await orchestrator.close()
    FIXTURES.parent.mkdir(exist_ok=True)
    FIXTURES.write_text(json.dumps(transport.records, indent=1, sort_keys=True), encoding="utf-8")
    print(f"recorded {len(transport.records)} responses -> {FIXTURES} ({FIXTURES.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    asyncio.run(main())
