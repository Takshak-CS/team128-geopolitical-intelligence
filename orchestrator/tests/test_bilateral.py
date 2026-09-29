"""Bilateral questions: the Events answer leads with the pair, not the first country's day.

Recorded days (tests/record_fixtures.py):
    20260928  China is not among India's eight most active counterparts; two
              India-China events, one of them India's top event #3 ("China vs
              West Bengal", coded CHN-IND)
    20260922  four India-China events, none among India's top five
"""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app.agents.events import EventsAdapter, _involves_pair
from app.pipeline import Orchestrator
from tests.replay import ReplayTransport, load_records

RECORDS = load_records()
ROOT = Path(__file__).resolve().parents[1]
ABSENT_DAY = "20260928"


def ask(question, overrides=None, **transport_kwargs):
    transport = ReplayTransport(RECORDS, **transport_kwargs)

    async def run():
        orchestrator = Orchestrator(client=httpx.AsyncClient(transport=transport))
        try:
            return await orchestrator.ask(question, overrides)
        finally:
            await orchestrator.close()

    return asyncio.run(run()), transport


def events_insights(result):
    return result["agents"]["event_summarization"]["envelope"]["insights"]


def rendered(result, label="Events"):
    """What the real briefing UI script renders for one agent's panel."""
    if not shutil.which("node"):
        pytest.skip("node is needed to run the UI script")
    out = subprocess.run(["node", str(ROOT / "tests" / "ui_harness.js"), str(ROOT / "static" / "index.html"), label],
                         input=json.dumps(result), capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


# --------------------------------------------------------------- the question
def test_bilateral_panel_shows_the_relationship_before_the_whole_day():
    result, transport = ask("India and China relations", {"date": ABSENT_DAY})
    assert transport.missing == []
    partners = next(i for i in events_insights(result) if i["facet"] == "event_partners")["evidence"]["partners"]
    assert "CHN" not in [p["iso3"] for p in partners], "fixture premise: China is not a top counterpart that day"

    page = rendered(result)
    assert page["views"].index("relationship") < page["views"].index("day-activity")
    assert page["headings"][0] == "Relationship: India and China"
    assert page["headings"].index("Relationship: India and China") < page["headings"].index("India's whole day, all counterparts (context)")
    # Only the event whose GDELT codes are India-China is shown; India's other
    # top events of the day (a gang, a labour clash, the UK) are not.
    assert page["headlines"] == ["Top event #3: India came under pressure as China moved to occupy territory belonging to West Bengal (Goldstein score: -9.5)."]
    assert "Top events, checked against their source" not in page["headings"]
    for unrelated in ("Gang", "Worker", "United Kingdom carried"):
        assert unrelated not in " ".join(page["headlines"])


def test_a_day_with_no_joint_top_event_says_so_instead_of_showing_one():
    result, _ = ask("India and China relations", {"date": "20260922"})
    assert not [i for i in events_insights(result) if i["facet"] == "event_headline"]
    none = next(i for i in events_insights(result) if i["facet"] == "bilateral_headlines")
    assert none["claim"] == "None of India's top 5 GDELT events on 2026-09-22 involve both India and China."
    page = rendered(result)
    assert page["headlines"] == []
    assert none["claim"] in page["text"]
    assert page["views"].index("relationship") < page["views"].index("day-activity")


def test_the_pair_summary_leads_and_counts_the_pair_exactly():
    result, _ = ask("India and China relations", {"date": ABSENT_DAY})
    insights = events_insights(result)
    assert [i["facet"] for i in insights][:3] == ["bilateral_events", "event_headline", "relationship_baseline"]
    pair, activity = insights[0], next(i for i in insights if i["facet"] == "event_activity")
    assert pair["claim"].startswith("India and China appear together in 2 GDELT events on 2026-09-28, mean Goldstein -3.05 (conflictual); "
                                    "their 1990-2024 GGE baseline is broadly neutral")
    assert pair["evidence"]["count"] == 2 and pair["evidence"]["table_complete"] is True
    assert pair["confidence"] > activity["confidence"]
    section = next(s for s in result["briefing"]["sections"] if s.get("agent") == "event_summarization")
    assert [f["facets"][0] for f in section["findings"]][:3] == ["bilateral_events", "event_headline", "relationship_baseline"]


def test_a_pair_event_its_source_contradicts_is_dropped_and_named():
    key = next(k for k in RECORDS if k.startswith("event_summarization GET /article-relevance") and "term1=China" in k and "term2=West Bengal" in k)
    contradicted = {key: {"status": 200, "json": {**RECORDS[key]["json"], "article_ok": True, "link": "none",
                                                  "verdict_text": "Neither China nor West Bengal is named in this article."}}}
    result, _ = ask("India and China relations", {"date": ABSENT_DAY}, responses=contradicted)
    insights = events_insights(result)
    assert not [i for i in insights if i["facet"] == "event_headline"]
    none = next(i for i in insights if i["facet"] == "bilateral_headlines")
    assert none["claim"].endswith("involve both India and China; 1 that did was flagged as likely mis-tagged by GDELT.")
    assert insights[0]["evidence"]["excluded_mistagged"] == 1


# ------------------------------------------------------------------ matching
TABLE = [
    {"SOURCEURL": "https://a.example/border", "EventType": "Fight", "GoldsteinScale": -9.5, "Actor1CountryCode": "CHN", "Actor2CountryCode": "IND"},
    {"SOURCEURL": "https://b.example/toronto", "EventType": "Fight", "GoldsteinScale": -10.0, "Actor1CountryCode": "CAN", "Actor2CountryCode": "IND"},
]


def test_country_codes_decide_participation_not_names():
    # "West Bengal" is India by code; "China" in the text of an event coded
    # Canada-India does not make it a China event.
    assert _involves_pair({"url": "https://a.example/border", "event_type": "Fight", "score": -9.5, "actor1": "China", "actor2": "West Bengal"}, TABLE, "IND", "CHN")
    assert not _involves_pair({"url": "https://b.example/toronto", "event_type": "Fight", "score": -10.0, "actor1": "China", "actor2": "Tamil Nadu", "role": "Recipient"}, TABLE, "IND", "CHN")


def test_without_a_table_row_the_counterpart_name_is_used():
    event = {"url": "https://c.example/x", "event_type": "Consult", "score": 1.0, "role": "Recipient", "actor1": "China", "actor2": "India"}
    assert _involves_pair(event, TABLE, "IND", "CHN")
    assert not _involves_pair({**event, "actor1": "Toronto"}, TABLE, "IND", "CHN")
    assert not _involves_pair({**event, "role": "Both"}, TABLE, "IND", "CHN")


def test_a_truncated_table_makes_the_count_a_floor():
    item = EventsAdapter._pair_summary("IND", "CHN", ABSENT_DAY, [{"GoldsteinScale": 1.0, "EventType": "Consult"}], 1.0, False,
                                       {"available": True, "baseline_label": "broadly neutral", "avg_10yr": 0.02, "trend": "stable"}, 0, 0, 0.59)
    assert item["confidence"] == 0.59
    assert item["reason"].endswith("so the count is a floor")
