"""Scoring for the query benchmark.

Pure functions over plain dicts: a plan as ``QueryPlan.to_dict()`` returns it,
an ``/ask`` response, and the gold labels from ``questions.json``. The runner
(``run.py``) does the I/O. Every metric is defined in docs/EVALUATION.md.

A gold label names only the slots that matter for its question, so a slot is
scored only where the gold sets it. "Plan exact" means every gold slot is right.
"""

from __future__ import annotations

import math
import re
from statistics import mean
from typing import Iterable, Optional

SLOTS = ("intent", "countries", "time", "sector", "severity", "metric", "trade_query", "agents")
ANSWERED = ("ok", "partial")

# A briefing line that cites its source ends like "[Trade+Policy Stance, conf 0.97]".
_CITATION = re.compile(r"\[[^\[\]]+, conf \d\.\d\d\]$")
_NO_ANSWER = "No agent returned usable insights for this question."


# ------------------------------------------------------------------- plans
def plan_slots(plan: dict) -> dict:
    """The slots of a query plan that the benchmark scores."""
    time = plan.get("time") or {}
    return {
        "intent": plan.get("intent"),
        "countries": [entity["iso3"] for entity in plan.get("entities") or []],
        "time": {key: time.get(key) for key in ("mode", "year", "date", "horizon_year")},
        "sector": plan.get("sector"),
        "severity": plan.get("severity"),
        "metric": plan.get("metric"),
        "trade_query": plan.get("trade_query"),
        "agents": list(plan.get("agents") or []),
    }


def subject_correct(predicted: list[str], gold: list[str], bilateral: bool) -> bool:
    """Did the plan pick the country (or, for a bilateral question, the pair) the question is about?"""
    if not gold:
        return not predicted
    if bilateral:
        return set(predicted[:2]) == set(gold[:2])
    return predicted[:1] == gold[:1]


def slot_correct(slot: str, predicted, gold, bilateral: bool = False) -> bool:
    if slot == "countries":
        return subject_correct(predicted, gold, bilateral) and set(predicted) == set(gold)
    if slot == "time":
        return all((predicted or {}).get(key) == value for key, value in gold.items())
    if slot == "severity":
        if predicted is None or gold is None:
            return predicted is gold
        return math.isclose(float(predicted), float(gold), abs_tol=1e-6)
    if slot == "agents":
        return set(predicted) == set(gold)
    return predicted == gold


def score_plan(predicted: dict, gold: dict) -> dict:
    """Per-slot correctness of one predicted plan against its gold label."""
    bilateral = gold.get("intent") == "bilateral"
    slots = {slot: slot_correct(slot, predicted[slot], gold[slot], bilateral) for slot in SLOTS if slot in gold}
    gold_countries = gold.get("countries", [])
    return {
        "slots": slots,
        "plan_exact": all(slots.values()),
        "subject": subject_correct(predicted["countries"], gold_countries, bilateral),
        # The question names a country but the plan found none: it will be
        # answered with a global overview.
        "fallback": bool(gold_countries) and not predicted["countries"],
    }


def same_plan(a: dict, b: dict, gold: dict) -> bool:
    """Do two predicted plans agree on every slot the gold label scores?

    Used for paraphrase consistency: a rewording should produce the same plan
    as its original, whether or not that plan is right.
    """
    bilateral = gold.get("intent") == "bilateral"
    for slot in SLOTS:
        if slot not in gold:
            continue
        if slot == "time":
            if any(a["time"].get(key) != b["time"].get(key) for key in gold["time"]):
                return False
        elif not slot_correct(slot, a[slot], b[slot], bilateral):
            return False
    return True


# ------------------------------------------------------------- set metrics
def prf(tp: int, fp: int, fn: int) -> dict:
    """Precision, recall and F1, with 0 where a denominator is 0."""
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def set_counts(predicted: Iterable[str], gold: Iterable[str]) -> tuple[int, int, int]:
    p, g = set(predicted), set(gold)
    return len(p & g), len(p - g), len(g - p)


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    """Macro-averaged F1 over the labels in (gold, predicted) pairs."""
    labels = sorted({label for pair in pairs for label in pair})
    if not labels:
        return 0.0
    scores = []
    for label in labels:
        tp = sum(1 for g, p in pairs if g == label and p == label)
        fp = sum(1 for g, p in pairs if g != label and p == label)
        fn = sum(1 for g, p in pairs if g == label and p != label)
        scores.append(prf(tp, fp, fn)["f1"])
    return mean(scores)


def percentile(values: list[float], q: float) -> Optional[float]:
    """Nearest-rank percentile, q in 0-100."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


# ----------------------------------------------------------------- answers
def attribution(markdown: str) -> tuple[int, int]:
    """(claim lines that cite an agent and confidence, all claim lines) in a briefing."""
    cited = total = 0
    section = ""
    for line in markdown.splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
            continue
        if not line.startswith("- ") or section in ("Caveats", "Time alignment"):
            continue
        text = line[2:].strip()
        if text == _NO_ANSWER:
            continue
        total += 1
        cited += bool(_CITATION.search(text))
    return cited, total


def answer_metrics(result: dict, gold: dict, facets: list[str]) -> dict:
    """What one ``/ask`` response delivered for a question."""
    agents = result.get("agents") or {}
    answered = [name for name, info in agents.items() if info.get("status") in ANSWERED and info.get("insight_count")]
    findings = (result.get("fused") or {}).get("findings") or []
    gold_countries = set(gold.get("countries") or [])

    # Facets present in findings about the question's countries (any finding
    # for a question that names none).
    present = {
        facet
        for finding in findings
        if not gold_countries or finding.get("entity_iso3") in gold_countries
        for facet in finding.get("facets") or []
    }
    cited, lines = attribution((result.get("briefing") or {}).get("markdown", ""))
    shown = findings[:5]
    return {
        "agents_asked": len(agents),
        "agents_answered": len(answered),
        "agent_status": {name: info.get("status") for name, info in agents.items()},
        "answer_rate": len(answered) / len(agents) if agents else 0.0,
        "facets_found": sorted(set(facets) & present),
        "facet_recall": len(set(facets) & present) / len(facets) if facets else None,
        "cross_agent_findings": sum(1 for finding in findings if finding.get("kind") != "insight"),
        "findings": len(findings),
        "top5_confidence": mean(float(f.get("confidence", 0.0)) for f in shown) if shown else None,
        "cited_lines": cited,
        "claim_lines": lines,
        "latency_ms": result.get("latency_ms"),
        "headline": (result.get("briefing") or {}).get("headline"),
    }


# --------------------------------------------------------------- summaries
def _rate(flags: list[bool]) -> Optional[float]:
    return sum(flags) / len(flags) if flags else None


def _mean(values: list[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return mean(present) if present else None


def summarize(records: list[dict]) -> dict:
    """Aggregate metrics over a list of per-question records (see run.py)."""
    if not records:
        return {"questions": 0}
    golds = [r["gold"] for r in records]
    preds = [r["predicted"] for r in records]
    scores = [r["score"] for r in records]

    tp = fp = fn = 0
    for g, p in zip(golds, preds):
        a, b, c = set_counts(p["countries"], g.get("countries", []))
        tp, fp, fn = tp + a, fp + b, fn + c
    entity = prf(tp, fp, fn)

    atp = afp = afn = 0
    for g, p in zip(golds, preds):
        if "agents" in g:
            a, b, c = set_counts(p["agents"], g["agents"])
            atp, afp, afn = atp + a, afp + b, afn + c
    agents = prf(atp, afp, afn)

    summary = {
        "questions": len(records),
        "intent_accuracy": _rate([s["slots"]["intent"] for s in scores]),
        "intent_macro_f1": macro_f1([(g["intent"], p["intent"]) for g, p in zip(golds, preds)]),
        "entity_precision": entity["precision"],
        "entity_recall": entity["recall"],
        "entity_f1": entity["f1"],
        "subject_accuracy": _rate([s["subject"] for s in scores]),
        "fallback_rate": _rate([s["fallback"] for g, s in zip(golds, scores) if g.get("countries")]),
    }
    for slot in ("time", "sector", "severity", "metric", "trade_query"):
        summary[f"{slot}_accuracy"] = _rate([s["slots"][slot] for s in scores if slot in s["slots"]])
    summary["agent_precision"] = agents["precision"]
    summary["agent_recall"] = agents["recall"]
    summary["plan_exact"] = _rate([s["plan_exact"] for s in scores])
    summary["paraphrase_consistency"] = _rate([r["consistent"] for r in records if r["kind"] != "original"])

    # Understanding confidence (intent.parse) against whether the plan was right.
    # A useful confidence is high on right plans, low on wrong ones, and has a
    # low Brier score: mean (confidence - right)^2, 0 is perfect.
    understood = [(r["understanding"]["confidence"], r["score"]["plan_exact"]) for r in records if r.get("understanding")]
    if understood:
        summary["rewritten_rate"] = _rate([bool(r["understanding"]["read_as"]) for r in records if r.get("understanding")])
        summary["understanding_mean"] = mean(c for c, _ in understood)
        summary["understanding_right"] = _mean([c for c, ok in understood if ok])
        summary["understanding_wrong"] = _mean([c for c, ok in understood if not ok])
        summary["understanding_brier"] = mean((c - ok) ** 2 for c, ok in understood)

    answers = [r["answer"] for r in records if r.get("answer")]
    if answers:
        latencies = [a["latency_ms"] for a in answers if a.get("latency_ms") is not None]
        cited = sum(a["cited_lines"] for a in answers)
        lines = sum(a["claim_lines"] for a in answers)
        summary.update({
            "answered_questions": len(answers),
            "request_errors": sum(1 for r in records if r.get("answer_error")),
            "answer_rate": _mean([a["answer_rate"] for a in answers]),
            "facet_recall": _mean([a["facet_recall"] for a in answers]),
            "facet_hit_rate": _rate([bool(a["facet_recall"]) for a in answers if a["facet_recall"] is not None]),
            "cross_agent_yield": _mean([a["cross_agent_findings"] for a in answers]),
            "attribution_rate": cited / lines if lines else None,
            "top5_confidence": _mean([a["top5_confidence"] for a in answers]),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        })
    return summary
