from datetime import date

import pytest

from app import briefing, intent, reformulate
from evaluation import run


@pytest.fixture(autouse=True)
def reference_day(monkeypatch):
    monkeypatch.setattr(intent, "_today", lambda: date(2026, 10, 26))


def read(question, steps=None):
    return reformulate.reformulate(question, steps)


# ------------------------------------------------------------------- steps
@pytest.mark.parametrize(
    "question, expected, kind",
    [
        ("Which camp does Hanoi belong to?", "Which camp does Vietnam belong to?", "capital"),
        ("How vulnerable is Bharat at the moment?", "How vulnerable is India at the moment?", "endonym"),
        ("ROK and Japan relations", "South Korea and Japan relations", "abbreviation"),
        ("compare the usa and Russia", "compare the United States and Russia", "abbreviation"),
        ("Sino-Indian relations", "China-India relations", "combining_form"),
        ("Bogotá's trade exposure", "Colombia's trade exposure", "capital"),
    ],
)
def test_aliases_become_country_names(question, expected, kind):
    result = read(question, "aliases")
    assert result.text == expected
    assert [r.kind for r in result.rewrites] == [kind]


def test_a_capital_inside_a_known_name_is_left_alone():
    assert not read("New Delhi and Beijing ties").rewrites
    assert read("Delhi and Beijing ties").text == "India and Beijing ties"


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Indai exposure", "India exposure"),
        ("which bloc is vietnma in", "which bloc is Vietnam in"),
        ("whats happening in iarn", "whats happening in Iran"),
        ("how exposed is the untied kingdom", "how exposed is the United Kingdom"),
        ("india chian ties", "india China ties"),
    ],
)
def test_misspelt_country_names_are_corrected_when_one_is_missing(question, expected):
    result = read(question, "spelling")
    assert result.text == expected
    assert all(r.kind == "country_spelling" for r in result.rewrites)


def test_domain_words_are_corrected_and_word_forms_marked_as_such():
    result = read("forcast brazil exports to 2030", "spelling")
    assert result.text == "forecast brazil exports to 2030"
    assert result.rewrites[0].kind == "word_spelling"
    assert read("Japan forecasts", "spelling").rewrites[0].kind == "word_form"


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Where will Japan's exports be in five years?", "Where will Japan's exports be by 2031?"),
        ("Japan export forecast for the next 5 years", "Japan export forecast by 2031"),
        ("japanese exports 5 yrs out", "japanese exports by 2031"),
        ("a decade from now", "by 2036"),
    ],
)
def test_relative_years_count_from_today(question, expected):
    assert read(question, "numbers").text == expected


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Latest on Tehran", "latest news on Tehran"),
        ("vietnam - which side is it on", "vietnam - which bloc is it on"),
        ("what blocks exist", "what blocs exist"),
        ("Who relies most heavily on a single trade partner?", "Who is dependent most heavily on a single trade partner?"),
        ("What will Brazil's exports look like in 2030?", "What will Brazil's exports look like by 2030?"),
        ("Moscow reduces fuel exports by half - impact?", "What if Moscow reduces fuel exports by half - impact?"),
        ("Simulate a 50 percent drop in Russian energy exports", "What if 50 percent drop in Russian energy exports"),
        ("What happens if Saudi Arabia cuts oil production by 20%?", "What if Saudi Arabia cuts oil production by 20%?"),
    ],
)
def test_phrasings_map_to_parser_vocabulary(question, expected):
    assert read(question, "phrasing").text.lower() == expected.lower()


# ------------------------------------------------------------------ guards
@pytest.mark.parametrize(
    "question",
    [
        "iron exports from Australia",          # iron is one edit from Iran
        "green energy in Europe",               # green is one edit from Greek
        "child labour in supply chains",        # child is one edit from Chile
        "macro outlook for India",              # macro is one edit from Macao
        "What is the spin on Iran?",            # spin is one edit from Spain
        "Indo-Pacific strategy of Japan",       # not a country after the hyphen
        "Sino-Tibetan languages",
        "Paris Agreement and India",            # a treaty, not France
        "Doha Round trade talks",               # a WTO round, not Qatar
        "Brussels trade policy",                # usually the EU, so not mapped
        "How did India's exports drop in 2020?",  # history, not a scenario
        "Why did Russia cut gas supply to Europe?",
        "What if Russia cuts energy exports by 40%?",  # already a scenario
        "Forecast Brazil exports to 2030",      # already a forecast
        "Compare the US and Russia in 2015",    # a past year stays a time window
    ],
)
def test_questions_that_must_not_be_rewritten(question):
    result = read(question)
    assert result.rewrites == [] and result.text == question


def test_no_original_benchmark_question_is_rewritten():
    originals = [q["text"] for group in run.load_questions()["groups"] for q in group["questions"] if q["kind"] == "original"]
    assert {q: read(q).rewrites for q in originals if read(q).rewrites} == {}


def test_steps_can_be_switched_off():
    assert read("How vulnerable is Bharat?", "none").text == "How vulnerable is Bharat?"
    assert reformulate.resolve_steps("spelling,aliases") == ("aliases", "spelling")
    assert reformulate.resolve_steps(None) == reformulate.STEPS
    with pytest.raises(ValueError):
        reformulate.resolve_steps("synonyms")


# ------------------------------------------------------------- the plan
def test_plan_keeps_the_question_as_asked_and_what_was_read():
    plan = intent.parse("How vulnerable is Bharat at the moment?")
    assert plan.question == "How vulnerable is Bharat at the moment?"
    assert plan.read_as == "How vulnerable is India at the moment?"
    assert plan.iso3s == ["IND"] and plan.intent == "country_profile"
    assert plan.entities[0].matched == "Bharat"
    assert plan.notes[0] == 'Read "Bharat" as "India" (endonym of India).'
    assert plan.understanding == pytest.approx(0.95)


def test_a_clear_question_is_fully_understood():
    plan = intent.parse("How exposed is India right now?")
    assert plan.read_as is None and plan.rewrites == [] and plan.understanding == 1.0


def test_understanding_falls_when_the_plan_looks_like_a_misreading():
    lost = intent.parse("Where does Lagos stand overall?")  # Lagos is a city, not a capital
    assert lost.iso3s == [] and lost.understanding == pytest.approx(0.4)
    half = intent.parse("Tell me about relations with Peru")  # a relationship with one side
    assert half.understanding == pytest.approx(0.6)
    ranking = intent.parse("Which countries are most dependent on trade?")
    assert ranking.understanding == 1.0  # no country, but a ranking question


def test_reformulation_can_be_switched_off_per_parse():
    plan = intent.parse("How vulnerable is Bharat at the moment?", steps="none")
    assert plan.iso3s == [] and plan.read_as is None


def test_briefing_shows_what_was_read_and_warns_when_unsure():
    plan = intent.parse("How vulnerable is Bharat at the moment?")
    brief = briefing.compose(plan, {"findings": []}, {}, {})
    assert brief["understanding"]["read_as"] == "How vulnerable is India at the moment?"
    assert "_Read as: How vulnerable is India at the moment? (understanding 0.95)_" in brief["markdown"]
    assert not brief["understanding"]["low"]

    unsure = briefing.compose(intent.parse("Where does Lagos stand overall?"), {"findings": []}, {}, {})
    assert unsure["understanding"]["low"]
    assert "may not be the question that was asked" in unsure["markdown"]
