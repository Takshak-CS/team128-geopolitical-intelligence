import pytest

from app import fusion, intent
from app.agents.base import AgentResult
from app.contract import envelope, insight


def result(agent, insights, context=None, status="ok"):
    return AgentResult(agent=agent, status=status, envelope=envelope(agent, insights, {}), context=context or {})


def trade_bloc(x, anchor, conf=0.9):
    return insight(x, f"{x} in {anchor} bloc", 0.68, conf, "r", {"bloc_anchor_iso3": anchor, "internal_trade_share": 0.68, "bloc_size": 125}, facet="trade_alignment")


def policy_bloc(x, bloc, provenance="vote_model", conf=0.7):
    return insight(x, f"{x} in {bloc}", 0.3, conf, "r", {"bloc": bloc, "provenance": provenance}, facet="diplomatic_alignment")


def kinds(fused):
    return [(f["kind"], f["title"]) for f in fused["findings"] if f["kind"] != "insight"]


def test_divergence_when_trade_bloc_anchor_votes_elsewhere():
    plan = intent.parse("How exposed is Vietnam?")
    fused = fusion.fuse(plan, {
        "trade_intelligence": result("trade_intelligence", [trade_bloc("VNM", "CHN")]),
        "policy_stance": result("policy_stance", [policy_bloc("VNM", "Non-Aligned")], {"bloc_by_iso3": {"VNM": "Non-Aligned", "CHN": "China-Centered Bloc"}}),
    })
    top = fused["findings"][0]
    assert top["kind"] == "divergence"
    assert "China-anchored bloc" in top["claim"] and "Non-Aligned" in top["claim"]
    assert top["confidence"] == pytest.approx(0.7)  # min of the two sides
    assert top["caveat"] is None
    assert fused["stats"]["divergences"] == 1


def test_corroboration_uses_noisy_or():
    plan = intent.parse("How exposed is Cambodia?")
    fused = fusion.fuse(plan, {
        "trade_intelligence": result("trade_intelligence", [trade_bloc("KHM", "CHN", conf=0.9)]),
        "policy_stance": result("policy_stance", [policy_bloc("KHM", "China-Centered Bloc", conf=0.7)], {"bloc_by_iso3": {"KHM": "China-Centered Bloc", "CHN": "China-Centered Bloc"}}),
    })
    top = fused["findings"][0]
    assert top["kind"] == "corroboration"
    assert top["confidence"] == pytest.approx(1 - 0.1 * 0.3)


def test_anchor_or_override_bloc_is_caveated_and_ranked_lower():
    plan = intent.parse("How exposed is India?")
    fused = fusion.fuse(plan, {
        "trade_intelligence": result("trade_intelligence", [trade_bloc("IND", "CHN")]),
        "policy_stance": result("policy_stance", [policy_bloc("IND", "Non-Aligned", provenance="manual_override", conf=0.25)], {"bloc_by_iso3": {"IND": "Non-Aligned", "CHN": "China-Centered Bloc"}}),
    })
    top = fused["findings"][0]
    assert top["kind"] == "divergence"
    assert "hard-coded override" in top["caveat"]
    assert top["confidence"] == pytest.approx(0.25)


def test_country_anchoring_its_own_bloc_is_not_a_divergence():
    plan = intent.parse("How exposed is China?")
    fused = fusion.fuse(plan, {
        "trade_intelligence": result("trade_intelligence", [trade_bloc("CHN", "CHN")]),
        "policy_stance": result("policy_stance", [policy_bloc("CHN", "China-Centered Bloc", provenance="anchor", conf=0.3)], {"bloc_by_iso3": {"CHN": "China-Centered Bloc"}}),
    })
    assert kinds(fused) == [("cross_agent", "Anchors its own trading bloc")]


def test_critical_partner_and_sector_supplier_across_bloc_line():
    plan = intent.parse("How exposed is India?")
    lev = insight("IND", "lev", 8.0, 0.92, "r", {"most_critical_partner_iso3": "CHN", "critical_partner_dependence": 0.12}, facet="trade_dependence")
    energy = insight("IND", "energy", 0.29, 0.95, "r", {"sector": "energy", "top_supplier_iso3": "RUS", "top_supplier_share": 0.27}, facet="supply_fragility")
    agri = insight("IND", "agri", 0.07, 0.95, "r", {"sector": "agriculture", "top_supplier_iso3": "IDN", "top_supplier_share": 0.16}, facet="supply_fragility")
    blocs = {"IND": "Non-Aligned", "CHN": "China-Centered Bloc", "RUS": "Russia+Allies", "IDN": "Non-Aligned"}
    fused = fusion.fuse(plan, {
        "trade_intelligence": result("trade_intelligence", [lev, energy, agri]),
        "policy_stance": result("policy_stance", [policy_bloc("IND", "Non-Aligned")], {"bloc_by_iso3": blocs}),
    })
    titles = [t for _, t in kinds(fused)]
    assert "Critical trade partner across the bloc line" in titles
    assert "Energy supply depends on another bloc" in titles
    assert not any("Agriculture" in t for t in titles)  # 16% is below the 25% threshold


def test_momentum_rule():
    plan = intent.parse("Forecast India exports")
    trade = insight("IND", "exports up", 0.07, 0.9, "r", {"trend": "increasing", "metric": "exports"}, facet="trade_outlook")
    falling = insight("IND", "sp down", -0.03, 0.7, "r", {"direction": "falling"}, facet="influence_outlook")
    fused = fusion.fuse(plan, {"trade_intelligence": result("trade_intelligence", [trade]), "soft_power": result("soft_power", [falling])})
    assert kinds(fused) == [("divergence", "Economic and soft-power momentum diverge")]


def test_event_friction_with_critical_partner_and_baseline():
    plan = intent.parse("How exposed is India?")
    lev = insight("IND", "lev", 8.0, 0.92, "r", {"most_critical_partner_iso3": "CHN", "critical_partner_dependence": 0.12}, facet="trade_dependence")
    partners = insight("IND", "partners", 0.1, 0.6, "r", {}, facet="event_partners")
    baseline = insight("IND", "baseline", 0.2, 0.75, "r", {"pair": ["IND", "CHN"], "avg_10yr": 0.2, "baseline_label": "moderately cooperative"}, facet="relationship_baseline")
    events = result("event_summarization", [partners, baseline], {"partners": [{"iso3": "CHN", "count": 12, "avg_goldstein": -3.1}]})
    fused = fusion.fuse(plan, {"trade_intelligence": result("trade_intelligence", [lev]), "event_summarization": events})
    titles = [t for _, t in kinds(fused)]
    assert "Friction with a critical trade partner" in titles
    assert "Today is out of character for the relationship" in titles


def test_bilateral_rules():
    plan = intent.parse("India and China relations")
    same = insight("IND", "same bloc", 1.0, 0.85, "r", {"pair": ["IND", "CHN"], "same_bloc": True}, facet="bilateral_trade_bloc")
    dep = insight("IND", "dep", 0.2, 0.9, "r", {"pair": ["IND", "CHN"], "exposed_dependence": 0.12}, facet="bilateral_trade_dependence")
    dip = insight("IND", "dip", 0.4, 0.7, "r", {"pair": ["IND", "CHN"], "metrics": {"same_bloc": False, "vote_match_rate": 41.0}}, facet="bilateral_diplomacy")
    fused = fusion.fuse(plan, {"trade_intelligence": result("trade_intelligence", [same, dep]), "policy_stance": result("policy_stance", [dip])})
    titles = [t for _, t in kinds(fused)]
    assert "India-China: trade and diplomacy diverge" in titles
    assert "India-China: dependence without diplomatic agreement" in titles


def test_shock_groups_exposed_economies_by_camp():
    plan = intent.parse("What if China stops exporting electronics?")
    hits = [insight(code, f"hit {code}", score, 0.6, "r", {}, facet="shock_impact") for code, score in (("CHN", 1.0), ("PRK", 0.4), ("VNM", 0.3), ("USA", 0.2))]
    blocs = {"CHN": "China-Centered Bloc", "PRK": "Russia+Allies", "VNM": "China-Centered Bloc", "USA": "Western Bloc"}
    fused = fusion.fuse(plan, {"trade_intelligence": result("trade_intelligence", hits), "policy_stance": result("policy_stance", [], {"bloc_by_iso3": blocs})})
    cross = [f for f in fused["findings"] if f["kind"] == "cross_agent"][0]
    assert "1 vote in China's own UN bloc" in cross["claim"] and "2 in other blocs" in cross["claim"]


def test_dedupe_keeps_most_confident_and_failed_agents_contribute_nothing():
    plan = intent.parse("How exposed is India?")
    a = insight("IND", "low", 0.1, 0.4, "r", {}, facet="trade_exposure")
    b = insight("IND", "high", 0.1, 0.8, "r", {}, facet="trade_exposure")
    fused = fusion.fuse(plan, {
        "trade_intelligence": result("trade_intelligence", [a, b]),
        "soft_power": result("soft_power", [insight("IND", "x", 0, 0.9, "r", {}, facet="influence")], status="timeout"),
    })
    assert fused["stats"]["duplicates_removed"] == 1
    claims = [f["claim"] for f in fused["findings"]]
    assert "high" in claims and "low" not in claims and "x" not in claims


def test_contract_violations_are_reported_not_fatal():
    plan = intent.parse("How exposed is India?")
    broken = AgentResult(agent="soft_power", status="ok", envelope={"agent": "soft_power", "metadata": {}, "insights": [{"claim": "no fields"}]})
    fused = fusion.fuse(plan, {"soft_power": broken})
    assert fused["contract_issues"]["soft_power"]
