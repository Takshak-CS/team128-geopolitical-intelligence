"""Response synthesis: join the answers to a compound question's parts.

decompose.py splits a compound question and each part is answered on its own,
with its own fan-out, fusion and briefing. This module puts the parts back
together, in two ways:

1. **Cross-part fusion.** The claims from every part go into one pool, and
   fusion's existing cross-agent checks run over it. A check that needs a claim
   from one part and a claim from another can now fire. Only findings that no
   single part produced on its own are kept.
2. **Linking rules.** A few rules join what one part asked with what another
   part asked:
       outlook      today's position (profile part) against the projection
                    (forecast part), for trade, soft power and conflict
       shock reach  a country in another part is among the economies most hit
                    by the shock part's disruption, or trades inside the
                    disrupted country's bloc
       blocs        two parts' countries in the same or different trading and UN blocs
       counterpart  a country in another part is among the day's most active
                    counterparts in the events part
   A linking rule fires only when its two claims answer different parts: each
   facet must be one the part's intent asks for (fusion.PRIMARY_FACETS), and
   the two facets must come from different parts.

Nothing here generates new facts. Every connection quotes the claims it joins,
cites their agents, and takes the confidence of the weaker one. When the parts
are about different countries and no rule finds a link, the combined answer
says so instead of inventing one.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from . import countries, fusion
from .agents.base import AgentResult
from .contract import AGENT_LABELS
from .fusion import Finding, InsightIndex, _support
from .intent import QueryPlan

INTENT_LABELS = {
    "country_profile": "profile",
    "bilateral": "relationship",
    "shock": "disruption scenario",
    "forecast": "forecast",
    "blocs": "blocs",
    "events": "latest events",
    "ranking": "ranking",
}

# Claims per part in the combined summary, and connections in its overview.
PART_SUMMARY_LINES = 3
OVERVIEW_LINES = 3


@dataclass
class PartAnswer:
    plan: QueryPlan
    results: dict[str, AgentResult]
    response: dict

    @property
    def focus(self) -> list[str]:
        return self.plan.iso3s[:2] if self.plan.intent == "bilateral" else self.plan.iso3s[:1]


# ------------------------------------------------------------------ pooling
def pool(parts: list[PartAnswer]) -> dict[str, AgentResult]:
    """One AgentResult per agent holding the claims from every part."""
    pooled: dict[str, AgentResult] = {}
    for part in parts:
        for name, result in part.results.items():
            if result.status not in ("ok", "partial"):
                continue
            if name not in pooled:
                merged = AgentResult(agent=name, status=result.status, envelope=copy.deepcopy(result.envelope), context=dict(result.context))
                pooled[name] = merged
                continue
            merged = pooled[name]
            merged.envelope.setdefault("insights", []).extend(copy.deepcopy(result.envelope.get("insights", [])))
            for key, value in result.context.items():
                if isinstance(value, dict) and isinstance(merged.context.get(key), dict):
                    merged.context[key] = {**value, **merged.context[key]}
                else:
                    merged.context.setdefault(key, value)
    return pooled


def _origins(parts: list[PartAnswer]) -> dict[tuple, set[int]]:
    """Which parts each claim came from, keyed on (agent, entity, facet, claim)."""
    where: dict[tuple, set[int]] = {}
    for i, part in enumerate(parts):
        for name, result in part.results.items():
            for item in result.insights:
                where.setdefault((name, item.get("entity_iso3"), item.get("facet"), item.get("claim")), set()).add(i)
    return where


class _Pool:
    def __init__(self, parts: list[PartAnswer]):
        self.parts = parts
        self.index = InsightIndex(pool(parts))
        self.where = _origins(parts)

    def asked(self, entity: str, facet: str, agent: str) -> list[tuple[int, tuple[str, dict]]]:
        """The claim for (entity, facet) and the parts it answers: parts whose
        intent asks for that facet and that are about that entity."""
        found = self.index.find(entity, facet, agent)
        if not found:
            return []
        name, item = found
        sources = self.where.get((name, item.get("entity_iso3"), item.get("facet"), item.get("claim")), set())
        return [(i, found) for i in sorted(sources)
                if facet in fusion.PRIMARY_FACETS.get(self.parts[i].plan.intent, set()) and entity in self.parts[i].plan.iso3s]

    def across(self, entity: str, first: tuple[str, str], second: tuple[str, str]) -> Optional[tuple[tuple[str, dict], tuple[str, dict], tuple[int, int]]]:
        """Two claims about one entity that answer two different parts."""
        a, b = self.asked(entity, first[0], first[1]), self.asked(entity, second[0], second[1])
        for i, claim_a in a:
            for j, claim_b in b:
                if i != j:
                    return claim_a, claim_b, (i, j)
        return None


def _connection(title: str, claim: str, entity: str, pair: list[tuple[str, dict]], parts: tuple[int, ...], facets: list[str], kind: str = "connection") -> Finding:
    agents = list(dict.fromkeys(agent for agent, _ in pair))
    finding = Finding(kind, title, claim, entity, countries.name_of(entity), min(item["confidence"] for _, item in pair), agents, facets,
                      [_support(agent, item) for agent, item in pair])
    finding.rank = finding.confidence
    finding.parts = sorted(set(parts))  # type: ignore[attr-defined]
    return finding


def _year_value(series, key: str) -> tuple[Optional[int], Optional[float]]:
    if isinstance(series, list) and series and isinstance(series[-1], dict):
        return series[-1].get("year"), series[-1].get(key)
    return None, None


# ------------------------------------------------------------ linking rules
def _rule_outlook(x: str, p: _Pool) -> list[Finding]:
    out: list[Finding] = []
    name = countries.name_of(x)

    hit = p.across(x, ("trade_exposure", "trade_intelligence"), ("trade_outlook", "trade_intelligence"))
    if hit:
        now, later, where = hit
        ev_now, ev_later = now[1].get("evidence", {}), later[1].get("evidence", {})
        rank, of = ev_now.get("rank"), ev_now.get("countries_ranked")
        trend = {"increasing": "rising", "decreasing": "falling"}.get(str(ev_later.get("trend")), str(ev_later.get("trend") or "flat"))
        year, _ = _year_value(ev_later.get("forecast_values"), "predicted_value")
        if rank and of:
            out.append(_connection(
                "Today's trade exposure against the trade forecast",
                f"{name} ranks {rank} of {of} by trade risk today, and its {ev_later.get('metric', 'trade')} are projected {trend}"
                f"{f' to {year}' if year else ''}.",
                x, [now, later], where, ["trade_exposure", "trade_outlook"]))

    hit = p.across(x, ("influence", "soft_power"), ("influence_outlook", "soft_power"))
    if hit:
        now, later, where = hit
        ev_now, ev_later = now[1].get("evidence", {}), later[1].get("evidence", {})
        year, score = _year_value(ev_later.get("forecast"), "score")
        if ev_now.get("score") is not None and score is not None:
            change = score - ev_now["score"]
            out.append(_connection(
                "Today's soft power against its forecast",
                f"{name} scores {ev_now['score']:.1f} on the Soft Power Index today (rank #{ev_now.get('rank')} of {ev_now.get('of')}); "
                f"the forecast puts it at {score:.1f} by {year} ({change:+.1f}), so it is {ev_later.get('direction', 'moving')}.",
                x, [now, later], where, ["influence", "influence_outlook"]))

    hit = p.across(x, ("conflict_exposure", "policy_stance"), ("conflict_outlook", "policy_stance"))
    if hit:
        now, later, where = hit
        ev_now, ev_later = now[1].get("evidence", {}), later[1].get("evidence", {})
        year, value = _year_value(ev_later.get("forecast"), "forecast")
        if ev_now.get("recent_deaths_5y") is not None and ev_later.get("trend"):
            out.append(_connection(
                "Recent conflict against the conflict trend",
                f"{name} has {ev_now['recent_deaths_5y']:,.0f} conflict deaths in the last five years of UCDP data, and its conflict-activity trend is "
                f"{ev_later['trend']}{f' ({value} projected for {year})' if value is not None else ''}.",
                x, [now, later], where, ["conflict_exposure", "conflict_outlook"]))
    return out


def _rule_shock_reach(p: _Pool) -> list[Finding]:
    out: list[Finding] = []
    for i, part in enumerate(p.parts):
        if part.plan.intent != "shock" or not part.plan.primary:
            continue
        origin = part.plan.primary
        oname = countries.name_of(origin)
        impacts = {item.get("entity_iso3"): (agent, item) for agent, item in p.index.all("shock_impact", "trade_intelligence")
                   if item.get("entity_iso3") and item.get("entity_iso3") != origin}
        ranked = sorted(impacts, key=lambda code: impacts[code][1].get("score", 0), reverse=True)
        for j, other in enumerate(p.parts):
            if j == i:
                continue
            for x in other.focus:
                if x == origin or x in part.plan.iso3s[1:]:
                    continue
                name = countries.name_of(x)
                bloc = p.index.find(x, "trade_alignment", "trade_intelligence")
                in_bloc = bloc and bloc[1].get("evidence", {}).get("bloc_anchor_iso3") == origin
                share = (bloc[1].get("evidence", {}).get("internal_trade_share") if in_bloc else None)
                share_text = f" ({share * 100:.0f}% of its trade stays inside it)" if isinstance(share, (int, float)) else ""
                if x in impacts:
                    claim = (f"{name} is among the economies most exposed to the cut in {oname}'s exports "
                             f"(#{ranked.index(x) + 1} of {len(ranked)} ranked, impact score {impacts[x][1].get('score', 0) * 100:.0f}%)")
                    claim += f", and it trades inside the {oname}-anchored bloc{share_text}." if in_bloc else "."
                    pair = [impacts[x]] + ([bloc] if in_bloc else [])
                    out.append(_connection(f"The disruption reaches {name}", claim, x, pair, (i, j), ["shock_impact"] + (["trade_alignment"] if in_bloc else [])))
                elif in_bloc and ranked:
                    shock = p.index.find(origin, "shock_impact", "trade_intelligence") or impacts[ranked[0]]
                    out.append(_connection(
                        f"{name} sits in {oname}'s trading bloc",
                        f"{name} trades inside the {oname}-anchored bloc{share_text}, yet it is not among the {len(ranked)} economies "
                        f"the trade model ranks most exposed to the cut in {oname}'s exports.",
                        x, [shock, bloc], (i, j), ["shock_impact", "trade_alignment"]))
    return out


def _rule_blocs(p: _Pool) -> list[Finding]:
    """Two parts' countries side by side in trading and UN blocs."""
    out: list[Finding] = []
    seen: set[frozenset] = set()
    for i, a in enumerate(p.parts):
        for j, b in enumerate(p.parts):
            if j <= i:
                continue
            for x in a.focus:
                for y in b.focus:
                    if x == y or frozenset((x, y)) in seen or {x, y} <= set(a.plan.iso3s) or {x, y} <= set(b.plan.iso3s):
                        continue
                    tx, ty = p.index.find(x, "trade_alignment", "trade_intelligence"), p.index.find(y, "trade_alignment", "trade_intelligence")
                    dx, dy = p.index.find(x, "diplomatic_alignment", "policy_stance"), p.index.find(y, "diplomatic_alignment", "policy_stance")
                    if not (tx and ty):
                        continue
                    seen.add(frozenset((x, y)))
                    nx, ny = countries.name_of(x), countries.name_of(y)
                    ax, ay = tx[1]["evidence"].get("bloc_anchor_iso3"), ty[1]["evidence"].get("bloc_anchor_iso3")
                    def side(code: str, anchor: str) -> str:
                        return "anchors its own trading bloc" if anchor == code else f"trades in the {countries.name_of(anchor)}-anchored bloc"

                    trade_text = (f"{nx} and {ny} trade in the same bloc (anchored by {countries.name_of(ax)})" if ax == ay
                                  else f"{nx} {side(x, ax)} and {ny} {side(y, ay)}")
                    pair = [tx, ty]
                    if dx and dy:
                        bx, by = dx[1]["evidence"].get("bloc"), dy[1]["evidence"].get("bloc")
                        un_text = f"they vote in the same UN bloc ({bx})" if bx == by else f"at the UN {nx} sits in the {bx} and {ny} in the {by}"
                        joiner = ", and " if (ax == ay) == (bx == by) else ", but "
                        trade_text += joiner + un_text
                        pair += [dx, dy]
                    out.append(_connection(f"{nx} and {ny} side by side", trade_text + ".", x, pair, (i, j), ["trade_alignment", "diplomatic_alignment"]))
    return out


def _rule_counterpart(p: _Pool) -> list[Finding]:
    """A country from another part among the day's most active counterparts."""
    out: list[Finding] = []
    for i, part in enumerate(p.parts):
        if part.plan.intent not in ("events", "country_profile") or not part.plan.primary:
            continue
        x = part.plan.primary
        found = p.index.find(x, "event_partners", "event_summarization")
        if not found:
            continue
        partners = {row.get("iso3"): row for row in (found[1].get("evidence", {}).get("partners") or []) if isinstance(row, dict)}
        for j, other in enumerate(p.parts):
            if j == i:
                continue
            for y in other.focus:
                row = partners.get(y)
                if y == x or not row:
                    continue
                g = row.get("avg_goldstein") or 0.0
                tone = "cooperative" if g >= 1.0 else "conflictual" if g <= -1.0 else "mixed"
                day = found[1].get("evidence", {}).get("date", "")
                day_text = f" on {day[:4]}-{day[4:6]}-{day[6:]}" if len(str(day)) == 8 else ""
                out.append(_connection(
                    f"{countries.name_of(y)} in {countries.name_of(x)}'s news",
                    f"{countries.name_of(y)} is one of {countries.name_of(x)}'s most active counterparts{day_text}: "
                    f"{row.get('count')} events, mean Goldstein {g:+.1f} ({tone}).",
                    x, [found], (i, j), ["event_partners"]))
    return out


# ---------------------------------------------------------------- connect
def connect(parts: list[PartAnswer]) -> dict:
    """Findings that join the parts, and whether the parts are linked at all."""
    p = _Pool(parts)
    findings: list[Finding] = []
    for x in dict.fromkeys(code for part in parts for code in part.focus):
        findings += _rule_outlook(x, p)
    findings += _rule_shock_reach(p)
    findings += _rule_blocs(p)
    findings += _rule_counterpart(p)

    # Fusion's own cross-agent checks over the pooled claims; keep only what no
    # part found on its own. The events check is left out: its reference data
    # (the day's counterparts) belongs to one part's country, and each part
    # already ran it for that country.
    known = {(f["title"], f["claim"]) for part in parts for f in part.response["fused"]["findings"]}
    for x in dict.fromkeys(code for part in parts for code in part.plan.iso3s):
        for rule in (fusion._rule_alignment, fusion._rule_critical_partners, fusion._rule_momentum):
            for finding in rule(x, p.index):
                if (finding.title, finding.claim) not in known:
                    finding.rank = finding.confidence * fusion.KIND_WEIGHT[finding.kind]
                    findings.append(finding)
                    known.add((finding.title, finding.claim))

    unique: dict[tuple, Finding] = {}
    for finding in findings:
        unique.setdefault((finding.title, finding.claim), finding)
    ordered = sorted(unique.values(), key=lambda f: -f.rank)

    per_part = [set(part.plan.iso3s) for part in parts]
    shared = sorted(set.intersection(*per_part)) if all(per_part) else []
    payload = []
    for finding in ordered:
        item = finding.to_dict()
        item["parts"] = [i + 1 for i in getattr(finding, "parts", [])]
        payload.append(item)
    return {"linked": bool(payload or shared), "shared_countries": shared, "findings": payload}


# ---------------------------------------------------------------- compose
def _cite(finding: dict) -> str:
    return f"[{'+'.join(finding.get('agent_labels') or [])}, conf {finding['confidence']:.2f}]"


def _subject(parts: list[PartAnswer]) -> str:
    names = list(dict.fromkeys(e.name for part in parts for e in part.plan.entities))
    if not names:
        return "Global view"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def compose(question: str, parts: list[PartAnswer], connections: dict) -> dict:
    """The combined answer shown above the per-part tabs."""
    labels = list(dict.fromkeys(INTENT_LABELS.get(part.plan.intent, part.plan.intent) for part in parts))
    headline = f"{_subject(parts)}: {', '.join(labels[:-1]) + ' and ' + labels[-1] if len(labels) > 1 else labels[0]}"

    paragraphs = []
    for i, part in enumerate(parts):
        brief = part.response["briefing"]
        lines = [line for line in brief.get("summary", []) if line][:PART_SUMMARY_LINES]
        paragraphs.append({"part": i + 1, "question": part.plan.question, "intent": part.plan.intent, "headline": brief.get("headline"), "text": " ".join(lines)})

    findings = connections["findings"]
    if findings:
        overview = " ".join(f"{f['claim']} {_cite(f)}" for f in findings[:OVERVIEW_LINES])
        note = None
    elif connections["shared_countries"]:
        names = ", ".join(countries.name_of(c) for c in connections["shared_countries"])
        overview = None
        note = f"Every part is about {names}, but no claim in one part bears on another beyond what each part says on its own."
    else:
        overview = None
        note = (f"The parts are about different countries ({'; '.join(_subject([part]) for part in parts)}), and the agents' data shows no link "
                "between them, so they are answered side by side.")

    return {
        "headline": headline,
        "overview": overview,
        "paragraphs": paragraphs,
        "connections": {"title": "Connecting the parts", "findings": findings},
        "linked": connections["linked"],
        "note": note,
    }
