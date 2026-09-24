"""Insight fusion: turn four agents' envelopes into one ranked set of findings.

Concatenating four answers is not fusion. This module does three things a single
agent cannot:

1. **Deduplicate** - one claim per (agent, entity, facet[, sector]), keeping the
   most confident.
2. **Cross-check** - a fixed set of rules line up claims from *independent*
   agents about the same entity and the same underlying question, and mark each
   pair as a corroboration (they agree) or a divergence (they disagree).
3. **Rank** - by confidence, relevance to the question, and whether the finding
   rests on more than one agent.

Divergence is a first-class output, not noise to be averaged away. A country
whose trade structure and UN voting point in different directions is exactly the
case an analyst wants flagged - and no single-source tool can see it.

Confidence arithmetic:
    same proposition   1 - prod(1 - c_i), capped at 0.97   independent agents each supporting
                                                            one conclusion (both measure alignment
                                                            with the same country; both measure momentum)
    conjunction        min(c_i)                            a finding that joins two *different* facts
                                                            ("coverage is cooperative" + "partner carries
                                                            12% of trade") is only as solid as the weaker
    divergence         min(c_i)                            only as solid as its weakest side
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from . import countries
from .agents.base import AgentResult
from .contract import AGENT_LABELS, validate_envelope
from .intent import QueryPlan

KIND_WEIGHT = {"divergence": 1.35, "corroboration": 1.2, "cross_agent": 1.1, "insight": 1.0}
# Findings about what the question actually asked (see PRIMARY_FACETS) rank higher.
PRIMARY_BOOST = 1.3

# Which facets matter most for each intent; others still appear, lower down.
PRIMARY_FACETS = {
    "country_profile": {"influence", "diplomatic_alignment", "trade_exposure", "trade_alignment", "trade_dependence", "event_activity", "conflict_exposure"},
    "bilateral": {"bilateral_trade_bloc", "bilateral_trade_dependence", "bilateral_diplomacy", "bilateral_events", "bilateral_influence", "relationship_baseline"},
    "shock": {"shock_impact"},
    "forecast": {"trade_outlook", "influence_outlook", "conflict_outlook"},
    "blocs": {"trade_alignment", "diplomatic_alignment", "diplomatic_blocs"},
    "events": {"event_activity", "event_partners", "event_headline", "relationship_baseline"},
    "ranking": {"trade_exposure", "trade_dependence", "supply_fragility", "trade_alignment", "influence", "diplomatic_blocs"},
}

PROVENANCE_CAVEAT = {
    "override_replaced": "Policy Stance publishes a hard-coded UN bloc for {name}; this finding uses the module's own vote-model placement instead, which comes from the full 1989-2025 voting history rather than the aligned year.",
    "anchor": "{name} is one of the anchor countries that define its UN bloc in the Policy Stance model, so its diplomatic side is an assumption, not a measurement.",
    "manual_override": "{name}'s UN bloc is a hard-coded override in the Policy Stance module, so its diplomatic side is an assumption, not a measurement.",
    "fallback_rule": "{name} has no UN voting records loaded, so its UN bloc comes from a hand-written fallback rule.",
}


@dataclass
class Finding:
    kind: str
    title: str
    claim: str
    entity_iso3: Optional[str]
    entity_name: str
    confidence: float
    agents: list[str]
    facets: list[str]
    supporting: list[dict] = field(default_factory=list)
    caveat: Optional[str] = None
    rank: float = 0.0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["confidence"] = round(self.confidence, 3)
        payload["rank"] = round(self.rank, 4)
        payload["agent_labels"] = [AGENT_LABELS.get(a, a) for a in self.agents]
        return payload


def corroborated(confidences: Iterable[float]) -> float:
    remaining = 1.0
    for value in confidences:
        remaining *= 1.0 - max(0.0, min(1.0, value))
    return min(0.97, 1.0 - remaining)


def _support(agent: str, item: dict) -> dict:
    return {
        "agent": agent,
        "agent_label": AGENT_LABELS.get(agent, agent),
        "facet": item.get("facet"),
        "claim": item.get("claim"),
        "confidence": round(float(item.get("confidence", 0.0)), 3),
        "reason": item.get("reason"),
    }


class InsightIndex:
    """Deduplicated insights, addressable by entity and facet."""

    def __init__(self, results: dict[str, AgentResult]):
        self.results = results
        self.items: list[tuple[str, dict]] = []
        self.contract_issues: dict[str, list[str]] = {}
        self.received = 0
        best: dict[tuple, tuple[str, dict]] = {}
        for agent, result in results.items():
            if result.status not in ("ok", "partial"):
                continue
            problems = validate_envelope(result.envelope)
            if problems:
                self.contract_issues[agent] = problems
            for item in result.insights:
                self.received += 1
                evidence = item.get("evidence") or {}
                key = (agent, item.get("entity_iso3"), item.get("facet"), evidence.get("sector"), _pair_key(evidence), item.get("claim") if item.get("facet") in (None, "shock_impact") else None)
                current = best.get(key)
                if current is None or item.get("confidence", 0) > current[1].get("confidence", 0):
                    best[key] = (agent, item)
        self.items = list(best.values())

    def find(self, entity: Optional[str], facet: str, agent: Optional[str] = None) -> Optional[tuple[str, dict]]:
        matches = [(a, i) for a, i in self.items if i.get("entity_iso3") == entity and i.get("facet") == facet and (agent is None or a == agent)]
        if not matches:
            return None
        return max(matches, key=lambda pair: pair[1].get("confidence", 0))

    def all(self, facet: str, agent: Optional[str] = None) -> list[tuple[str, dict]]:
        return [(a, i) for a, i in self.items if i.get("facet") == facet and (agent is None or a == agent)]

    def context(self, agent: str) -> dict:
        result = self.results.get(agent)
        return result.context if result and result.status in ("ok", "partial") else {}


def _pair_key(evidence: dict) -> Optional[str]:
    pair = evidence.get("pair")
    return "-".join(pair) if isinstance(pair, list) else None


# ------------------------------------------------------------------ rules
def _rule_alignment(x: str, idx: InsightIndex) -> list[Finding]:
    """Is X diplomatically aligned with the anchor of the trading bloc it sits in?"""
    trade = idx.find(x, "trade_alignment", "trade_intelligence")
    policy = idx.find(x, "diplomatic_alignment", "policy_stance")
    bloc_map = idx.context("policy_stance").get("bloc_by_iso3", {})
    if not trade or not policy:
        return []
    t_ev, p_ev = trade[1].get("evidence", {}), policy[1].get("evidence", {})
    anchor = t_ev.get("bloc_anchor_iso3")
    x_bloc = p_ev.get("bloc")
    if not anchor or not x_bloc:
        return []
    name, anchor_name = countries.name_of(x), countries.name_of(anchor)
    share = t_ev.get("internal_trade_share")
    share_text = f" ({share * 100:.0f}% of its trade stays inside it)" if isinstance(share, (int, float)) else ""
    support = [_support(*trade), _support(*policy)]
    caveat = PROVENANCE_CAVEAT.get(p_ev.get("provenance", ""), "").format(name=name) or None
    confidences = [trade[1]["confidence"], policy[1]["confidence"]]

    if anchor == x:
        return [
            Finding(
                "cross_agent",
                "Anchors its own trading bloc",
                f"{name} anchors its own trading bloc ({t_ev.get('bloc_size')} members){share_text} and sits in the {x_bloc} at the UN.",
                x, name, min(confidences), ["trade_intelligence", "policy_stance"], ["trade_alignment", "diplomatic_alignment"], support, caveat,
            )
        ]
    anchor_bloc = bloc_map.get(anchor)
    if not anchor_bloc:
        return []
    if anchor_bloc == x_bloc:
        return [
            Finding(
                "corroboration",
                "Trade and diplomacy point the same way",
                f"{name} trades inside the {anchor_name}-anchored bloc{share_text} and votes in the same UN bloc as {anchor_name} ({x_bloc}).",
                x, name, corroborated(confidences), ["trade_intelligence", "policy_stance"], ["trade_alignment", "diplomatic_alignment"], support, caveat,
            )
        ]
    return [
        Finding(
            "divergence",
            "Economic and diplomatic alignment diverge",
            f"{name} trades inside the {anchor_name}-anchored bloc{share_text}, but at the UN it sits in the {x_bloc} while {anchor_name} sits in the {anchor_bloc}.",
            x, name, min(confidences), ["trade_intelligence", "policy_stance"], ["trade_alignment", "diplomatic_alignment"], support, caveat,
        )
    ]


def _rule_critical_partners(x: str, idx: InsightIndex) -> list[Finding]:
    """Do X's biggest trade dependencies sit on the same side of the UN bloc line?"""
    bloc_map = idx.context("policy_stance").get("bloc_by_iso3", {})
    policy = idx.find(x, "diplomatic_alignment", "policy_stance")
    x_bloc = bloc_map.get(x)
    if not x_bloc or not policy:
        return []
    name = countries.name_of(x)
    caveat = PROVENANCE_CAVEAT.get(policy[1].get("evidence", {}).get("provenance", ""), "").format(name=name) or None
    out: list[Finding] = []

    lev = idx.find(x, "trade_dependence", "trade_intelligence")
    if lev:
        ev = lev[1].get("evidence", {})
        partner, share = ev.get("most_critical_partner_iso3"), ev.get("critical_partner_dependence") or 0
        p_bloc = bloc_map.get(partner)
        if partner and p_bloc and share >= 0.05:
            pname = countries.name_of(partner)
            support = [_support(*lev), _support(*policy)]
            confidences = [lev[1]["confidence"], policy[1]["confidence"]]
            if p_bloc == x_bloc:
                out.append(Finding(
                    "corroboration", "Largest trade dependency is a diplomatic ally",
                    f"{name}'s most critical trade relationship, {pname} ({share * 100:.1f}% of its trade), is also in its UN bloc ({x_bloc}).",
                    x, name, min(confidences), ["trade_intelligence", "policy_stance"], ["trade_dependence", "diplomatic_alignment"], support, caveat))
            else:
                out.append(Finding(
                    "divergence", "Critical trade partner across the bloc line",
                    f"{name}'s most critical trade relationship is {pname} ({share * 100:.1f}% of its trade), which votes in the {p_bloc} while {name} sits in the {x_bloc}.",
                    x, name, min(confidences), ["trade_intelligence", "policy_stance"], ["trade_dependence", "diplomatic_alignment"], support, caveat))

    for agent, item in idx.all("supply_fragility", "trade_intelligence"):
        if item.get("entity_iso3") != x:
            continue
        ev = item.get("evidence", {})
        supplier, share, sector = ev.get("top_supplier_iso3"), ev.get("top_supplier_share") or 0, ev.get("sector")
        s_bloc = bloc_map.get(supplier)
        if supplier and s_bloc and s_bloc != x_bloc and share >= 0.25:
            sname = countries.name_of(supplier)
            out.append(Finding(
                "divergence", f"{str(sector).title()} supply depends on another bloc",
                f"{name} sources {share * 100:.0f}% of its {sector} imports from {sname}, which votes in the {s_bloc} ({name}: {x_bloc}).",
                x, name, min(item["confidence"], policy[1]["confidence"]), ["trade_intelligence", "policy_stance"], ["supply_fragility", "diplomatic_alignment"],
                [_support(agent, item), _support(*policy)], caveat))
    return out


def _rule_momentum(x: str, idx: InsightIndex) -> list[Finding]:
    """Do influence and trade trajectories move together?"""
    trade = idx.find(x, "trade_outlook", "trade_intelligence")
    influence = idx.find(x, "influence_outlook", "soft_power") or idx.find(x, "influence_trend", "soft_power")
    if not trade or not influence:
        return []
    t_dir = {"increasing": "rising", "decreasing": "falling"}.get(str(trade[1].get("evidence", {}).get("trend")), "flat")
    s_dir = influence[1].get("evidence", {}).get("direction", "unknown")
    if "flat" in (t_dir, s_dir) or "unknown" in (t_dir, s_dir):
        return []
    name = countries.name_of(x)
    metric = trade[1].get("evidence", {}).get("metric", "trade")
    support = [_support(*trade), _support(*influence)]
    confidences = [trade[1]["confidence"], influence[1]["confidence"]]
    if t_dir == s_dir:
        return [Finding("corroboration", "Economic and soft-power momentum agree",
                        f"{name}'s {metric} are projected {t_dir} and its soft power is also {s_dir}.",
                        x, name, corroborated(confidences), ["trade_intelligence", "soft_power"], ["trade_outlook", influence[1].get("facet")], support)]
    return [Finding("divergence", "Economic and soft-power momentum diverge",
                    f"{name}'s {metric} are projected {t_dir} while its soft power is {s_dir}.",
                    x, name, min(confidences), ["trade_intelligence", "soft_power"], ["trade_outlook", influence[1].get("facet")], support)]


def _rule_event_friction(x: str, idx: InsightIndex) -> list[Finding]:
    """Today's news against trade stakes and against the long-run relationship baseline."""
    out: list[Finding] = []
    events_ctx = idx.context("event_summarization")
    partners = {p["iso3"]: p for p in events_ctx.get("partners", [])}
    activity = idx.find(x, "event_partners", "event_summarization") or idx.find(x, "event_activity", "event_summarization")
    name = countries.name_of(x)

    lev = idx.find(x, "trade_dependence", "trade_intelligence")
    if lev and activity:
        ev = lev[1].get("evidence", {})
        partner = ev.get("most_critical_partner_iso3")
        share = ev.get("critical_partner_dependence") or 0
        seen = partners.get(partner)
        if seen and seen["count"] >= 3 and share >= 0.05:
            pname = countries.name_of(partner)
            support = [_support(*lev), _support(*activity)]
            conf = min(lev[1]["confidence"], activity[1]["confidence"])
            if seen["avg_goldstein"] <= -1.0:
                out.append(Finding("divergence", "Friction with a critical trade partner",
                                   f"Today's {name}-{pname} coverage is conflictual (mean Goldstein {seen['avg_goldstein']:+.1f} over {seen['count']} events) although {pname} carries {share * 100:.1f}% of {name}'s trade.",
                                   x, name, conf, ["event_summarization", "trade_intelligence"], ["event_partners", "trade_dependence"], support))
            elif seen["avg_goldstein"] >= 1.0:
                out.append(Finding("corroboration", "Cooperative coverage with a critical trade partner",
                                   f"Today's {name}-{pname} coverage is cooperative (mean Goldstein {seen['avg_goldstein']:+.1f}) and {pname} carries {share * 100:.1f}% of {name}'s trade.",
                                   x, name, conf, ["event_summarization", "trade_intelligence"], ["event_partners", "trade_dependence"], support))

    for agent, base in idx.all("relationship_baseline", "event_summarization"):
        if base.get("entity_iso3") != x:
            continue
        ev = base.get("evidence", {})
        other = next((code for code in ev.get("pair", []) if code != x), None)
        today = partners.get(other)
        if not other or not today:
            continue
        avg10 = ev.get("avg_10yr") or 0.0
        g = today["avg_goldstein"]
        oname = countries.name_of(other)
        support = [_support(agent, base)] + ([_support(*activity)] if activity else [])
        conf = min(base["confidence"], activity[1]["confidence"] if activity else 0.5)
        # Same agent, two independent datasets (GDELT daily vs GGE annual).
        if avg10 >= 0.1 and g <= -1.0:
            out.append(Finding("divergence", "Today is out of character for the relationship",
                               f"{name}-{oname} coverage today is conflictual (Goldstein {g:+.1f}) against a {ev.get('baseline_label')} 1990-2024 baseline.",
                               x, name, conf, ["event_summarization"], ["event_partners", "relationship_baseline"], support))
        elif avg10 <= -0.1 and g >= 1.0:
            out.append(Finding("divergence", "Today is warmer than the relationship's history",
                               f"{name}-{oname} coverage today is cooperative (Goldstein {g:+.1f}) against a {ev.get('baseline_label')} 1990-2024 baseline.",
                               x, name, conf, ["event_summarization"], ["event_partners", "relationship_baseline"], support))
    return out


def _rule_bilateral(pair: list[str], idx: InsightIndex) -> list[Finding]:
    a, b = pair
    name_a, name_b = countries.name_of(a), countries.name_of(b)
    title_pair = f"{name_a}-{name_b}"
    out: list[Finding] = []
    trade_same = next((i for _, i in idx.all("bilateral_trade_bloc", "trade_intelligence")), None)
    policy = next((i for _, i in idx.all("bilateral_diplomacy", "policy_stance")), None)
    if trade_same and policy:
        t_same = bool(trade_same["evidence"]["same_bloc"])
        metrics = policy.get("evidence", {}).get("metrics", {})
        p_same = bool(metrics.get("same_bloc"))
        support = [_support("trade_intelligence", trade_same), _support("policy_stance", policy)]
        confidences = [trade_same["confidence"], policy["confidence"]]
        if t_same == p_same:
            text = "share a trading bloc and a UN bloc" if t_same else "sit in different trading blocs and different UN blocs"
            out.append(Finding("corroboration", f"{title_pair}: trade and diplomacy agree", f"{name_a} and {name_b} {text}.",
                               a, title_pair, corroborated(confidences), ["trade_intelligence", "policy_stance"], ["bilateral_trade_bloc", "bilateral_diplomacy"], support))
        else:
            text = ("share a trading bloc but vote in different UN blocs" if t_same else "vote in the same UN bloc but trade in different blocs")
            out.append(Finding("divergence", f"{title_pair}: trade and diplomacy diverge", f"{name_a} and {name_b} {text}.",
                               a, title_pair, min(confidences), ["trade_intelligence", "policy_stance"], ["bilateral_trade_bloc", "bilateral_diplomacy"], support))

    dependence = next((i for _, i in idx.all("bilateral_trade_dependence", "trade_intelligence") if "exposed_dependence" in i.get("evidence", {})), None)
    if dependence and policy:
        exposed = dependence.get("entity_iso3")
        share = dependence["evidence"].get("exposed_dependence") or 0
        match_rate = policy.get("evidence", {}).get("metrics", {}).get("vote_match_rate")
        if match_rate is not None and share >= 0.10 and match_rate < 50:
            out.append(Finding("divergence", f"{title_pair}: dependence without diplomatic agreement",
                               f"{countries.name_of(exposed)} relies on the relationship for {share * 100:.0f}% of its trade, yet the two voted alike on only {match_rate:.0f}% of sampled UN resolutions.",
                               exposed, title_pair, min(dependence["confidence"], policy["confidence"]), ["trade_intelligence", "policy_stance"], ["bilateral_trade_dependence", "bilateral_diplomacy"],
                               [_support("trade_intelligence", dependence), _support("policy_stance", policy)]))

    today = next((i for _, i in idx.all("bilateral_events", "event_summarization") if "avg_goldstein" in i.get("evidence", {})), None)
    if today and policy:
        g = today["evidence"]["avg_goldstein"]
        metrics = policy.get("evidence", {}).get("metrics", {})
        aligned = bool(metrics.get("same_bloc"))
        if aligned and g <= -1.0:
            out.append(Finding("divergence", f"{title_pair}: allies in conflictual coverage",
                               f"{name_a} and {name_b} share a UN bloc, but today's coverage between them is conflictual (Goldstein {g:+.1f}).",
                               a, title_pair, min(today["confidence"], policy["confidence"]), ["event_summarization", "policy_stance"], ["bilateral_events", "bilateral_diplomacy"],
                               [_support("event_summarization", today), _support("policy_stance", policy)]))
    return out


def _rule_shock(plan: QueryPlan, idx: InsightIndex) -> list[Finding]:
    origin = plan.primary
    bloc_map = idx.context("policy_stance").get("bloc_by_iso3", {})
    impacts = [(a, i) for a, i in idx.all("shock_impact", "trade_intelligence") if i.get("entity_iso3") and i.get("entity_iso3") != origin]
    if not origin or not impacts or not bloc_map.get(origin):
        return []
    origin_bloc = bloc_map[origin]
    impacts.sort(key=lambda pair: pair[1].get("score", 0), reverse=True)
    top = impacts[: max(3, plan.limit)]
    labelled = [(i["entity_iso3"], bloc_map.get(i["entity_iso3"])) for _, i in top]
    same = [code for code, bloc in labelled if bloc == origin_bloc]
    other = [code for code, bloc in labelled if bloc and bloc != origin_bloc]
    unknown = [code for code, bloc in labelled if not bloc]
    oname = countries.name_of(origin)
    parts = [f"{len(same)} vote in {oname}'s own UN bloc ({origin_bloc})" + (f": {', '.join(countries.name_of(c) for c in same)}" if same else "")]
    if other:
        parts.append(f"{len(other)} in other blocs: {', '.join(countries.name_of(c) for c in other)}")
    if unknown:
        parts.append(f"{len(unknown)} without a bloc in the Policy Stance data")
    pct = int(round((plan.severity or 0.5) * 100))
    sector = "" if plan.sector == "all" else f" {plan.sector}"
    confidence = min(0.75, sum(i["confidence"] for _, i in top) / len(top))
    return [Finding(
        "cross_agent", "Who a disruption would hit, by diplomatic camp",
        f"Of the {len(top)} economies most exposed to a {pct}% cut in {oname}'s{sector} exports, " + "; ".join(parts) + ".",
        origin, oname, confidence, ["trade_intelligence", "policy_stance"], ["shock_impact", "diplomatic_alignment"],
        [_support(a, i) for a, i in top[:3]],
    )]


# ---------------------------------------------------------------- fusion
def fuse(plan: QueryPlan, results: dict[str, AgentResult]) -> dict:
    idx = InsightIndex(results)
    findings: list[Finding] = []
    focus = plan.iso3s[:2] if plan.intent == "bilateral" else plan.iso3s[:1]

    if plan.intent == "bilateral" and len(focus) == 2:
        findings += _rule_bilateral(focus, idx)
    if plan.intent == "shock":
        findings += _rule_shock(plan, idx)
    for x in focus:
        findings += _rule_alignment(x, idx)
        findings += _rule_critical_partners(x, idx)
        findings += _rule_momentum(x, idx)
        findings += _rule_event_friction(x, idx)

    primary = PRIMARY_FACETS.get(plan.intent, set())
    for agent, item in idx.items:
        entity = item.get("entity_iso3")
        relevance = 1.0 if (entity in focus or entity is None or not focus) else 0.7
        if item.get("facet") in primary:
            relevance *= PRIMARY_BOOST
        if agent in plan.focus_agents:
            relevance *= 1.1
        findings.append(Finding(
            "insight", AGENT_LABELS.get(agent, agent), item.get("claim", ""), entity, item.get("entity_name") or countries.name_of(entity),
            float(item.get("confidence", 0.0)), [agent], [item.get("facet") or "general"], [_support(agent, item)],
            rank=float(item.get("confidence", 0.0)) * relevance,
        ))

    for finding in findings:
        if finding.kind == "insight":
            continue
        finding.rank = finding.confidence * KIND_WEIGHT[finding.kind]
        if finding.caveat:
            finding.rank *= 0.85
        if set(finding.facets) & primary:
            finding.rank *= PRIMARY_BOOST
        if plan.intent == "bilateral" and not any(f.startswith("bilateral") or f == "relationship_baseline" for f in finding.facets):
            # About one side and a third country, not about the pair asked about.
            finding.rank *= 0.7
    # Cross-agent findings first, then single-agent insights, each by rank.
    findings.sort(key=lambda f: (f.kind == "insight", -f.rank))

    cross = [f for f in findings if f.kind != "insight"]
    return {
        "findings": [f.to_dict() for f in findings],
        "stats": {
            "insights_received": idx.received,
            "insights_after_dedupe": len(idx.items),
            "duplicates_removed": idx.received - len(idx.items),
            "divergences": sum(1 for f in cross if f.kind == "divergence"),
            "corroborations": sum(1 for f in cross if f.kind == "corroboration"),
            "cross_agent": sum(1 for f in cross if f.kind == "cross_agent"),
            "agents_contributing": sorted({a for a, _ in idx.items}),
        },
        "contract_issues": idx.contract_issues,
    }
