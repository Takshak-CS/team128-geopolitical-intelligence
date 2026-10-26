from datetime import date

import pytest

from app import countries, intent
from evaluation import metrics, run

DATA = run.load_questions()
KINDS = {"original", "reworded", "alias", "typo", "casual", "numeric"}
# Facets the adapters emit (docs/CONTRACT.md, "Facets by agent").
FACETS = {
    "influence", "influence_trend", "influence_outlook", "influence_drivers", "influence_peers", "bilateral_influence",
    "diplomatic_alignment", "diplomatic_partners", "conflict_exposure", "conflict_outlook", "bilateral_diplomacy", "diplomatic_blocs", "issue_stance",
    "trade_exposure", "trade_alignment", "trade_dependence", "supply_fragility", "shock_impact", "trade_outlook", "bilateral_trade_bloc", "bilateral_trade_dependence",
    "event_activity", "event_partners", "event_themes", "event_domestic_split", "event_headline", "bilateral_events", "bilateral_headlines", "relationship_baseline",
}


# ------------------------------------------------------------ question set
def test_question_set_is_well_formed():
    ids = [group["id"] for group in DATA["groups"]]
    assert len(ids) == len(set(ids))
    texts = [q["text"] for group in DATA["groups"] for q in group["questions"]]
    assert len(texts) == len(set(texts)), "a question appears twice"
    date.fromisoformat(DATA["reference_date"])
    for group in DATA["groups"]:
        gold = group["gold"]
        assert group["split"] in ("dev", "test"), group["id"]
        assert set(gold) <= set(metrics.SLOTS), group["id"]
        assert gold["intent"] in intent.INTENTS, group["id"]
        assert all(code in countries.COUNTRIES for code in gold["countries"]), group["id"]
        assert set(gold["agents"]) <= set(intent.ALL_AGENTS), group["id"]
        assert set(gold["time"]) <= {"mode", "year", "date", "horizon_year"}, group["id"]
        assert group["facets"] and set(group["facets"]) <= FACETS, group["id"]
        kinds = [q["kind"] for q in group["questions"]]
        assert kinds.count("original") == 1, group["id"]
        assert set(kinds) <= KINDS, group["id"]


def test_both_splits_are_used():
    splits = {group["split"] for group in DATA["groups"]}
    assert splits == {"dev", "test"}


def test_every_original_question_parses_to_its_gold_plan():
    # The originals are the questions the system was built around; a change
    # that breaks one of them is a regression, whatever it does for rewordings.
    records = run.evaluate_parser(DATA)
    missed = [(r["question"], r["score"]["slots"]) for r in records if r["kind"] == "original" and not r["score"]["plan_exact"]]
    assert missed == []


def test_parser_runs_against_the_reference_date():
    original = intent._today
    records = {r["question"]: r for r in run.evaluate_parser(DATA)}
    assert records["What happened in Ukraine yesterday?"]["predicted"]["time"]["date"] == "20261025"
    assert intent._today is original  # the pin is undone afterwards


# ----------------------------------------------------------------- metrics
def plan(intent_name="country_profile", iso3s=(), **time):
    return {"intent": intent_name, "entities": [{"iso3": c} for c in iso3s], "time": time or {"mode": "latest"}, "sector": "all", "severity": None, "metric": "exports", "trade_query": None, "agents": ["trade_intelligence"]}


def test_prf_handles_empty_denominators():
    assert metrics.prf(0, 0, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    scores = metrics.prf(3, 1, 2)
    assert scores["precision"] == pytest.approx(0.75)
    assert scores["recall"] == pytest.approx(0.6)
    assert scores["f1"] == pytest.approx(2 * 0.75 * 0.6 / 1.35)


def test_macro_f1_weights_each_intent_equally():
    pairs = [("events", "events"), ("ranking", "ranking"), ("ranking", "ranking"), ("ranking", "events")]
    # events: P 1/2, R 1 -> 2/3; ranking: P 1, R 2/3 -> 0.8
    assert metrics.macro_f1(pairs) == pytest.approx((2 / 3 + 0.8) / 2)


def test_bilateral_subject_ignores_order_but_a_profile_does_not():
    assert metrics.subject_correct(["CHN", "IND"], ["IND", "CHN"], bilateral=True)
    assert not metrics.subject_correct(["CHN", "VNM"], ["VNM", "CHN"], bilateral=False)
    assert metrics.subject_correct([], [], bilateral=False)
    assert not metrics.subject_correct(["IND"], [], bilateral=False)


def test_time_is_scored_only_on_the_keys_the_gold_sets():
    predicted = metrics.plan_slots(plan(mode="date", date="20261025", year=2026))
    assert metrics.slot_correct("time", predicted["time"], {"mode": "date", "date": "20261025"})
    assert not metrics.slot_correct("time", predicted["time"], {"mode": "latest"})


def test_score_plan_flags_a_fallback_to_the_global_overview():
    gold = {"intent": "country_profile", "countries": ["IND"], "agents": ["trade_intelligence"]}
    score = metrics.score_plan(metrics.plan_slots(plan("ranking")), gold)
    assert score["fallback"] and not score["subject"] and not score["plan_exact"]
    assert score["slots"] == {"intent": False, "countries": False, "agents": True}


def test_same_plan_compares_only_gold_slots():
    gold = {"intent": "country_profile", "countries": ["IND"]}
    a = metrics.plan_slots(plan(iso3s=["IND"]))
    b = dict(metrics.plan_slots(plan(iso3s=["IND"])), sector="energy")
    assert metrics.same_plan(a, b, gold)
    assert not metrics.same_plan(a, metrics.plan_slots(plan(iso3s=["CHN"])), gold)


def test_two_plans_without_a_severity_are_the_same():
    gold = {"intent": "shock", "countries": ["CHN"], "severity": 1.0}
    a = metrics.plan_slots(plan("ranking"))
    assert metrics.same_plan(a, dict(a), gold)
    assert not metrics.same_plan(a, dict(a, severity=1.0), gold)
    assert not metrics.score_plan(a, gold)["slots"]["severity"]


def test_attribution_counts_cited_claim_lines_only():
    markdown = "\n".join([
        "## India: fused briefing",
        "",
        "- Agents agree: India trades in the China bloc. [Trade+Policy Stance, conf 0.97]",
        "- An uncited sentence.",
        "",
        "### Trade",
        "- India risk rank 12. [Trade, conf 0.88]",
        "  - _Caveat: something_",
        "### Caveats",
        "- A page-level caveat.",
    ])
    assert metrics.attribution(markdown) == (2, 3)


def test_percentile_is_nearest_rank():
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert metrics.percentile(values, 50) == 50
    assert metrics.percentile(values, 95) == 100
    assert metrics.percentile([], 50) is None


def test_answer_metrics_reads_facets_for_the_question_country():
    result = {
        "agents": {"trade_intelligence": {"status": "ok", "insight_count": 2}, "event_summarization": {"status": "timeout", "insight_count": 0}},
        "fused": {"findings": [
            {"kind": "divergence", "entity_iso3": "IND", "facets": ["trade_alignment", "diplomatic_alignment"], "confidence": 0.6},
            {"kind": "insight", "entity_iso3": "CHN", "facets": ["event_activity"], "confidence": 0.4},
        ]},
        "briefing": {"markdown": "- x [Trade, conf 0.60]", "headline": "India"},
        "latency_ms": 812.0,
    }
    answer = metrics.answer_metrics(result, {"countries": ["IND"]}, ["trade_alignment", "event_activity"])
    assert answer["answer_rate"] == 0.5
    assert answer["facets_found"] == ["trade_alignment"]  # event_activity is about China, not India
    assert answer["facet_recall"] == 0.5
    assert answer["cross_agent_findings"] == 1
    assert answer["top5_confidence"] == pytest.approx(0.5)
    assert (answer["cited_lines"], answer["claim_lines"]) == (1, 1)
