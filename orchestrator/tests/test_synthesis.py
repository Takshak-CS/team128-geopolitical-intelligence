"""Response synthesis: a compound question's parts joined into one answer."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app import intent, synthesis
from app.agents.base import AgentResult
from app.pipeline import Orchestrator
from tests.replay import ReplayTransport, load_records

HERE = Path(__file__).resolve().parent
DAY = "20260922"


def ask(question, overrides=None):
    transport = ReplayTransport(load_records())

    async def run():
        orchestrator = Orchestrator(client=httpx.AsyncClient(transport=transport))
        try:
            return await orchestrator.ask(question, overrides)
        finally:
            await orchestrator.close()

    return asyncio.run(run())


def agent_claims(response):
    return {(name, item["claim"]) for part in response["parts"] for name, agent in part["agents"].items()
            for item in agent.get("envelope", {}).get("insights", [])}


# ------------------------------------------------------------ replayed pipeline

def test_a_shock_and_a_bloc_question_are_linked_through_the_bloc():
    result = ask("What if China stops exporting electronics? Which bloc is Vietnam in?", {"date": DAY})
    combined = result["combined"]
    assert combined["linked"] is True
    titles = [f["title"] for f in combined["connections"]["findings"]]
    assert "Vietnam sits in China's trading bloc" in titles
    link = combined["connections"]["findings"][titles.index("Vietnam sits in China's trading bloc")]
    assert link["parts"] == [1, 2]
    assert link["confidence"] == pytest.approx(min(s["confidence"] for s in link["supporting"]), abs=1e-3)
    assert combined["overview"].startswith(combined["connections"]["findings"][0]["claim"])
    assert [p["question"] for p in combined["paragraphs"]] == ["What if China stops exporting electronics?", "Which bloc is Vietnam in?"]


def test_unrelated_parts_are_answered_side_by_side_and_say_so():
    combined = ask("Forecast Brazil exports to 2030, and which bloc is Vietnam in?")["combined"]
    assert combined["linked"] is False
    assert combined["connections"]["findings"] == []
    assert combined["overview"] is None
    assert "no link" in combined["note"]
    assert combined["headline"] == "Brazil and Vietnam: forecast and blocs"


def test_every_connection_rests_on_claims_the_agents_made():
    result = ask("What if China stops exporting electronics? Which bloc is Vietnam in?", {"date": DAY})
    claims = agent_claims(result)
    for finding in result["combined"]["connections"]["findings"]:
        for support in finding["supporting"]:
            assert (support["agent"], support["claim"]) in claims
        assert finding["agent_labels"]


def test_each_paragraph_is_the_parts_own_summary():
    result = ask("Forecast Brazil exports to 2030, and which bloc is Vietnam in?")
    for paragraph, part in zip(result["combined"]["paragraphs"], result["parts"]):
        assert paragraph["text"] == " ".join(part["briefing"]["summary"][:synthesis.PART_SUMMARY_LINES])


def test_a_single_question_has_no_combined_answer():
    assert "combined" not in ask("Forecast Brazil exports to 2030")


# ------------------------------------------------------------ linking rules

def insight(facet, claim, evidence, confidence=0.9, entity="IND"):
    return {"entity_iso3": entity, "entity_name": "India", "facet": facet, "claim": claim, "confidence": confidence, "reason": "test", "evidence": evidence}


EXPOSURE = insight("trade_exposure", "India ranks 15 of 226 by risk.", {"rank": 15, "countries_ranked": 226})
OUTLOOK = insight("trade_outlook", "India exports rise.", {"trend": "increasing", "metric": "exports", "forecast_values": [{"year": 2030, "predicted_value": 1.0}]}, 0.8)


def part(question, items):
    plan = intent.parse(question)
    results = {"trade_intelligence": AgentResult(agent="trade_intelligence", status="ok", envelope={"insights": items})}
    return synthesis.PartAnswer(plan=plan, results=results, response={"fused": {"findings": []}, "briefing": {"summary": [], "headline": ""}})


def test_outlook_joins_todays_position_from_one_part_with_the_forecast_from_another():
    found = synthesis.connect([part("How exposed is India", [EXPOSURE]), part("Forecast India's exports", [OUTLOOK])])["findings"]
    assert [f["title"] for f in found] == ["Today's trade exposure against the trade forecast"]
    assert found[0]["claim"] == "India ranks 15 of 226 by trade risk today, and its exports are projected rising to 2030."
    assert found[0]["confidence"] == pytest.approx(0.8)
    assert found[0]["parts"] == [1, 2]


def test_no_connection_when_one_part_already_holds_both_claims():
    # The profile part also returned the forecast, but did not ask for it, and
    # the forecast part returned nothing: there is nothing to join.
    found = synthesis.connect([part("How exposed is India", [EXPOSURE, OUTLOOK]), part("Forecast India's exports", [])])["findings"]
    assert found == []


def test_a_failed_agent_contributes_nothing():
    broken = part("Forecast India's exports", [OUTLOOK])
    broken.results["trade_intelligence"].status = "timeout"
    assert synthesis.connect([part("How exposed is India", [EXPOSURE]), broken])["findings"] == []


# ------------------------------------------------------------ the page

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_shows_the_combined_answer_above_the_parts():
    result = ask("What if China stops exporting electronics? Which bloc is Vietnam in?", {"date": DAY})
    script = (HERE / "ui_harness.js").read_text(encoding="utf8").replace("globalThis.__render = render;", "globalThis.__render = renderAnswer;")
    probe = HERE / "_ui_combined_harness.js"
    probe.write_text(script + "\nconsole.log(JSON.stringify({combined: document.getElementById('combined').textContent}));\n", encoding="utf8")
    try:
        out = subprocess.run(["node", str(probe), str(HERE.parent / "static" / "index.html"), "Trade"],
                             input=json.dumps(result), capture_output=True, text=True, encoding="utf8", check=True).stdout
    finally:
        probe.unlink()
    shown = json.loads(out.strip().splitlines()[-1])["combined"]
    assert result["combined"]["headline"] in shown
    assert "Connecting the parts" in shown
    assert "Vietnam sits in China's trading bloc" in shown
    assert "1. What if China stops exporting electronics?" in shown
