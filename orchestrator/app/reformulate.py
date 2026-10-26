"""Query reformulation: rewrite a question into words the intent parser knows.

Analysts ask the same question many ways. The parser (intent.py) recognises one
vocabulary: country names and a gazetteer of aliases, and fixed cue words for
each intent. "How vulnerable is Bharat?", "Indai exposure" and "Moscow reduces
fuel exports by half" all lose their meaning before this step: the first two get
no country and fall back to a global overview, the third is read as a profile
instead of a shock. docs/EVALUATION.md measures how often that happens.

Reformulation runs before parsing and makes small, inspectable rewrites, in four
steps:

    aliases    capitals, endonyms, abbreviations and combining forms become country
               names: "Hanoi" -> Vietnam, "Bharat" -> India, "ROK" -> South Korea,
               "Sino-Indian" -> China-India
    spelling   a misspelt country name, only when the question seems to be missing a
               country ("Indai" -> India), and misspelt domain words ("forcast")
    numbers    number words and relative years: "in five years" -> "by 2031"
    phrasing   phrasings the parser has no rule for, mapped to ones it has:
               "latest on" -> "latest news on", "which side" -> "which bloc",
               "X reduces exports by half" -> "What if X reduces exports by half"

Every rewrite records what changed, why, and how sure the step is. The parser
reads the rewritten question; the plan keeps the original, the rewritten text
and the rewrites, and the briefing shows them, so a misreading is visible rather
than silent.

Like the parser, this is deliberately rule-based: deterministic, unit-tested, no
API key, and the same in a demo as in a test.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Callable, Iterable, Optional

from . import countries

STEPS = ("aliases", "spelling", "numbers", "phrasing")

# How sure each kind of rewrite is. The product over a question's rewrites is the
# reformulation part of the plan's understanding confidence (intent.parse).
CONFIDENCE = {
    "endonym": 0.95,
    "combining_form": 0.95,
    "abbreviation": 0.9,
    "capital": 0.9,
    "country_spelling": 0.8,
    "word_spelling": 0.9,
    "word_form": 0.95,
    "number_word": 0.95,
    "relative_year": 0.9,
    "lexicon": 0.9,
    "future_year": 0.85,
    "scenario": 0.8,
}


@dataclass
class Rewrite:
    step: str
    kind: str
    original: str
    replacement: str
    reason: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)

    def note(self) -> str:
        return f"Read \"{self.original}\" as \"{self.replacement}\" ({self.reason})."


@dataclass
class Reformulation:
    original: str
    text: str
    rewrites: list[Rewrite] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text != self.original

    @property
    def confidence(self) -> float:
        value = 1.0
        for rewrite in self.rewrites:
            value *= rewrite.confidence
        return value


# ------------------------------------------------------------------ tables
# A capital that usually names something other than its country in this domain
# is left out: Brussels (the EU), The Hague (the international courts), Jerusalem
# (contested), Male and Victoria (English words), Georgetown, San Jose and Sofia
# (other places and names).
CAPITALS = {
    "ottawa": "CAN", "havana": "CUB", "port-au-prince": "HTI", "santo domingo": "DOM", "nassau": "BHS",
    "kingston": "JAM", "port of spain": "TTO", "tegucigalpa": "HND", "managua": "NIC", "san salvador": "SLV",
    "bogota": "COL", "caracas": "VEN", "paramaribo": "SUR", "quito": "ECU", "lima": "PER", "la paz": "BOL",
    "asuncion": "PRY", "santiago": "CHL", "buenos aires": "ARG", "montevideo": "URY", "brasilia": "BRA",
    "london": "GBR", "dublin": "IRL", "amsterdam": "NLD", "paris": "FRA", "bern": "CHE",
    "berne": "CHE", "madrid": "ESP", "lisbon": "PRT", "berlin": "DEU", "warsaw": "POL", "vienna": "AUT",
    "budapest": "HUN", "prague": "CZE", "bratislava": "SVK", "rome": "ITA", "valletta": "MLT", "tirana": "ALB",
    "belgrade": "SRB", "podgorica": "MNE", "skopje": "MKD", "zagreb": "HRV", "sarajevo": "BIH", "pristina": "XKX",
    "ljubljana": "SVN", "athens": "GRC", "nicosia": "CYP", "bucharest": "ROU", "chisinau": "MDA", "tallinn": "EST",
    "riga": "LVA", "vilnius": "LTU", "kiev": "UKR", "minsk": "BLR", "yerevan": "ARM", "tbilisi": "GEO",
    "baku": "AZE", "helsinki": "FIN", "stockholm": "SWE", "oslo": "NOR", "copenhagen": "DNK", "reykjavik": "ISL",
    "vaduz": "LIE", "praia": "CPV", "banjul": "GMB", "bamako": "MLI", "dakar": "SEN", "porto-novo": "BEN",
    "nouakchott": "MRT", "niamey": "NER", "yamoussoukro": "CIV", "abidjan": "CIV", "conakry": "GIN",
    "ouagadougou": "BFA", "monrovia": "LBR", "freetown": "SLE", "accra": "GHA", "lome": "TGO", "yaounde": "CMR",
    "abuja": "NGA", "libreville": "GAB", "bangui": "CAF", "n'djamena": "TCD", "ndjamena": "TCD",
    "brazzaville": "COG", "kinshasa": "COD", "kampala": "UGA", "nairobi": "KEN", "dodoma": "TZA", "gitega": "BDI",
    "kigali": "RWA", "mogadishu": "SOM", "addis ababa": "ETH", "asmara": "ERI", "luanda": "AGO", "maputo": "MOZ",
    "lusaka": "ZMB", "harare": "ZWE", "lilongwe": "MWI", "pretoria": "ZAF", "windhoek": "NAM", "maseru": "LSO",
    "gaborone": "BWA", "mbabane": "SWZ", "antananarivo": "MDG", "port louis": "MUS", "rabat": "MAR",
    "algiers": "DZA", "tunis": "TUN", "tripoli": "LBY", "khartoum": "SDN", "juba": "SSD", "cairo": "EGY",
    "ankara": "TUR", "baghdad": "IRQ", "damascus": "SYR", "beirut": "LBN", "amman": "JOR", "riyadh": "SAU",
    "sanaa": "YEM", "sana'a": "YEM", "doha": "QAT", "abu dhabi": "ARE", "muscat": "OMN", "manama": "BHR",
    "kabul": "AFG", "ashgabat": "TKM", "dushanbe": "TJK", "bishkek": "KGZ", "tashkent": "UZB", "astana": "KAZ",
    "ulaanbaatar": "MNG", "ulan bator": "MNG", "delhi": "IND", "thimphu": "BTN", "islamabad": "PAK",
    "dhaka": "BGD", "naypyidaw": "MMR", "colombo": "LKA", "kathmandu": "NPL", "bangkok": "THA",
    "phnom penh": "KHM", "vientiane": "LAO", "hanoi": "VNM", "kuala lumpur": "MYS", "manila": "PHL",
    "jakarta": "IDN", "dili": "TLS", "canberra": "AUS", "port moresby": "PNG", "wellington": "NZL", "suva": "FJI",
}
# "Paris Agreement", "Doha Round", "Minsk accords" name a treaty or a process, not the country.
_NOT_THE_COUNTRY = r"(?!\s+(?:agreements?|accords?|conventions?|protocols?|round|statute|treaty|club|process|format|declaration|consensus)\b)"

ENDONYMS = {
    "bharat": "IND", "hindustan": "IND", "deutschland": "DEU", "nippon": "JPN", "nihon": "JPN", "espana": "ESP",
    "italia": "ITA", "polska": "POL", "hellas": "GRC", "rossiya": "RUS", "misr": "EGY", "helvetia": "CHE",
    "schweiz": "CHE", "suisse": "CHE", "suomi": "FIN", "hrvatska": "HRV", "ceylon": "LKA", "siam": "THA",
    "kampuchea": "KHM", "zhongguo": "CHN", "eire": "IRL", "sverige": "SWE", "norge": "NOR", "danmark": "DNK",
    "osterreich": "AUT", "nederland": "NLD", "magyarorszag": "HUN",
}

# Lower-case "usa" is not in the gazetteer (only "USA" and "u.s.a."). "ROC" is
# left out: in a technical question it is more often the ROC curve.
ABBREVIATIONS = {"usa": "USA", "rok": "KOR", "ksa": "SAU", "rsa": "ZAF", "nz": "NZL"}

# "Sino-Indian" -> China-India. Only rewritten when the second half is itself a
# country, so "Indo-Pacific", "Sino-Tibetan" and "Anglo-Saxon" stay as they are.
COMBINING_FORMS = {"sino": "CHN", "russo": "RUS", "franco": "FRA", "anglo": "GBR", "indo": "IND", "turco": "TUR", "italo": "ITA", "greco": "GRC"}

# English words one edit away from a country name. Never "corrected".
FALSE_FRIENDS = {
    "child", "chili", "chin", "chia", "franc", "francs", "sedan", "tiger", "spin", "span", "stain", "sprain",
    "swain", "macro", "mail", "moan", "malt", "malts", "indie", "tongs", "pajama", "trance", "expert", "experts",
}

# Spelling targets beyond country names: words the parser keys on, long enough
# that a one-edit neighbour is very unlikely to be a different real word.
DOMAIN_WORDS = (
    "forecast", "happened", "happening", "relations", "relationship", "exposure", "dependence",
    "dependent", "embargo", "sanctions", "influence", "alliance", "alliances", "electronics", "semiconductors",
    "agriculture", "outlook", "headlines", "projection",
)

# Aliases common enough to be misspelt that are still safe fuzzy targets.
# Demonyms are not: "green" is one edit from "greek".
_FUZZY_ALIASES = {"britain": "GBR", "america": "USA", "holland": "NLD"}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# Verbs of reduction and the trade flows they apply to, for scenario framing.
_REDUCTION = re.compile(r"\b(reduc(?:e|es|ed|ing|tion)|cuts?|cutting|slash(?:es|ed)?|curbs?|curbed|drops?|dropped|lowers?|lowered|plunges?|chokes?|throttles?)\b", re.I)
_FLOW = re.compile(r"\b(exports?|imports?|supply|supplies|shipments?|production|output|sales)\b", re.I)
_SCENARIO_LEAD = re.compile(r"^\s*(what (?:happens|would happen|will happen) if|simulate|imagine|suppose|scenario:?|model)\s+(?:that\s+|an?\s+)?", re.I)
_HISTORICAL = re.compile(r"^\s*(why|when|how did|did|was|were)\b", re.I)

_LEXICON: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str], str], ...] = (
    (re.compile(r"(?<!building )\bblocks\b", re.I), lambda m: "blocs", "'blocks' meant as trading or UN blocs"),
    (re.compile(r"\blatest on\b", re.I), lambda m: "latest news on", "a request for the latest events"),
    (re.compile(r"\bupdates? (on|from|about)\b", re.I), lambda m: f"news {m.group(1)}", "a request for the latest events"),
    (re.compile(r"\bwhat'?s new (?:in|with)\b", re.I), lambda m: "news about", "a request for the latest events"),
    (re.compile(r"\bwhich side\b", re.I), lambda m: "which bloc", "a question about alignment"),
    (re.compile(r"\brelies\b", re.I), lambda m: "is dependent", "reliance is dependence"),
    (re.compile(r"\brelied\b", re.I), lambda m: "was dependent", "reliance is dependence"),
    (re.compile(r"\brelying\b", re.I), lambda m: "being dependent", "reliance is dependence"),
    (re.compile(r"\breliance\b", re.I), lambda m: "dependence", "reliance is dependence"),
    (re.compile(r"\breliant\b", re.I), lambda m: "dependent", "reliance is dependence"),
    (re.compile(r"\bdepends\b", re.I), lambda m: "is dependent", "the parser keys on 'dependent'"),
)


# ----------------------------------------------------------------- helpers
def _fold(text: str) -> str:
    return countries._fold(text)


def _osa(a: str, b: str) -> int:
    """Optimal string alignment distance: edits, counting a swap of neighbours as one."""
    if abs(len(a) - len(b)) > 2:
        return 3
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], previous2[j - 2] + 1)
        previous2, previous = previous, current
    return previous[-1]


def _is_swap(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def _known_to_parser(word: str) -> bool:
    from . import intent  # imported here: intent imports this module

    patterns = [intent._SHOCK, intent._FORECAST, intent._BLOCS, intent._EVENTS, intent._RANKING, intent._BILATERAL]
    patterns += list(intent._DOMAIN.values()) + [pattern for _, pattern in intent._SECTORS]
    return any(pattern.search(word) for pattern in patterns)


def _mention_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start, m.start + len(m.matched)) for m in countries.find_mentions(text)]


def _overlaps(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(start < s_end and s_start < end for s_start, s_end in spans)


def _replace_spans(text: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


@lru_cache(maxsize=1)
def _alias_pattern() -> tuple[re.Pattern[str], dict[str, tuple[str, str]]]:
    table: dict[str, tuple[str, str]] = {}
    for label, iso3 in CAPITALS.items():
        table[label] = (iso3, "capital")
    for label, iso3 in ENDONYMS.items():
        table[label] = (iso3, "endonym")
    for label, iso3 in ABBREVIATIONS.items():
        table[label] = (iso3, "abbreviation")
    labels = sorted(table, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w.-])(" + "|".join(re.escape(label) for label in labels) + r")(?![\w-])" + _NOT_THE_COUNTRY, re.I)
    return pattern, table


@lru_cache(maxsize=1)
def _country_targets() -> tuple[dict[str, str], dict[str, str]]:
    """Fuzzy-match targets: single-word and multi-word country names (folded) -> ISO3."""
    single: dict[str, str] = {}
    multi: dict[str, str] = {}
    labels = [(c.name, c.iso3) for c in countries.COUNTRIES.values()] + list(_FUZZY_ALIASES.items())
    for label, iso3 in labels:
        folded = _fold(label)
        if not re.fullmatch(r"[a-z]+(?: [a-z]+)*", folded):
            continue
        (multi if " " in folded else single)[folded] = iso3
    return single, multi


_TOKEN = re.compile(r"[A-Za-zÀ-ɏ]+")


# ------------------------------------------------------------------- steps
def _step_aliases(text: str) -> tuple[str, list[Rewrite]]:
    rewrites: list[Rewrite] = []
    edits: list[tuple[int, int, str]] = []

    for match in re.finditer(r"\b(" + "|".join(COMBINING_FORMS) + r")-([A-Za-z]+)\b", text, re.I):
        second = countries.find_mentions(match.group(2))
        if len(second) != 1:
            continue
        first_name = countries.name_of(COMBINING_FORMS[match.group(1).lower()])
        replacement = f"{first_name}-{second[0].name}"
        edits.append((match.start(), match.end(), replacement))
        rewrites.append(Rewrite("aliases", "combining_form", match.group(0), replacement, "a combining form names two countries", CONFIDENCE["combining_form"]))
    text = _replace_spans(text, edits)

    folded = _fold(text)
    if len(folded) != len(text):  # spans would not line up; match on the text as typed
        folded = text.lower()
    taken = _mention_spans(text)
    pattern, table = _alias_pattern()
    edits = []
    for match in pattern.finditer(folded):
        start, end = match.span(1)
        if _overlaps(start, end, taken):  # already part of a name, e.g. "Delhi" in "New Delhi"
            continue
        iso3, kind = table[match.group(1)]
        name = countries.name_of(iso3)
        edits.append((start, end, name))
        rewrites.append(Rewrite("aliases", kind, text[start:end], name, f"{kind} of {name}", CONFIDENCE[kind]))
    return _replace_spans(text, edits), rewrites


def _step_spelling(text: str) -> tuple[str, list[Rewrite]]:
    from . import intent

    rewrites: list[Rewrite] = []
    edits: list[tuple[int, int, str]] = []
    taken = _mention_spans(text)
    tokens = [m for m in _TOKEN.finditer(text)]

    # Country names are corrected only where a country seems to be missing: none
    # found, or one found in a question about a relationship. A question that
    # already names its countries is left alone, which keeps "iron exports from
    # Australia" from becoming Iran.
    missing = not taken or (len(taken) == 1 and intent._BILATERAL.search(text))
    if missing:
        single, multi = _country_targets()
        used: set[int] = set()
        for size in (3, 2):  # "untied kingdom" -> United Kingdom
            for i in range(len(tokens) - size + 1):
                window = tokens[i:i + size]
                if any(t.start() in used for t in window):
                    continue
                start, end = window[0].start(), window[-1].end()
                if _overlaps(start, end, taken):
                    continue
                phrase = _fold(" ".join(t.group(0) for t in window))
                if len(phrase) < 8 or phrase in multi:
                    continue
                hits = {iso3 for label, iso3 in multi.items() if _osa(phrase, label) == 1}
                if len(hits) == 1:
                    iso3 = hits.pop()
                    name = countries.name_of(iso3)
                    edits.append((start, end, name))
                    used.update(t.start() for t in window)
                    rewrites.append(Rewrite("spelling", "country_spelling", text[start:end], name, "likely a misspelt country name", CONFIDENCE["country_spelling"]))
        for token in tokens:
            word = _fold(token.group(0))
            if token.start() in used or len(word) < 4 or word in FALSE_FRIENDS or word in single or countries.resolve(word):
                continue
            if _overlaps(token.start(), token.end(), taken) or _known_to_parser(word):
                continue
            # Four-letter names (Iran, Iraq, Oman, Mali, Chad, ...) sit one edit
            # from too many words; accept only a swapped pair ("iarn").
            hits = {iso3 for label, iso3 in single.items() if _osa(word, label) == 1 and (len(label) > 4 or _is_swap(word, label))}
            if len(hits) == 1:
                iso3 = hits.pop()
                name = countries.name_of(iso3)
                edits.append((token.start(), token.end(), name))
                used.add(token.start())
                rewrites.append(Rewrite("spelling", "country_spelling", token.group(0), name, "likely a misspelt country name", CONFIDENCE["country_spelling"]))

    for token in tokens:
        word = _fold(token.group(0))
        if token.start() in {e[0] for e in edits} or len(word) < 6 or word in FALSE_FRIENDS or word in DOMAIN_WORDS:
            continue
        if countries.resolve(word) or _known_to_parser(word):
            continue
        hits = [target for target in DOMAIN_WORDS if _osa(word, target) == 1]
        if len(hits) == 1:
            target = hits[0]
            # "forecasts" is the same word as "forecast", not a misspelling of it.
            kind, reason = ("word_form", "another form of the word the parser keys on") if word.startswith(target) or target.startswith(word) else ("word_spelling", "likely a misspelling")
            edits.append((token.start(), token.end(), target))
            rewrites.append(Rewrite("spelling", kind, token.group(0), target, reason, CONFIDENCE[kind]))
    return _replace_spans(text, edits), rewrites


def _step_numbers(text: str) -> tuple[str, list[Rewrite]]:
    from . import intent

    rewrites: list[Rewrite] = []

    def number_word(match: re.Match[str]) -> str:
        value = str(_NUMBER_WORDS[match.group(1).lower()])
        rewrites.append(Rewrite("numbers", "number_word", match.group(1), value, "number in words", CONFIDENCE["number_word"]))
        return value + match.group(2)

    text = re.sub(r"\byrs?\b", lambda m: "years" if m.group(0).lower() == "yrs" else "year", text, flags=re.I)
    text = re.sub(r"\ba decade\b", "10 years", text, flags=re.I)
    words = "|".join(_NUMBER_WORDS)
    text = re.sub(rf"\b({words})(\s*(?:years?|percent|per cent|%))", number_word, text, flags=re.I)

    year_now = intent._today().year

    def horizon(match: re.Match[str]) -> str:
        years = int(match.group("n"))
        if not 1 <= years <= 20:
            return match.group(0)
        replacement = f"by {year_now + years}"
        rewrites.append(Rewrite("numbers", "relative_year", match.group(0).strip(), replacement, f"{years} years from {year_now}", CONFIDENCE["relative_year"]))
        return replacement

    for pattern in (
        r"\b(?:(?:over|in|within|for|during)\s+)?(?:the\s+)?next\s+(?P<n>\d{1,2})\s+years?\b",
        r"\bin\s+(?P<n>\d{1,2})\s+years?(?:'?\s*time)?\b",
        r"\b(?P<n>\d{1,2})\s+years?\s+(?:from now|out|ahead|hence)\b",
    ):
        text = re.sub(pattern, horizon, text, flags=re.I)
    return text, rewrites


def _step_phrasing(text: str) -> tuple[str, list[Rewrite]]:
    from . import intent

    rewrites: list[Rewrite] = []
    for pattern, replace, reason in _LEXICON:
        def lexicon(match: re.Match[str], replace=replace, reason=reason) -> str:
            replacement = replace(match)
            rewrites.append(Rewrite("phrasing", "lexicon", match.group(0), replacement, reason, CONFIDENCE["lexicon"]))
            return replacement

        text = pattern.sub(lexicon, text)

    year_now = intent._today().year
    has_country = bool(countries.find_mentions(text))

    # A future year with no forecast cue: "What will Brazil's exports look like in 2030?"
    if not intent._FORECAST.search(text) and not intent._SHOCK.search(text):
        def future(match: re.Match[str]) -> str:
            if int(match.group(2)) <= year_now:
                return match.group(0)
            replacement = f"by {match.group(2)}"
            rewrites.append(Rewrite("phrasing", "future_year", match.group(0), replacement, "a future year asks for a forecast", CONFIDENCE["future_year"]))
            return replacement

        text = re.sub(r"\b(in|through|until|till|to)\s+(20[2-4]\d)\b", future, text, flags=re.I)

    # A reduction of a trade flow, framed as a statement: "Moscow reduces fuel
    # exports by half". The parser reads a scenario from "What if".
    past_year = any(int(y) <= year_now for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", text))
    if (has_country and not intent._SHOCK.search(text) and _REDUCTION.search(text) and _FLOW.search(text)
            and not past_year and not _HISTORICAL.search(text)):
        lead = _SCENARIO_LEAD.match(text)
        framed = "What if " + (text[lead.end():] if lead else text)
        rewrites.append(Rewrite("phrasing", "scenario", text, framed, "a cut to a trade flow is a disruption scenario", CONFIDENCE["scenario"]))
        text = framed
    return text, rewrites


_STEP_FUNCTIONS = {"aliases": _step_aliases, "spelling": _step_spelling, "numbers": _step_numbers, "phrasing": _step_phrasing}


def resolve_steps(steps: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Normalise a step selection: None or "all" -> every step, "none" -> no steps."""
    if steps is None:
        return STEPS
    if isinstance(steps, str):
        steps = [] if steps.strip().lower() == "none" else (STEPS if steps.strip().lower() == "all" else [s.strip() for s in steps.split(",") if s.strip()])
    chosen = set(steps)
    unknown = chosen - set(STEPS)
    if unknown:
        raise ValueError(f"unknown reformulation step(s): {', '.join(sorted(unknown))}")
    return tuple(step for step in STEPS if step in chosen)


def reformulate(question: str, steps: Optional[Iterable[str]] = None) -> Reformulation:
    """Rewrite a question, step by step, into words the parser recognises."""
    original = " ".join(str(question or "").split())
    text = original
    rewrites: list[Rewrite] = []
    for step in resolve_steps(steps):
        text, made = _STEP_FUNCTIONS[step](text)
        rewrites += made
    return Reformulation(original=original, text=" ".join(text.split()), rewrites=rewrites)
