"""Compose the fused findings into a readable, cited briefing.

Every sentence in the briefing comes from a finding, and every finding cites the
agent(s) it rests on and its confidence. Nothing here generates new claims; it
orders and phrases what fusion produced, so the narrative can always be traced
back to an agent response.
"""

from __future__ import annotations

from . import countries
from .agents.base import AgentResult
from .contract import AGENT_LABELS
from .intent import QueryPlan


def _cite(finding: dict) -> str:
    labels = "+".join(finding.get("agent_labels") or [])
    return f"[{labels}, conf {finding['confidence']:.2f}]"


def _headline(plan: QueryPlan, findings: list[dict], results: dict[str, AgentResult]) -> str:
    names = [countries.name_of(code) for code in plan.iso3s[:2]]
    lead = next((f for f in findings if f["kind"] in ("divergence", "corroboration")), None)
    if plan.intent == "events" and names:
        day = (results.get("event_summarization") and results["event_summarization"].context.get("date")) or ""
        when = f" on {day[:4]}-{day[4:6]}-{day[6:]}" if day else ""
        return f"{names[0]}: what the news shows{when}"
    if plan.intent == "bilateral" and len(names) == 2:
        subject = f"{names[0]} and {names[1]}"
    elif plan.intent == "shock" and names:
        pct = int(round((plan.severity or 0.5) * 100))
        sector = "" if plan.sector == "all" else f" {plan.sector}"
        return f"What a {pct}% cut in {names[0]}'s{sector} exports would do"
    elif plan.intent == "ranking" or not names:
        return "Global overview"
    else:
        subject = names[0]
    if lead:
        title = lead["title"].split(": ", 1)[-1]
        return f"{subject}: {title[0].lower() + title[1:]}"
    return f"{subject}: fused briefing"


def _coverage(plan: QueryPlan, results: dict[str, AgentResult], alignment: dict) -> str:
    answered = [a for a, r in results.items() if r.status in ("ok", "partial") and r.insights]
    parts = []
    for agent in plan.agents:
        result = results.get(agent)
        label = AGENT_LABELS.get(agent, agent)
        if not result:
            continue
        if result.status in ("ok", "partial") and result.insights:
            served = alignment.get("served", {}).get(agent)
            parts.append(f"{label} ({served})" if served else label)
        else:
            parts.append(f"{label}: {result.status}")
    return f"{len(answered)} of {len(plan.agents)} agents answered - " + "; ".join(parts) + "."


def compose(plan: QueryPlan, fused: dict, results: dict[str, AgentResult], alignment: dict) -> dict:
    findings = fused["findings"]
    divergences = [f for f in findings if f["kind"] == "divergence"]
    agreements = [f for f in findings if f["kind"] == "corroboration"]
    cross = [f for f in findings if f["kind"] == "cross_agent"]
    singles = [f for f in findings if f["kind"] == "insight"]

    summary: list[str] = []
    prefix = {"divergence": "Key tension: ", "corroboration": "Agents agree: ", "cross_agent": ""}
    for finding in [f for f in findings if f["kind"] != "insight"][:2]:
        summary.append(f"{prefix[finding['kind']]}{finding['claim']} {_cite(finding)}")
    # Then the strongest claim from each agent in turn - agents the question is
    # about first - so one agent with high confidences cannot crowd out the rest.
    best_per_agent: dict[str, dict] = {}
    for finding in singles:
        best_per_agent.setdefault(finding["agents"][0], finding)
    ordered = [a for a in plan.agents if a in plan.focus_agents] + [a for a in plan.agents if a not in plan.focus_agents]
    for agent in ordered:
        if len(summary) >= 5:
            break
        if agent in best_per_agent:
            summary.append(f"{best_per_agent[agent]['claim']} {_cite(best_per_agent[agent])}")
    if not summary:
        summary.append("No agent returned usable insights for this question.")

    sections = []
    if divergences:
        sections.append({"title": "Where the agents disagree", "kind": "divergence", "findings": divergences})
    if agreements:
        sections.append({"title": "Where independent agents agree", "kind": "corroboration", "findings": agreements})
    if cross:
        sections.append({"title": "Cross-agent analysis", "kind": "cross_agent", "findings": cross})
    by_agent: dict[str, list[dict]] = {}
    for finding in singles:
        by_agent.setdefault(finding["agents"][0], []).append(finding)
    for agent in plan.agents:
        if by_agent.get(agent):
            sections.append({"title": AGENT_LABELS.get(agent, agent), "kind": "agent", "agent": agent, "findings": by_agent[agent][:6]})

    caveats = sorted({f["caveat"] for f in findings if f.get("caveat")})
    coverage = _coverage(plan, results, alignment)
    headline = _headline(plan, findings, results)

    lines = [f"## {headline}", ""]
    lines += [f"- {sentence}" for sentence in summary]
    lines += ["", f"_{coverage}_"]
    for section in sections:
        lines += ["", f"### {section['title']}"]
        for finding in section["findings"]:
            lines.append(f"- {finding['claim']} {_cite(finding)}")
    if caveats:
        lines += ["", "### Caveats"] + [f"- {text}" for text in caveats]
    if alignment.get("warnings"):
        lines += ["", "### Time alignment"] + [f"- {text}" for text in alignment["warnings"]]

    return {
        "headline": headline,
        "summary": summary,
        "sections": sections,
        "caveats": caveats,
        "coverage": coverage,
        "markdown": "\n".join(lines),
    }
