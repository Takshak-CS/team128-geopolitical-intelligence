"""Run the query benchmark and print (or save) its metrics.

    cd orchestrator
    ../.venv/Scripts/python -m evaluation.run                     parser metrics, offline, a few seconds
    ../.venv/Scripts/python -m evaluation.run --live              also ask the running system (scripts/run_all.ps1)
    ../.venv/Scripts/python -m evaluation.run --live --save baseline
    ../.venv/Scripts/python -m evaluation.run --compare evaluation/results/baseline_parser.json
    ../.venv/Scripts/python -m evaluation.run --ablation              what each reformulation step adds
    ../.venv/Scripts/python -m evaluation.run --steps none            the parser without reformulation

Parser metrics come from parsing each question offline with "today" pinned to the
set's reference date, so they are reproducible on any day. ``--live`` sends every
question to ``POST /ask`` and adds answer metrics: how many agents answered,
whether the facets the question needs came back, cross-agent findings,
attribution, confidence and latency.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from app import intent, reformulate
from app.config import REFORMULATION_STEPS

from . import metrics

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.json"
RESULTS = HERE / "results"

# (key, label, format) for the printed report. Answer metrics only appear with --live.
ROWS = [
    ("questions", "questions", "n"),
    ("intent_accuracy", "intent accuracy", "pct"),
    ("intent_macro_f1", "intent macro-F1", "dec"),
    ("entity_precision", "entity precision", "dec"),
    ("entity_recall", "entity recall", "dec"),
    ("entity_f1", "entity F1", "dec"),
    ("subject_accuracy", "subject accuracy", "pct"),
    ("fallback_rate", "fallback rate (lower is better)", "pct"),
    ("time_accuracy", "time slot accuracy", "pct"),
    ("sector_accuracy", "sector slot accuracy", "pct"),
    ("severity_accuracy", "severity slot accuracy", "pct"),
    ("metric_accuracy", "metric slot accuracy", "pct"),
    ("trade_query_accuracy", "trade query slot accuracy", "pct"),
    ("agent_precision", "agent selection precision", "dec"),
    ("agent_recall", "agent selection recall", "dec"),
    ("plan_exact", "plan exact match", "pct"),
    ("paraphrase_consistency", "paraphrase consistency", "pct"),
    ("rewritten_rate", "questions reformulated", "pct"),
    ("understanding_mean", "understanding confidence, mean", "dec"),
    ("understanding_right", "  ... on right plans", "dec"),
    ("understanding_wrong", "  ... on wrong plans", "dec"),
    ("understanding_brier", "understanding Brier (lower is better)", "dec"),
    ("request_errors", "request errors", "n"),
    ("answer_rate", "agent answer rate", "pct"),
    ("facet_recall", "facet recall", "dec"),
    ("facet_hit_rate", "facet hit rate", "pct"),
    ("cross_agent_yield", "cross-agent findings / question", "dec"),
    ("attribution_rate", "attribution rate", "pct"),
    ("top5_confidence", "top-5 mean confidence (descriptive)", "dec"),
    ("latency_p50_ms", "latency p50 (ms)", "ms"),
    ("latency_p95_ms", "latency p95 (ms)", "ms"),
]


# ------------------------------------------------------------------ inputs
def load_questions(path: Path = QUESTIONS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def pinned_today(day: date):
    """Parse relative dates ("yesterday", "in five years") against a fixed day."""
    original = intent._today
    intent._today = lambda: day
    try:
        yield
    finally:
        intent._today = original


def plan_for(question: str, steps: Optional[str] = None) -> dict:
    """The plan the system makes for a question. Keep this the same path POST /ask uses.

    ``steps`` selects the reformulation steps; None means the configured default.
    """
    return intent.parse(question, steps=steps).to_dict()


# --------------------------------------------------------------------- run
def evaluate_parser(data: dict, steps: Optional[str] = None) -> list[dict]:
    reference = date.fromisoformat(data["reference_date"])
    records: list[dict] = []
    with pinned_today(reference):
        for group in data["groups"]:
            gold = group["gold"]
            group_records = []
            for question in group["questions"]:
                plan = plan_for(question["text"], steps)
                predicted = metrics.plan_slots(plan)
                group_records.append({
                    "group": group["id"],
                    "split": group["split"],
                    "kind": question["kind"],
                    "question": question["text"],
                    "gold": gold,
                    "facets": group.get("facets", []),
                    "predicted": predicted,
                    "understanding": {
                        "confidence": plan.get("understanding", 1.0),
                        "read_as": plan.get("read_as"),
                        "rewrites": [f"{r['kind']}: {r['original']} -> {r['replacement']}" for r in plan.get("rewrites", [])],
                    },
                    "score": metrics.score_plan(predicted, gold),
                })
            original = next(r for r in group_records if r["kind"] == "original")
            for record in group_records:
                record["consistent"] = metrics.same_plan(record["predicted"], original["predicted"], gold)
            records += group_records
    return records


def evaluate_live(records: list[dict], base_url: str, timeout: float) -> None:
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        try:
            health = client.get("/health", timeout=20).json()
        except httpx.HTTPError as exc:
            sys.exit(f"orchestrator unreachable at {base_url}: {exc}. Start it with scripts\\run_all.ps1.")
        print(f"agents up: {health['agents_up']}/{health['agents_total']}  {health['agents']}")
        for position, record in enumerate(records, 1):
            print(f"  [{position:>3}/{len(records)}] {record['question']}", flush=True)
            try:
                response = client.post("/ask", json={"question": record["question"], "include_envelopes": False})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                record["answer_error"] = f"{type(exc).__name__}: {exc}"
                continue
            result = response.json()
            record["answer"] = metrics.answer_metrics(result, record["gold"], record["facets"])
            # The live plan should match the offline one; a mismatch means the
            # server parses differently (or "today" differs from the reference date).
            live = metrics.plan_slots(result["plan"])
            record["answer"]["live_plan_matches_offline"] = metrics.same_plan(live, record["predicted"], record["gold"])


def build_report(records: list[dict], data: dict, label: Optional[str], live: bool, steps: Optional[str] = None) -> dict:
    kinds = sorted({r["kind"] for r in records})
    return {
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": _git_state(),
        "reference_date": data["reference_date"],
        "questions_version": data["version"],
        "reformulation_steps": list(reformulate.resolve_steps(steps if steps is not None else REFORMULATION_STEPS)),
        "live": live,
        "summary": {
            "all": metrics.summarize(records),
            "dev": metrics.summarize([r for r in records if r["split"] == "dev"]),
            "test": metrics.summarize([r for r in records if r["split"] == "test"]),
        },
        "by_kind": {kind: metrics.summarize([r for r in records if r["kind"] == kind]) for kind in kinds},
        "records": records,
    }


def _git_state() -> dict:
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    return {"commit": git("rev-parse", "--short", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


# ------------------------------------------------------------------ output
def _fmt(value, kind: str) -> str:
    if value is None:
        return "-"
    if kind == "n":
        return str(int(value))
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "ms":
        return f"{value:.0f}"
    return f"{value:.3f}"


def _delta(now, before, kind: str) -> str:
    if now is None or before is None or kind == "n":
        return ""
    diff = now - before
    if kind == "pct":
        return f"{diff * 100:+.1f}"
    if kind == "ms":
        return f"{diff:+.0f}"
    return f"{diff:+.3f}"


def print_report(report: dict, compare: Optional[dict], failures: str) -> None:
    summary = report["summary"]
    before = compare["summary"] if compare else None
    header = f"{'metric':<38}{'all':>9}{'dev':>9}{'test':>9}"
    if before:
        header += f"{'chg dev':>9}{'chg test':>9}   vs {compare.get('label') or 'previous'}"
    print(f"\nQuery benchmark v{report['questions_version']}, reference date {report['reference_date']}, commit {report['git']['commit']}{' (dirty)' if report['git']['dirty'] else ''}")
    print(header)
    print("-" * len(header))
    for key, label, kind in ROWS:
        values = [summary[split].get(key) for split in ("all", "dev", "test")]
        if all(v is None for v in values):
            continue
        line = f"{label:<38}" + "".join(f"{_fmt(v, kind):>9}" for v in values)
        if before:
            line += "".join(f"{_delta(summary[s].get(key), before[s].get(key), kind):>9}" for s in ("dev", "test"))
        print(line)

    print(f"\n{'by kind':<12}{'n':>5}{'plan exact':>12}{'consistent':>12}{'fallback':>10}")
    for kind, values in report["by_kind"].items():
        print(f"{kind:<12}{values['questions']:>5}{_fmt(values['plan_exact'], 'pct'):>12}{_fmt(values['paraphrase_consistency'], 'pct'):>12}{_fmt(values['fallback_rate'], 'pct'):>10}")

    if failures == "none":
        return
    shown = [r for r in report["records"] if not r["score"]["plan_exact"] and (failures == "all" or r["split"] == "dev")]
    hidden = sum(1 for r in report["records"] if not r["score"]["plan_exact"] and r["split"] == "test") if failures == "dev" else 0
    print(f"\nPlans that miss the gold ({len(shown)} shown{f', {hidden} test-split hidden' if hidden else ''}):")
    for record in shown:
        wrong = [slot for slot, ok in record["score"]["slots"].items() if not ok]
        got = {slot: record["predicted"][slot] for slot in wrong}
        if "time" in got:
            got["time"] = {k: v for k, v in got["time"].items() if v is not None}
        print(f"  [{record['group']}/{record['kind']}] {record['question']!r}\n      wrong: {', '.join(wrong)}  got: {json.dumps(got)}")


def print_ablation(data: dict) -> None:
    """What each reformulation step contributes: on its own, and when left out."""
    configs = [("none (parser only)", "none")]
    configs += [(f"only {step}", step) for step in reformulate.STEPS]
    configs += [(f"all but {step}", ",".join(s for s in reformulate.STEPS if s != step)) for step in reformulate.STEPS]
    configs += [("all steps", "all")]

    header = f"{'reformulation':<22}{'exact dev':>11}{'exact test':>11}{'consist dev':>12}{'consist test':>13}{'fallback':>10}{'Brier':>8}"
    print(f"\nAblation, reference date {data['reference_date']} (fallback and Brier over all questions)")
    print(header)
    print("-" * len(header))
    for label, steps in configs:
        records = evaluate_parser(data, steps)
        dev = metrics.summarize([r for r in records if r["split"] == "dev"])
        test = metrics.summarize([r for r in records if r["split"] == "test"])
        every = metrics.summarize(records)
        print(f"{label:<22}{_fmt(dev['plan_exact'], 'pct'):>11}{_fmt(test['plan_exact'], 'pct'):>11}"
              f"{_fmt(dev['paraphrase_consistency'], 'pct'):>12}{_fmt(test['paraphrase_consistency'], 'pct'):>13}"
              f"{_fmt(every['fallback_rate'], 'pct'):>10}{_fmt(every.get('understanding_brier'), 'dec'):>8}")


# -------------------------------------------------------------------- main
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--live", action="store_true", help="also send every question to POST /ask")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds per /ask request")
    parser.add_argument("--save", metavar="LABEL", help="write the full report to evaluation/results/LABEL.json")
    parser.add_argument("--compare", type=Path, metavar="REPORT", help="show the change against a saved report")
    parser.add_argument("--failures", choices=("dev", "all", "none"), default="dev", help="which missed plans to list (default: dev only, so the test split stays held out)")
    parser.add_argument("--steps", help="reformulation steps for the offline parse: all, none, or e.g. aliases,spelling (default: REFORMULATION_STEPS)")
    parser.add_argument("--ablation", action="store_true", help="score every combination of reformulation steps offline, then exit")
    args = parser.parse_args(argv)

    data = load_questions(args.questions)
    if args.ablation:
        print_ablation(data)
        return 0
    records = evaluate_parser(data, args.steps)
    if args.live:
        evaluate_live(records, args.base_url, args.timeout)
    report = build_report(records, data, args.save, args.live, args.steps)
    compare = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    print_report(report, compare, args.failures)

    if args.save:
        RESULTS.mkdir(exist_ok=True)
        path = RESULTS / f"{args.save}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
