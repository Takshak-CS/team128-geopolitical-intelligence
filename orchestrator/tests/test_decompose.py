"""Query decomposition: compound questions split into parts, single ones never do."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app import decompose, intent
from app.pipeline import Orchestrator
from tests.replay import ReplayTransport, load_records

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE.parent / "evaluation" / "questions.json"


def parts(question, overrides=None):
    return [(p.plan.intent, p.plan.iso3s) for p in decompose.decompose(question, overrides).parts]


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What is India's soft power forecast, and what happens if China's exports drop by half?",
         [("forecast", ["IND"]), ("shock", ["CHN"])]),
        ("Forecast Brazil exports to 2030, and which bloc is Vietnam in?",
         [("forecast", ["BRA"]), ("blocs", ["VNM"])]),
        ("Compare India and Pakistan. What is happening in India today?",
         [("bilateral", ["IND", "PAK"]), ("events", ["IND"])]),
        ("How exposed is India and which countries are most dependent on trade?",
         [("country_profile", ["IND"]), ("ranking", [])]),
        ("Which bloc is Vietnam in; what is happening there?",
         [("blocs", ["VNM"]), ("events", ["VNM"])]),
    ],
)
def test_compound_questions_split_into_their_parts(question, expected):
    assert parts(question) == expected


def test_a_part_with_no_country_takes_the_country_of_another_part():
    result = decompose.decompose("How exposed is India, and what is the forecast for it?")
    assert [(p.plan.intent, p.plan.iso3s, p.carried_countries) for p in result.parts] == [
        ("country_profile", ["IND"], []),
        ("forecast", ["IND"], ["IND"]),
    ]
    assert any("carried over" in note for note in result.parts[1].plan.notes)


def test_a_global_part_does_not_take_a_country():
    result = decompose.decompose("How exposed is India and which countries are most dependent on trade?")
    assert result.parts[1].carried_countries == []


@pytest.mark.parametrize(
    "question",
    [
        "India and China relations",
        "Compare the US and Russia in 2015",
        "India vs. China trade",
        "What if China stops exporting electronics and how does that affect Vietnam?",
        "How exposed is India? How vulnerable is India?",
        "Trade between Japan and South Korea",
    ],
)
def test_questions_that_ask_one_thing_are_not_split(question):
    result = decompose.decompose(question)
    assert not result.compound
    assert result.plans[0].to_dict() == intent.parse(question).to_dict()


def test_no_benchmark_question_is_split():
    data = json.loads(QUESTIONS.read_text(encoding="utf8"))
    split = [q["text"] for g in data["groups"] for q in g["questions"] if decompose.decompose(q["text"]).compound]
    assert split == []


def test_whole_question_overrides_and_the_switch_stop_splitting():
    question = "Forecast Brazil exports to 2030, and which bloc is Vietnam in?"
    assert not decompose.decompose(question, {"intent": "forecast"}).compound
    assert not decompose.decompose(question, {"countries": ["BRA"]}).compound
    assert not decompose.decompose(question, enabled=False).compound
    # Overrides that fit every part are passed to each one.
    assert {p.plan.time.year for p in decompose.decompose(question, {"year": 2020}).parts} == {2020}


def test_parts_are_capped():
    question = "; ".join(f"How exposed is {c}" for c in ("India", "China", "Brazil", "Japan", "Kenya", "Peru"))
    result = decompose.decompose(question)
    assert len(result.parts) == decompose.MAX_PARTS
    assert any("answering the first" in note for note in result.notes)


# ------------------------------------------------------------- pipeline + UI

def ask(question):
    transport = ReplayTransport(load_records())

    async def run():
        orchestrator = Orchestrator(client=httpx.AsyncClient(transport=transport))
        try:
            return await orchestrator.ask(question)
        finally:
            await orchestrator.close()

    return asyncio.run(run())


def test_each_part_is_answered_as_if_asked_on_its_own():
    compound = ask("Forecast Brazil exports to 2030, and which bloc is Vietnam in?")
    assert [p["plan"]["intent"] for p in compound["parts"]] == ["forecast", "blocs"]
    assert compound["decomposition"]["compound"] is True
    # The top level stays the first part's answer, so older clients still work.
    assert compound["plan"]["intent"] == "forecast"
    for part, alone in zip(compound["parts"], (ask("Forecast Brazil exports to 2030"), ask("which bloc is Vietnam in?"))):
        assert part["briefing"]["headline"] == alone["briefing"]["headline"]
        assert {n: a["status"] for n, a in part["agents"].items()} == {n: a["status"] for n, a in alone["agents"].items()}
    assert [p["headline"] for p in compound["decomposition"]["parts"]] == [p["briefing"]["headline"] for p in compound["parts"]]


def test_a_single_question_has_no_parts():
    result = ask("Forecast Brazil exports to 2030")
    assert "parts" not in result and "decomposition" not in result


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_shows_a_tab_per_part():
    compound = ask("Forecast Brazil exports to 2030, and which bloc is Vietnam in?")
    script = (HERE / "ui_harness.js").read_text(encoding="utf8").replace(
        "globalThis.__render = render;", "globalThis.__render = renderAnswer;")
    probe = HERE / "_ui_parts_harness.js"
    probe.write_text(script + "\nconsole.log(JSON.stringify({parts: document.getElementById('parts').textContent, hidden: document.getElementById('parts').className}));\n", encoding="utf8")
    try:
        out = subprocess.run(["node", str(probe), str(HERE.parent / "static" / "index.html"), "Trade"],
                             input=json.dumps(compound), capture_output=True, text=True, encoding="utf8", check=True).stdout
    finally:
        probe.unlink()
    shown = json.loads(out.strip().splitlines()[-1])
    assert "1. Forecast Brazil exports to 2030" in shown["parts"]
    assert "2. which bloc is Vietnam in?" in shown["parts"]
    assert "hidden" not in shown["hidden"]
