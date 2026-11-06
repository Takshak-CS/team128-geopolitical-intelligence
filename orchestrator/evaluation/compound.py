"""Benchmark for query decomposition (app/decompose.py).

    cd orchestrator
    ../.venv/Scripts/python -m evaluation.compound            dev and test, with and without decomposition
    ../.venv/Scripts/python -m evaluation.compound --failures show the dev questions it gets wrong

Metrics, per split:
    part recall      share of gold parts the system answers, matched on intent and countries
    all parts        share of questions where every gold part is answered and nothing extra
    over-split       share of single-part controls the system wrongly splits (lower is better)

"without" is the system with decomposition off: one plan per question, which
is how it worked before. The 90 single questions in questions.json are checked
for over-splitting too.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from app import decompose

from .run import QUESTIONS, load_questions, pinned_today

COMPOUND = Path(__file__).resolve().parent / "compound.json"


def _key(intent: str, countries) -> tuple:
    return (intent, tuple(countries))


def score(question: dict, enabled: bool) -> dict:
    result = decompose.decompose(question["text"], enabled=enabled)
    got = [_key(p.intent, p.iso3s) for p in result.plans]
    gold = [_key(g["intent"], g["countries"]) for g in question["gold"]]
    hits = sum(1 for g in gold if g in got)
    return {"text": question["text"], "split": question["split"], "gold": gold, "got": got,
            "hits": hits, "exact": sorted(got) == sorted(gold), "control": len(gold) == 1, "split_wrongly": len(gold) == 1 and len(got) > 1}


def summarize(records: list[dict]) -> dict:
    compound = [r for r in records if not r["control"]]
    controls = [r for r in records if r["control"]]
    return {
        "questions": len(records),
        "part_recall": sum(r["hits"] for r in compound) / max(1, sum(len(r["gold"]) for r in compound)),
        "all_parts": sum(r["exact"] for r in records) / max(1, len(records)),
        "over_split": sum(r["split_wrongly"] for r in controls) / max(1, len(controls)),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--failures", action="store_true", help="list the dev questions that are not answered exactly")
    args = parser.parse_args(argv)

    data = json.loads(COMPOUND.read_text(encoding="utf-8"))
    with pinned_today(date.fromisoformat(data["reference_date"])):
        runs = {label: [score(q, enabled) for q in data["questions"]] for label, enabled in (("without", False), ("with", True))}
        singles = [q["text"] for g in load_questions(QUESTIONS)["groups"] for q in g["questions"]]
        over = sum(decompose.decompose(text).compound for text in singles)

    header = f"{'decomposition':<15}{'split':<7}{'n':>4}{'part recall':>13}{'all parts':>11}{'over-split':>12}"
    print(header)
    print("-" * len(header))
    for label, records in runs.items():
        for split in ("dev", "test"):
            s = summarize([r for r in records if r["split"] == split])
            print(f"{label:<15}{split:<7}{s['questions']:>4}{s['part_recall']:>13.1%}{s['all_parts']:>11.1%}{s['over_split']:>12.1%}")
    print(f"\nsingle questions from questions.json split by mistake: {over}/{len(singles)}")

    if args.failures:
        for r in runs["with"]:
            if r["split"] == "dev" and not r["exact"]:
                print(f"\n  {r['text']}\n    gold {r['gold']}\n    got  {r['got']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
