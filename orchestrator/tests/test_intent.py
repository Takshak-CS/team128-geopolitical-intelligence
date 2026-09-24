import pytest

from app import intent


@pytest.mark.parametrize(
    "question, expected_intent, expected_countries",
    [
        ("How exposed is India right now?", "country_profile", ["IND"]),
        ("India and China relations", "bilateral", ["IND", "CHN"]),
        ("What if China stops exporting electronics?", "shock", ["CHN"]),
        ("Sanctions on Russia", "shock", ["RUS"]),
        ("Forecast Brazil exports to 2030", "forecast", ["BRA"]),
        ("Which bloc is Vietnam in?", "blocs", ["VNM"]),
        ("What is happening in Iran?", "events", ["IRN"]),
        ("Which countries are most dependent on trade?", "ranking", []),
        ("Tell me about Latin America", "ranking", []),
    ],
)
def test_intent_and_entities(question, expected_intent, expected_countries):
    plan = intent.parse(question)
    assert plan.intent == expected_intent
    assert plan.iso3s == expected_countries


def test_profile_asks_all_four_agents_with_a_reason_each():
    plan = intent.parse("How exposed is India right now?")
    assert plan.agents == list(intent.ALL_AGENTS)
    assert set(plan.agent_reasons) == set(plan.agents)


def test_shock_reads_severity_and_sector():
    assert intent.parse("What if China stops exporting electronics?").severity == 1.0
    assert intent.parse("What if Russia cuts energy exports by 40%?").severity == pytest.approx(0.4)
    assert intent.parse("What if Russia's oil exports halve?").severity == 0.5
    assert intent.parse("What if Russia's oil exports halve?").sector == "energy"
    assert intent.parse("sanctions on Iran").severity == 0.5


def test_ranking_picks_the_trade_query_from_wording():
    assert intent.parse("Which countries are most dependent on trade?").trade_query == "leverage"
    assert intent.parse("Which countries have the most fragile supply chains?").trade_query == "fragility"
    assert intent.parse("Which countries are most exposed?").trade_query == "risk"


def test_past_year_is_a_time_window_future_year_is_a_forecast_horizon():
    plan = intent.parse("Compare the US and Russia in 2015")
    assert (plan.time.mode, plan.time.year) == ("year", 2015)
    plan = intent.parse("Forecast Brazil exports to 2030")
    assert (plan.time.mode, plan.time.horizon_year) == ("latest", 2030)


def test_events_agent_is_skipped_for_a_historical_year():
    plan = intent.parse("How exposed was India in 2012?")
    assert "event_summarization" not in plan.agents
    assert any("2012" in note for note in plan.notes)


def test_iso_date_selects_date_mode():
    plan = intent.parse("What is happening in Iran on 2026-09-22?")
    assert (plan.time.mode, plan.time.date) == ("date", "20260922")


def test_overrides_win():
    plan = intent.parse("How exposed is India?", {"agents": ["trade_intelligence"], "year": 2019, "sector": "energy"})
    assert plan.agents == ["trade_intelligence"]
    assert (plan.time.mode, plan.time.year, plan.sector) == ("year", 2019, "energy")
    plan = intent.parse("tell me about it", {"countries": ["JPN"], "intent": "blocs"})
    assert plan.iso3s == ["JPN"] and plan.intent == "blocs"


def test_imports_metric():
    assert intent.parse("Forecast India's imports").metric == "imports"
    assert intent.parse("Forecast India's exports").metric == "exports"
