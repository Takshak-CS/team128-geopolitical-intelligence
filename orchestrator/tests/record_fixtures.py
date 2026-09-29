"""Re-record the agent fixtures from the live services.

    cd orchestrator
    ../.venv/Scripts/python tests/record_fixtures.py
    ../.venv/Scripts/python tests/record_fixtures.py --agents event_summarization
    ../.venv/Scripts/python tests/record_fixtures.py --agents event_summarization --keep-recorded

Needs the agents being recorded running with their data (scripts/run_all.ps1).
``--agents`` re-records only those agents' responses and keeps every other
recording as it is, so one module can be refreshed on a machine that lacks the
other modules' data. ``--keep-recorded`` also keeps each response already
recorded for those agents and records only the requests that are new, so live
answers that drift between runs (an article site that blocks one fetch and
serves the next) do not change existing fixtures. Events questions are pinned to
one GDELT day so the recording is reproducible.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import Orchestrator  # noqa: E402
from tests.replay import FIXTURES, RecordingTransport  # noqa: E402

EVENTS_DAY = "20260922"
# A day on which China is not among India's most active counterparts.
PAIR_ABSENT_DAY = "20260928"
SCENARIOS = [
    ("How exposed is India right now?", {"date": EVENTS_DAY}),
    ("India and China relations", {"date": EVENTS_DAY}),
    ("India and China relations", {"date": PAIR_ABSENT_DAY}),
    ("What if China stops exporting electronics?", {"date": EVENTS_DAY}),
    ("Which countries are most dependent on trade?", {}),
    ("Forecast Brazil exports to 2030", {}),
    ("Which bloc is Vietnam in?", {}),
    ("What is happening in Iran?", {"date": EVENTS_DAY}),
    ("Compare the US and Russia in 2015", {}),
]


async def main(agents: list[str], keep_recorded: bool = False) -> None:
    transport = RecordingTransport()
    orchestrator = Orchestrator(client=httpx.AsyncClient(transport=transport))
    for question, overrides in SCENARIOS:
        result = await orchestrator.ask(question, overrides, include_envelopes=False)
        statuses = {name: agent["status"] for name, agent in result["agents"].items()}
        print(f"{question!r}: {statuses}")
    await orchestrator.close()
    records = transport.records
    if agents:
        # Keys start with the agent name (tests/replay.py request_key).
        old = json.loads(FIXTURES.read_text(encoding="utf-8"))
        fresh = {key: value for key, value in records.items() if key.split(" ", 1)[0] in agents}
        if keep_recorded:
            fresh = {key: old.get(key, value) for key, value in fresh.items()}
            print(f"{sum(key not in old for key in fresh)} new responses recorded; {sum(key in old for key in fresh)} kept as recorded")
        kept = {key: value for key, value in old.items() if key.split(" ", 1)[0] not in agents}
        records = {**kept, **fresh}
        print(f"re-recorded {len(fresh)} responses for {', '.join(agents)}; kept {len(kept)} others")
    FIXTURES.parent.mkdir(exist_ok=True)
    FIXTURES.write_text(json.dumps(records, indent=1, sort_keys=True), encoding="utf-8")
    print(f"recorded {len(records)} responses -> {FIXTURES} ({FIXTURES.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record agent responses for the replay tests.")
    parser.add_argument("--agents", nargs="+", default=[], help="re-record only these agents and keep the other recordings")
    parser.add_argument("--keep-recorded", action="store_true", help="with --agents: keep responses already recorded, record only new requests")
    args = parser.parse_args()
    if args.keep_recorded and not args.agents:
        parser.error("--keep-recorded needs --agents")
    asyncio.run(main(args.agents, args.keep_recorded))
