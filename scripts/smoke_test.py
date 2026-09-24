"""End-to-end check against running services.

    python scripts/smoke_test.py                  default case-study questions
    python scripts/smoke_test.py "question" ...   your own

Prints, per question: intent, which agents answered, divergences and
corroborations found, the headline, and latency. Exits non-zero if the
orchestrator is down or a question returns no findings at all.
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
CASES = [
    "How exposed is India right now?",
    "India and China relations",
    "What if China stops exporting electronics?",
    "Which countries are most dependent on trade?",
    "Forecast Brazil exports to 2030",
    "Which bloc is Vietnam in?",
    "What is happening in Iran?",
]


def call(path: str, body: dict | None = None, timeout: float = 300) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def main() -> int:
    try:
        health = call("/health", timeout=20)
    except OSError as exc:
        print(f"orchestrator unreachable at {BASE}: {exc}")
        return 2
    print(f"agents up: {health['agents_up']}/{health['agents_total']}  {health['agents']}\n")

    failures = 0
    for question in sys.argv[1:] or CASES:
        result = call("/ask", {"question": question, "include_envelopes": False})
        stats = result["fused"]["stats"]
        statuses = {name: agent["status"] for name, agent in result["agents"].items()}
        print(f"Q: {question}")
        print(f"   intent={result['plan']['intent']}  countries={[e['iso3'] for e in result['plan']['entities']]}  {result['latency_ms']:.0f} ms")
        print(f"   agents: {statuses}")
        print(f"   {stats['divergences']} divergences, {stats['corroborations']} corroborations, {stats['insights_after_dedupe']} insights")
        print(f"   -> {result['briefing']['headline']}")
        for line in result["briefing"]["summary"][:2]:
            print(f"      - {line[:180]}")
        print()
        if not result["fused"]["findings"]:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
