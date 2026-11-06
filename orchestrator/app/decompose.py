"""Query decomposition: a compound question becomes several sub-questions.

The intent parser gives one plan per question, so a question that asks two
things ("What is India's soft power forecast, and what happens if China's
exports halve?") used to lose one of them: the parser picked one intent and
the other part went unanswered. Decomposition splits such a question into
sub-questions, parses each one on its own, and lets the pipeline answer each
part with its own fan-out, fusion and briefing.

Like the parser it is rule-based and conservative, because splitting a
question that should not be split is worse than not splitting:

1. Split only at clause boundaries: "?", "!", ";", a full stop before a new
   question, or "and" / "also" / "plus" / "but" / "then" before a question word
   ("..., and what if ...", "... and how ...", "... also forecast ...").
   "India and China relations" has no question word after "and", so it stays
   one bilateral question.
2. A part with no country, that does not ask for a global ranking, takes the
   countries of the nearest part that has one ("How exposed is India, and
   what is the forecast for it?"). The plan notes the carry-over.
3. The split is kept only if the parts ask different things. Parts with the
   same plan (same intent, countries and time) are merged. If every part
   matches, the question is answered as one, exactly as it was before.
4. A split is dropped if it produces a part the system cannot read (low
   understanding) when the whole question can be read.

At most MAX_PARTS parts are answered, so one question cannot fan out without
limit. ``DECOMPOSITION=off`` turns it off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import intent, reformulate
from .config import DECOMPOSITION, REFORMULATION_STEPS

MAX_PARTS = 4

# Below this a part counts as unreadable (the briefing's own warning threshold).
LOW_UNDERSTANDING = 0.5

# Overrides that describe the whole question, not one part of it. With one of
# these the question is not split.
_WHOLE_QUESTION_OVERRIDES = ("intent", "countries")

_QUESTION_WORD = (
    r"(?:what|what's|whats|how|how's|which|who|will|would|could|can|is|are|does|do|did|where|why|when|"
    r"tell|show|give|forecast|predict|compare|list|rank)"
)
_BOUNDARY = re.compile(
    r"[?!;]+\s*"                                                   # end of a question
    r"|\.\s+(?=" + _QUESTION_WORD + r"\b)"                          # full stop, then a new question
    r"|,?\s+\b(?:and(?:\s+also)?|also|plus|but|then)\b,?\s+(?=" + _QUESTION_WORD + r"\b)",
    re.I,
)
# A part that points back at the previous clause rather than starting a new
# question ("What if China stops exporting chips, and how does that affect
# Vietnam?" is one shock question). It stays joined to the clause before it.
_DEPENDENT = re.compile(
    r"\b(?:that|this|these|those)\b(?!\s+(?:week|year|month|day|country|countries|nation)\b)"
    r"|\b(?:affects?|affected|impacts?|impacted|hits?|consequences?|effects? on|mean for|knock-on)\b",
    re.I,
)
# A part that points back at a country named earlier.
_PRONOUN = re.compile(r"\b(it|its|it's|they|their|them|there|that country|this country|the country)\b", re.I)


@dataclass
class Part:
    text: str                               # the sub-question as typed
    plan: intent.QueryPlan
    carried_countries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "question": self.text,
            "intent": self.plan.intent,
            "countries": self.plan.iso3s,
            "carried_countries": self.carried_countries,
        }


@dataclass
class Decomposition:
    question: str
    parts: list[Part]
    notes: list[str] = field(default_factory=list)

    @property
    def compound(self) -> bool:
        return len(self.parts) > 1

    @property
    def plans(self) -> list[intent.QueryPlan]:
        return [part.plan for part in self.parts]

    def to_dict(self) -> dict:
        return {"question": self.question, "compound": self.compound, "parts": [p.to_dict() for p in self.parts], "notes": self.notes}


def split(question: str) -> list[str]:
    """Candidate sub-questions, at clause boundaries only. One item if there are none."""
    text = " ".join(str(question or "").split())
    pieces, start = [], 0
    for match in _BOUNDARY.finditer(text):
        piece = text[start:match.end()].strip() if match.group(0).strip().startswith(("?", "!")) else text[start:match.start()].strip()
        pieces.append(piece)
        start = match.end()
    pieces.append(text[start:].strip())
    pieces = [p.strip(" ,;.") for p in pieces]
    pieces = [p for p in pieces if p]

    # A fragment of one or two words ("and?", "why") is not a question on its
    # own, and a clause that refers back to the one before it belongs with it.
    merged: list[str] = []
    for piece in pieces:
        if merged and _DEPENDENT.search(piece):
            merged[-1] = f"{merged[-1]} and {piece}"
        elif merged and len(piece.split()) < 3 and not _names_a_country(piece):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged or [text]


def _names_a_country(text: str) -> bool:
    from . import countries
    return bool(countries.find_mentions(text))


def _signature(plan: intent.QueryPlan) -> tuple:
    return (plan.intent, tuple(plan.iso3s), plan.time.mode, plan.time.year, plan.time.date, plan.time.horizon_year, plan.sector)


def _asks_globally(text: str, steps) -> bool:
    read = reformulate.reformulate(text, steps).text
    return bool(intent._RANKING.search(read))


def decompose(question: str, overrides: Optional[dict] = None, steps: Optional[Iterable[str] | str] = None, enabled: Optional[bool] = None) -> Decomposition:
    """Split ``question`` into sub-questions with a plan each.

    A question that is not compound comes back as one part whose plan is exactly
    ``intent.parse(question, overrides, steps)``.
    """
    overrides = {key: value for key, value in (overrides or {}).items() if value is not None}
    steps = REFORMULATION_STEPS if steps is None else steps
    whole = Decomposition(question=question, parts=[Part(text=question, plan=intent.parse(question, overrides, steps))])

    if not (DECOMPOSITION if enabled is None else enabled) or any(overrides.get(key) for key in _WHOLE_QUESTION_OVERRIDES):
        return whole
    texts = split(question)
    if len(texts) < 2:
        return whole

    notes: list[str] = []
    if len(texts) > MAX_PARTS:
        notes.append(f"The question has {len(texts)} parts; answering the first {MAX_PARTS}.")
        texts = texts[:MAX_PARTS]

    plans = [intent.parse(text, overrides, steps) for text in texts]

    # Carry countries into parts that name none and do not ask a global question.
    parts: list[Part] = []
    for i, (text, plan) in enumerate(zip(texts, plans)):
        carried: list[str] = []
        if not plan.entities and (_PRONOUN.search(text) or not _asks_globally(text, steps)):
            donors = [p for p in reversed(plans[:i]) if p.entities] + [p for p in plans[i + 1:] if p.entities]
            if donors:
                # A bilateral donor gives both countries only to a part that is itself about a pair.
                carried = donors[0].iso3s if donors[0].intent == "bilateral" and intent._BILATERAL.search(text) else donors[0].iso3s[:1]
                plan = intent.parse(text, {**overrides, "countries": carried}, steps)
                names = ", ".join(e.name for e in plan.entities)
                plan.notes.append(f"Part of a longer question; {names} carried over from another part.")
        parts.append(Part(text=text, plan=plan, carried_countries=carried))

    # Merge parts that ask the same thing.
    unique: list[Part] = []
    seen: dict[tuple, Part] = {}
    for part in parts:
        key = _signature(part.plan)
        if key in seen:
            seen[key].text = f"{seen[key].text} {part.text}"
            continue
        seen[key] = part
        unique.append(part)
    if len(unique) < 2:
        return whole

    if whole.parts[0].plan.understanding >= LOW_UNDERSTANDING and any(p.plan.understanding < LOW_UNDERSTANDING for p in unique):
        return whole

    for part in unique:
        part.plan.question = part.text
    notes.append(f"Answered as {len(unique)} separate questions: " + " | ".join(f'"{p.text}" ({p.plan.intent})' for p in unique))
    return Decomposition(question=question, parts=unique, notes=notes)
