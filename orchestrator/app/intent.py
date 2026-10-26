"""Intent parsing: a natural-language question becomes a query plan.

The parser is deliberately rule-based. Every decision it makes is inspectable in
the plan it returns (``/parse`` exposes it on its own), it needs no API key, and it
behaves identically in a demo and in a test. A question it cannot place falls back
to a country profile or a global overview rather than failing.

Before parsing, the question is reformulated (reformulate.py): aliases, typos,
number words and unfamiliar phrasings are rewritten into words the parser knows.
The plan keeps the original question, the text it actually read, and every
rewrite.

A plan answers four questions:
    intent    what kind of question is this
    entities  which countries, as ISO3
    time      which year or day
    agents    which agents to ask, and why

and carries an ``understanding`` confidence: how sure the system is that it read
the question as meant. It falls with each rewrite and when the plan looks like a
misreading, such as no country found in a question that is not a global one.
It says nothing about the data; claim confidences do that.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from . import countries, reformulate
from .config import REFORMULATION_STEPS

INTENTS = ("country_profile", "bilateral", "shock", "forecast", "blocs", "events", "ranking")
ALL_AGENTS = ("soft_power", "policy_stance", "trade_intelligence", "event_summarization")

_SHOCK = re.compile(
    r"\b(what if|stops?|stopped|halts?|halted|cuts? off|embargo(?:es|ed)?|blockades?|bans?|banned|sanction(?:s|ed)?|"
    r"disrupt(?:s|ed|ion)?|shock|collapse[sd]?|shuts? down|restricts?|restrictions?)\b",
    re.I,
)
_FORECAST = re.compile(r"\b(forecast|predict(?:ion|ed)?|projection|project(?:ed)?|outlook|future|next \d+ years|by 20[3-9]\d|trajectory|will .* (?:grow|rise|fall|decline))\b", re.I)
_BLOCS = re.compile(r"\b(blocs?|alliances?|allied|aligned|alignment|camps?|non-aligned|side with|coalition)\b", re.I)
_EVENTS = re.compile(r"\b(today|yesterday|news|headlines?|happening|this week|latest events|recent events|events)\b", re.I)
_RANKING = re.compile(r"\b(which countries|what countries|who are|top \d+|most|least|rank(?:ed|ing)?|leading|largest|biggest)\b", re.I)
_BILATERAL = re.compile(r"\b(relations?|relationship|ties|between|versus|vs\.?|compare[ds]?|comparison|bilateral|dependence on|depend on)\b", re.I)

_DOMAIN = {
    "trade_intelligence": re.compile(r"\b(trade|trading|exports?|imports?|supply|suppliers?|tariffs?|economic|economy|dependen\w*|leverage|fragil\w*|sectors?)\b", re.I),
    "soft_power": re.compile(r"\b(soft powers?|influence|reputation|culture|cultural|attractiveness|image|brand|prestige)\b", re.I),
    "policy_stance": re.compile(r"\b(un |united nations|vot(?:e|es|ing)|diplomac\w*|diplomatic|conflicts?|wars?|alliances?|blocs?|stance|policy)\b", re.I),
    "event_summarization": re.compile(r"\b(news|events?|today|yesterday|happening|headlines?|right now|currently|this week)\b", re.I),
}

_SECTORS = (
    ("energy", re.compile(r"\b(energy|oil|gas|lng|fuel|petroleum|coal|crude)\b", re.I)),
    ("agriculture", re.compile(r"\b(agri\w*|food|grain|wheat|rice|crops?|fertili[sz]ers?)\b", re.I)),
    ("electronics", re.compile(r"\b(electronics?|chips?|semiconductors?|microchips?|tech(?:nology)?)\b", re.I)),
)


@dataclass
class Entity:
    iso3: str
    name: str
    matched: str


@dataclass
class TimeWindow:
    mode: str = "latest"          # latest | year | date
    year: Optional[int] = None
    date: Optional[str] = None    # YYYYMMDD
    horizon_year: Optional[int] = None


@dataclass
class QueryPlan:
    question: str
    intent: str
    entities: list[Entity]
    time: TimeWindow
    sector: str = "all"
    severity: Optional[float] = None
    metric: str = "exports"
    limit: int = 5
    trade_query: Optional[str] = None
    agents: list[str] = field(default_factory=list)
    agent_reasons: dict[str, str] = field(default_factory=dict)
    focus_agents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    read_as: Optional[str] = None        # the reformulated question, when it differs
    rewrites: list[dict] = field(default_factory=list)
    understanding: float = 1.0

    @property
    def iso3s(self) -> list[str]:
        return [entity.iso3 for entity in self.entities]

    @property
    def primary(self) -> Optional[str]:
        return self.entities[0].iso3 if self.entities else None

    def to_dict(self) -> dict:
        return asdict(self)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_time(question: str, intent_hint: str) -> TimeWindow:
    iso_date = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", question)
    if iso_date:
        try:
            parsed = date(int(iso_date.group(1)), int(iso_date.group(2)), int(iso_date.group(3)))
            return TimeWindow(mode="date", date=parsed.strftime("%Y%m%d"), year=parsed.year)
        except ValueError:
            pass
    if re.search(r"\byesterday\b", question, re.I):
        day = _today() - timedelta(days=1)
        return TimeWindow(mode="date", date=day.strftime("%Y%m%d"), year=day.year)

    years = [int(y) for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", question)]
    if years:
        future = [y for y in years if y > _today().year - 1]
        past = [y for y in years if y <= _today().year - 1]
        if future and intent_hint == "forecast":
            return TimeWindow(mode="latest", horizon_year=max(future))
        if past:
            return TimeWindow(mode="year", year=past[0])
    return TimeWindow(mode="latest")


def _severity(question: str) -> float:
    pct = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", question, re.I)
    if pct:
        return max(0.01, min(1.0, float(pct.group(1)) / 100.0))
    if re.search(r"\b(halve[sd]?|half)\b", question, re.I):
        return 0.5
    if re.search(r"\b(stops?|stopped|halts?|halted|cuts? off|embargo\w*|blockades?|bans?|banned|shuts? down|total|complete)\b", question, re.I):
        return 1.0
    return 0.5


def _sector(question: str) -> str:
    for name, pattern in _SECTORS:
        if pattern.search(question):
            return name
    return "all"


def _trade_ranking_query(question: str) -> str:
    if re.search(r"\b(bloc|blocs|alliance|camp)\b", question, re.I):
        return "blocs"
    if re.search(r"\b(dependen\w*|leverage|reliant|rely)\b", question, re.I):
        return "leverage"
    if re.search(r"\b(fragil\w*|substitut\w*|supply chains?|brittle)\b", question, re.I):
        return "fragility"
    return "risk"


def _choose_intent(question: str, entities: list[Entity]) -> str:
    n = len(entities)
    if n >= 1 and _SHOCK.search(question):
        return "shock"
    if n >= 1 and _FORECAST.search(question):
        return "forecast"
    if n >= 2:
        return "bilateral"
    if _BLOCS.search(question):
        return "blocs"
    if n == 1 and _EVENTS.search(question) and not re.search(r"\b(exposed|exposure|profile|overall|position)\b", question, re.I):
        return "events"
    if n == 0:
        return "ranking"
    return "country_profile"


_INTENT_AGENTS = {
    "country_profile": {
        "soft_power": "influence level, trend, drivers and forecast",
        "policy_stance": "UN-voting bloc, conflict record, diplomatic partners",
        "trade_intelligence": "structural risk, trade bloc, leverage, sector fragility",
        "event_summarization": "latest day of GDELT activity and counterparts",
    },
    "bilateral": {
        "soft_power": "influence of each side",
        "policy_stance": "UN-vote similarity and bloc of each side",
        "trade_intelligence": "trade bloc and dependence of each side",
        "event_summarization": "latest interactions and 1990-2024 relationship baseline",
    },
    "shock": {
        "trade_intelligence": "propagate the export disruption through the trade graph",
        "policy_stance": "diplomatic bloc of the origin and of the most exposed economies",
        "event_summarization": "what the news shows about the origin right now",
    },
    "forecast": {
        "trade_intelligence": "trade projection with automatic model selection",
        "soft_power": "5-year Kalman forecast of the influence score",
        "policy_stance": "conflict-activity trend",
    },
    "blocs": {
        "trade_intelligence": "Louvain trading blocs",
        "policy_stance": "UN-voting alliance blocs",
        "soft_power": "closest influence peers",
    },
    "events": {
        "event_summarization": "GDELT events for the day",
        "policy_stance": "bloc context for the counterparts",
        "trade_intelligence": "trade stakes with the counterparts",
    },
    "ranking": {
        "trade_intelligence": "network-wide ranking",
        "soft_power": "global soft-power leaderboard",
        "policy_stance": "alliance-bloc overview",
    },
}


_COUNTRY_REWRITES = ("capital", "endonym", "abbreviation", "combining_form", "country_spelling")


def _typed(matched: str, reformulation: reformulate.Reformulation) -> str:
    """What the user actually typed for a country that reformulation renamed."""
    for rewrite in reformulation.rewrites:
        if rewrite.kind in _COUNTRY_REWRITES and matched.lower() in rewrite.replacement.lower():
            return rewrite.original
    return matched


def _understanding(plan: QueryPlan, reformulation: reformulate.Reformulation, text: str, overrides: dict) -> float:
    """How sure the system is that the plan is what the question meant (0-1)."""
    value = reformulation.confidence
    if not overrides.get("countries") and not overrides.get("intent"):
        if not plan.entities and plan.intent == "ranking" and not _RANKING.search(text):
            value *= 0.4
            plan.notes.append("No country and no ranking cue recognised, so this may not be the question that was asked.")
        elif len(plan.entities) == 1 and plan.intent != "bilateral" and _BILATERAL.search(text):
            value *= 0.6
            plan.notes.append("The question reads like one about a relationship, but only one country was recognised.")
        elif plan.intent == "bilateral" and len(plan.entities) > 2:
            value *= 0.8
    return round(value, 3)


def parse(question: str, overrides: Optional[dict] = None, steps: Optional[Iterable[str] | str] = None) -> QueryPlan:
    """Turn a question into a query plan. ``overrides`` wins over anything parsed.

    ``steps`` picks the reformulation steps to run first; by default the ones
    in ``REFORMULATION_STEPS`` (all of them, unless configured otherwise).
    """
    overrides = {key: value for key, value in (overrides or {}).items() if value is not None}
    reformulation = reformulate.reformulate(question, REFORMULATION_STEPS if steps is None else steps)
    text = reformulation.text

    mentions = countries.find_mentions(text)
    entities = [Entity(iso3=m.iso3, name=m.name, matched=_typed(m.matched, reformulation)) for m in mentions]
    for iso3 in overrides.get("countries", []) or []:
        resolved = countries.resolve(iso3)
        if resolved and resolved not in {e.iso3 for e in entities}:
            entities.append(Entity(iso3=resolved, name=countries.name_of(resolved), matched=str(iso3)))

    intent = overrides.get("intent") or _choose_intent(text, entities)
    if intent not in INTENTS:
        intent = "country_profile" if entities else "ranking"

    time = _parse_time(text, intent)
    if overrides.get("year"):
        time = TimeWindow(mode="year", year=int(overrides["year"]))
    if overrides.get("date"):
        day = str(overrides["date"]).replace("-", "")
        time = TimeWindow(mode="date", date=day, year=int(day[:4]))

    limit_match = re.search(r"\btop (\d{1,2})\b", text, re.I)
    plan = QueryPlan(
        question=reformulation.original,
        intent=intent,
        entities=entities,
        time=time,
        sector=overrides.get("sector") or _sector(text),
        severity=float(overrides["severity"]) if "severity" in overrides else (_severity(text) if intent == "shock" else None),
        metric="imports" if re.search(r"\bimports?\b", text, re.I) else "exports",
        limit=max(1, min(20, int(limit_match.group(1)))) if limit_match else (10 if intent == "ranking" else 5),
    )
    if intent == "ranking":
        plan.trade_query = _trade_ranking_query(text)
    elif intent == "blocs":
        plan.trade_query = "blocs"

    candidates = dict(_INTENT_AGENTS[intent])
    plan.focus_agents = [agent for agent, pattern in _DOMAIN.items() if pattern.search(text)]

    requested = overrides.get("agents")
    if requested:
        chosen = [agent for agent in ALL_AGENTS if agent in requested]
        for agent in chosen:
            candidates.setdefault(agent, "requested explicitly")
        plan.notes.append("agent selection overridden by the request")
    else:
        chosen = [agent for agent in ALL_AGENTS if agent in candidates]

    if intent == "ranking" and not requested:
        # A global ranking question is about one domain; ask the agents it names,
        # or all three annual agents when it names none.
        named = [agent for agent in chosen if agent in plan.focus_agents]
        if named:
            chosen = named

    if time.mode == "year" and "event_summarization" in chosen and intent != "bilateral":
        # GDELT daily data answers "what is happening", not "what was true in 2012".
        chosen.remove("event_summarization")
        plan.notes.append(f"Events agent skipped: daily GDELT activity does not describe the year {time.year}.")

    plan.agents = chosen
    plan.agent_reasons = {agent: candidates[agent] for agent in chosen}

    if not entities and intent not in ("ranking", "blocs"):
        plan.notes.append("No country recognised in the question; answering with a global overview.")
    if len(entities) > 2 and intent == "bilateral":
        plan.notes.append(f"{len(entities)} countries mentioned; comparing the first two.")
    if time.horizon_year:
        plan.notes.append(f"Forecast horizon read as {time.horizon_year}.")

    if reformulation.changed:
        plan.read_as = text
    plan.rewrites = [rewrite.to_dict() for rewrite in reformulation.rewrites]
    plan.notes = [rewrite.note() for rewrite in reformulation.rewrites] + plan.notes
    plan.understanding = _understanding(plan, reformulation, text, overrides)
    return plan
