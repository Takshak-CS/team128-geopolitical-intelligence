"""Events adapter: themes, domestic split, headline verification, GGE baselines.

Unit tests build the adapter's claims from hand-made payloads; the replay tests
run the whole pipeline on responses recorded from the live Events service
(20260922), which include a headline its source article does not support.
"""

import asyncio

import httpx

from app import fusion
from app.agents.base import AgentResult
from app.agents.events import EventsAdapter, _slug_check
from app.contract import envelope, insight
from app.intent import parse
from app.pipeline import Orchestrator
from tests.replay import ReplayTransport, load_records

DAY = "20260922"
RECORDS = load_records()
ONTARIO = "https://www.northbaynipissing.com/news/ontario-gas-price-prediction-for-sept-30/article_82cca2f2-0bbc-5b58-98bd"
EVENT = {"rank": 3, "actor1": "Israel", "actor2": "Iran", "event_type": "Fight", "score": -10.0, "tone": "highly conflictual",
         "url": ONTARIO, "sentence": "**Israel** fought **Iran**.", "num_articles": 60}


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


# ------------------------------------------------------------ URL fallback
def test_slug_check_flags_a_descriptive_url_that_names_neither_country():
    assert _slug_check(ONTARIO, "Israel", "Iran") == "none"


def test_slug_check_accepts_adjectival_forms():
    assert _slug_check("https://x.com/world/iranian-drones-strike-near-gulf-shipping-lane", "Iran", "United States") == "named"


def test_slug_check_does_not_judge_opaque_urls_or_non_country_actors():
    assert _slug_check("http://www.jpost.com/middle-east/article-909972", "Iran", "Iraq") is None
    assert _slug_check("https://x.com/news/man-arrested-after-downtown-stabbing", "Police", "Police") is None
    assert _slug_check(ONTARIO, "an unidentified party", "Iran") is None


# ------------------------------------------------------ headline verification
def headline(check):
    return EventsAdapter._headline_insight("IRN", DAY, EVENT, check, 0.6)


def test_an_article_naming_both_actors_verifies_the_event():
    item = headline({"article_ok": True, "link": "together", "verdict_text": "Both are named together in the article.", "best_snippet": "..."})
    assert item["evidence"]["verification"]["status"] == "verified"
    assert item["confidence"] == 0.55
    assert "caveat" not in item


def test_an_article_naming_neither_actor_flags_the_event_as_mis_tagged():
    item = headline({"article_ok": True, "link": "none", "verdict_text": "Neither Israel nor Iran is named in this article."})
    assert item["claim"].startswith("Likely mis-tagged by GDELT: event #3")
    assert item["evidence"]["verification"] == {"status": "mistagged", "method": "article_text", "link": "none",
                                                "verdict": "Neither Israel nor Iran is named in this article.", "snippet": None}
    assert item["confidence"] == 0.15
    assert item["caveat"]


def test_a_blocked_article_falls_back_to_its_url():
    # The real case: the site answers 403, so the module cannot read the article.
    item = headline({"article_ok": False, "link": "unavailable", "verdict_text": "The article text couldn't be retrieved."})
    verification = item["evidence"]["verification"]
    assert (verification["status"], verification["method"]) == ("mistagged", "url_only")
    assert "ontario gas price prediction sept" in verification["verdict"]
    assert item["confidence"] <= 0.2


def test_a_failed_check_leaves_the_event_unverified_not_flagged():
    item = headline(None)
    assert item["evidence"]["verification"]["status"] == "unverified"
    assert item["claim"].startswith("Top event #3")
    assert item["caveat"]


# --------------------------------------------------- themes and domestic split
def payload(**extra):
    return {"cluster_counts": {"Diplomatic Cooperation": 60, "Conflict & Violence": 40}, "domestic": {"total": 10, "avg_goldstein": -1.0},
            "international": {"total": 90, "avg_goldstein": 0.5}, **extra}


def test_themes_state_the_modules_cluster_validation():
    quality = {"silhouette": 0.54, "silhouette_null": -0.05, "stability_ari": 0.88, "label": "strong structure", "weak": False}
    item = EventsAdapter._themes_insight("IRN", DAY, payload(cluster_quality=quality), 0.6)
    assert "Diplomatic Cooperation 60%" in item["claim"]
    assert "silhouette 0.54 vs -0.05 on shuffled data, stability across seeds 0.88 (strong structure)" in item["claim"]
    assert "caveat" not in item


def test_weak_or_missing_cluster_validation_lowers_confidence_and_says_so():
    weak = EventsAdapter._themes_insight("IRN", DAY, payload(cluster_quality={"silhouette": 0.1, "silhouette_null": 0.05, "label": "weak", "weak": True}), 0.6)
    assert weak["confidence"] <= 0.35 and "tentative" in weak["caveat"]
    unscored = EventsAdapter._themes_insight("IRN", DAY, payload(cluster_quality=None), 0.6)
    assert unscored["confidence"] <= 0.4 and "not validate" in unscored["caveat"]


def test_domestic_split_carries_the_counting_caveat_and_stays_low_confidence():
    item = EventsAdapter._domestic_insight("IRN", DAY, payload(), 100, 0.6)
    assert item["claim"].startswith("10 of 100 events are domestic to Iran")
    assert item["confidence"] == 0.4
    assert "floor" in item["caveat"]


# ------------------------------------------------------------------ replay
def test_iran_brings_every_events_claim_type():
    result, transport = ask("What is happening in Iran?", {"date": DAY})
    assert transport.missing == []
    assert result["agents"]["event_summarization"]["status"] == "ok"
    facets = [i["facet"] for i in events_insights(result)]
    for facet in ("event_activity", "event_partners", "event_themes", "event_domestic_split"):
        assert facets.count(facet) == 1, facet
    assert facets.count("event_headline") == 3
    baselines = [i for i in events_insights(result) if i["facet"] == "relationship_baseline"]
    assert len(baselines) == 3
    assert all(b["evidence"]["series"] and "today" in b["evidence"] for b in baselines)
    # All three headlines survive fusion's dedupe.
    fused_headlines = [f for f in result["fused"]["findings"] if f["facets"] == ["event_headline"]]
    assert len(fused_headlines) == 3


def test_a_mis_tagged_headline_is_flagged_and_kept_out_of_the_summary():
    result, _ = ask("How exposed is India right now?", {"date": DAY})
    flagged = [i for i in events_insights(result) if (i["evidence"].get("verification") or {}).get("status") == "mistagged"]
    assert flagged, "the recorded India headlines include one its article does not support"
    assert all(i["claim"].startswith("Likely mis-tagged") and i["confidence"] <= 0.2 for i in flagged)
    assert not any("mis-tagged" in line for line in result["briefing"]["summary"])
    # Its caveat stays on the claim, not in the page-level caveats.
    assert not any("mis-tagged" in c for c in result["briefing"]["caveats"])


def test_a_pair_missing_from_gge_is_a_note_not_a_failure():
    result, _ = ask("What if China stops exporting electronics?", {"date": DAY})
    events = result["agents"]["event_summarization"]
    assert events["status"] == "ok"
    assert "No GGE 1990-2024 series for: China-Taiwan." in events["notes"]


def test_a_failing_relevance_check_does_not_degrade_the_events_agent():
    broken = {key: {"status": 500, "json": {"detail": "boom"}} for key in RECORDS if key.startswith("event_summarization GET /article-relevance")}
    result, _ = ask("What is happening in Iran?", {"date": DAY}, responses=broken)
    assert result["agents"]["event_summarization"]["status"] == "ok"
    headlines = [i for i in events_insights(result) if i["facet"] == "event_headline"]
    assert [h["evidence"]["verification"]["status"] for h in headlines] == ["unverified"] * 3


# ------------------------------------------------------------ contract/fusion
def test_an_insight_caveat_reaches_its_finding():
    item = insight("IRN", "claim", 0.1, 0.4, "reason", {}, facet="event_domestic_split", caveat="a floor, not an estimate")
    assert item["caveat"] == "a floor, not an estimate"
    assert "caveat" not in insight("IRN", "claim", 0.1, 0.4, "reason")
    result = AgentResult(agent="event_summarization", status="ok", envelope=envelope("event_summarization", [item]))
    fused = fusion.fuse(parse("What is happening in Iran?"), {"event_summarization": result})
    assert fused["findings"][0]["caveat"] == "a floor, not an estimate"


def test_what_happened_questions_lead_with_the_day_not_the_baseline():
    result, _ = ask("What is happening in Iran?", {"date": DAY})
    events_line = next(line for line in result["briefing"]["summary"] if "[Events, conf" in line)
    assert events_line.startswith("2026-09-22: ")
