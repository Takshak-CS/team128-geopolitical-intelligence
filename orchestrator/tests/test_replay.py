"""The whole pipeline against real agent responses recorded from the live services."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import AgentConfig, load_agents
from app.contract import validate_envelope
from app.pipeline import Orchestrator
from tests.replay import ReplayTransport, load_records

DAY = "20260922"
RECORDS = load_records()


def ask(question, overrides=None, configs=None, **transport_kwargs):
    transport = ReplayTransport(RECORDS, **transport_kwargs)

    async def run():
        orchestrator = Orchestrator(configs=configs, client=httpx.AsyncClient(transport=transport))
        try:
            return await orchestrator.ask(question, overrides)
        finally:
            await orchestrator.close()

    return asyncio.run(run()), transport


def statuses(result):
    return {name: agent["status"] for name, agent in result["agents"].items()}


@pytest.mark.parametrize(
    "question, overrides",
    [
        ("How exposed is India right now?", {"date": DAY}),
        ("India and China relations", {"date": DAY}),
        ("What if China stops exporting electronics?", {"date": DAY}),
        ("Which countries are most dependent on trade?", {}),
        ("Forecast Brazil exports to 2030", {}),
        ("Which bloc is Vietnam in?", {}),
        ("What is happening in Iran?", {"date": DAY}),
        ("Compare the US and Russia in 2015", {}),
    ],
)
def test_every_recorded_question_is_answered_by_every_selected_agent(question, overrides):
    result, transport = ask(question, overrides)
    assert transport.missing == []
    assert set(statuses(result).values()) == {"ok"}, statuses(result)
    for name, agent in result["agents"].items():
        assert validate_envelope(agent["envelope"]) == [], name
        for item in agent["envelope"]["insights"]:
            assert item["entity_iso3"] is None or len(item["entity_iso3"]) == 3
    assert result["fused"]["findings"]
    assert result["fused"]["contract_issues"] == {}
    assert result["briefing"]["summary"]


def test_india_uses_the_policy_models_own_bloc_not_the_hard_coded_label():
    result, _ = ask("How exposed is India right now?", {"date": DAY})
    policy = result["agents"]["policy_stance"]["envelope"]["insights"]
    bloc = next(i for i in policy if i["facet"] == "diplomatic_alignment")
    # The module publishes India as Non-Aligned via MANUAL_OVERRIDES; its own
    # vote model (exposed by /compare-insight) places India with China.
    assert bloc["evidence"]["provenance"] == "override_replaced"
    assert bloc["evidence"]["published_bloc"] == "Non-Aligned"
    assert bloc["evidence"]["model_bloc"] == "China-Centered Bloc"

    alignment = next(f for f in result["fused"]["findings"] if "trade_alignment" in f["facets"] and f["kind"] != "insight")
    assert alignment["kind"] == "corroboration"
    assert "China-anchored bloc" in alignment["claim"]
    assert "hard-coded" in alignment["caveat"]
    assert result["time_alignment"]["aligned_year"] == 2024
    assert result["time_alignment"]["served"]["event_summarization"] == "2026-09-22"


def test_policy_bloc_provenance_is_labelled():
    result, _ = ask("Which bloc is Vietnam in?")
    policy = result["agents"]["policy_stance"]["envelope"]["insights"]
    alignment = next(i for i in policy if i["facet"] == "diplomatic_alignment")
    assert alignment["evidence"]["provenance"] in {"vote_model", "anchor", "manual_override", "fallback_rule"}
    assert alignment["reason"].startswith("bloc provenance:")


def test_shock_labels_exposed_economies_by_diplomatic_camp():
    result, _ = ask("What if China stops exporting electronics?", {"date": DAY})
    cross = [f for f in result["fused"]["findings"] if f["kind"] == "cross_agent"]
    assert any("most exposed" in f["claim"] for f in cross)


def test_a_down_agent_degrades_the_briefing_instead_of_failing_it():
    result, _ = ask("How exposed is India right now?", {"date": DAY}, down=["policy_stance"])
    assert statuses(result)["policy_stance"] == "unavailable"
    assert statuses(result)["trade_intelligence"] == "ok"
    assert "Policy Stance: unavailable" in result["briefing"]["coverage"]
    assert not [f for f in result["fused"]["findings"] if "policy_stance" in f["agents"]]


def test_a_slow_agent_times_out_and_the_rest_still_answer():
    configs = load_agents()
    events = configs["event_summarization"]
    configs["event_summarization"] = AgentConfig(events.name, events.base_url, 0.2, events.dashboard_url)
    result, _ = ask("How exposed is India right now?", {"date": DAY}, configs=configs, slow=["event_summarization"], delay=10.0)
    assert statuses(result)["event_summarization"] in {"timeout", "error"}
    assert statuses(result)["soft_power"] == "ok"
    assert result["latency_ms"] < 8000


def test_events_falls_back_a_day_when_gdelt_has_not_published(monkeypatch):
    from app.agents import events as events_module

    class FixedNow(events_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 24, 6, 0, tzinfo=tz)  # before the 23rd's export is published

    monkeypatch.setattr(events_module, "datetime", FixedNow)
    recorded_key = next(k for k in RECORDS if k.startswith("event_summarization POST /analyze") and '"country_code": "IND"' in k)
    unpublished = {recorded_key.replace(DAY, "20260923"): {"status": 404, "json": {"detail": "No GDELT data found for 20260923."}}}
    result, _ = ask("How exposed is India right now?", {"agents": ["event_summarization"]}, responses=unpublished)
    events = result["agents"]["event_summarization"]
    assert events["status"] == "ok"  # a handled fallback is not a partial failure
    assert any("20260923 not published" in note for note in events["notes"])
    assert events["envelope"]["metadata"]["date"] == DAY


# ---------------------------------------------------------------- HTTP API
@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        test_client.app.state.orchestrator = Orchestrator(client=httpx.AsyncClient(transport=ReplayTransport(RECORDS)))
        yield test_client


def test_ask_endpoint(client):
    response = client.post("/ask", json={"question": "India and China relations", "date": "2026-09-22"})
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["intent"] == "bilateral"
    assert body["briefing"]["headline"].startswith("India and China")


def test_ask_rejects_unknown_fields_and_bad_values(client):
    assert client.post("/ask", json={"question": "India", "yr": 2020}).status_code == 422
    assert client.post("/ask", json={"question": "India", "date": "22/09/2026"}).status_code == 422
    assert client.post("/ask", json={"question": "India", "agents": ["weather"]}).status_code == 422
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_parse_endpoint_does_not_call_agents_beyond_alignment(client):
    body = client.post("/parse", json={"question": "What if Russia cuts energy exports by 40%?"}).json()
    assert body["plan"]["intent"] == "shock"
    assert body["plan"]["severity"] == pytest.approx(0.4)
    assert body["plan"]["sector"] == "energy"


def test_ui_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Geopolitical Briefing" in response.text
