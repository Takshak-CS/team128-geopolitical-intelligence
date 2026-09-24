"""
preprocess.py — GDELT Video Intelligence Pipeline
==================================================
ML layers:
  1. spaCy NER       — extracts real PERSON/ORG names from actor strings
  2. DistilBERT      — cross-validates Goldstein score with transformer sentiment
  3. KMeans          — clusters events into thematic groups

Patched (backend hardening pass):
  - KMeans now runs on StandardScaler-scaled features instead of raw,
    differently-scaled columns (EventRootCode vs GoldsteinScale).
  - Sentiment text-building no longer uses iterrows() — vectorized via zip().
  - NER enrichment is now deduped + batched through nlp.pipe() instead of
    one nlp() call per cell.
  - Added warmup_models() so a server (e.g. FastAPI) can eagerly load
    spaCy/DistilBERT on startup instead of on the first real request.
  Public function names, signatures, and DataFrame column names are
  unchanged — this is a drop-in replacement for the existing app.py.
"""

import os
import json
import zipfile
import warnings
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from importlib.util import find_spec

warnings.filterwarnings("ignore")

# ── Optional ML imports ────────────────────────────────────────────────────
_NLP = None
_NLP_LOAD_ATTEMPTED = False
NER_AVAILABLE = find_spec("spacy") is not None

_SENTIMENT = None
_SENTIMENT_LOAD_ATTEMPTED = False
SENTIMENT_AVAILABLE = find_spec("transformers") is not None and find_spec("torch") is not None

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    CLUSTER_AVAILABLE = True
except Exception:
    CLUSTER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GDELT_COLS = [1, 6, 7, 12, 16, 17, 22, 26, 30, 33, 57]
COL_NAMES  = [
    "SQLDATE",
    "Actor1Name", "Actor1CountryCode", "Actor1Type1Code",
    "Actor2Name", "Actor2CountryCode", "Actor2Type1Code",
    "EventCode", "GoldsteinScale", "NumArticles", "SOURCEURL",
]

# CAMEO actor-type codes, used as a fallback description when GDELT didn't
# record an actor's name but did record what kind of actor it was.
ACTOR_TYPE_MAP = {
    "GOV": "government", "MIL": "military", "REB": "rebel",
    "OPP": "opposition", "INS": "insurgent", "COP": "police",
    "JUD": "judicial", "BUS": "business", "CRM": "criminal",
    "MED": "media", "NGO": "non-government", "IGO": "intergovernmental",
    "CVL": "civilian", "EDU": "education", "SEP": "separatist",
    "SPY": "intelligence", "UAF": "militant", "MNC": "corporate",
    "LEG": "legislative", "ELI": "elite", "REF": "refugee",
    "HRI": "human rights",
}

GDELT_BASE_URL = "http://data.gdeltproject.org/events"
DATA_DIR       = Path("data")
CACHE_INDEX    = DATA_DIR / ".cache_index.json"
MAX_CACHE      = 5          # keep last 5 downloaded dates

EVENT_MAP = {
    "01": "Verbal Cooperation",    "02": "Material Cooperation",
    "03": "Diplomatic Cooperation","04": "Consultation",
    "05": "Mediation",             "06": "Engagement",
    "07": "Provision of Aid",      "08": "Yield / Concession",
    "09": "Investigation",         "10": "Demand",
    "11": "Disapprove",            "12": "Reject",
    "13": "Threaten",              "14": "Protest",
    "15": "Exhibit Force",         "16": "Reduce Relations",
    "17": "Coerce",                "18": "Assault",
    "19": "Fight",                 "20": "Mass Violence",
}

VERB_MAP = {
    "Verbal Cooperation":     "engaged in verbal cooperation with",
    "Material Cooperation":   "provided material cooperation to",
    "Diplomatic Cooperation": "entered into diplomatic cooperation with",
    "Consultation":           "held consultations with",
    "Mediation":              "attempted to mediate in a dispute involving",
    "Engagement":             "was involved in diplomatic engagement with",
    "Provision of Aid":       "extended aid to",
    "Yield / Concession":     "made a notable concession toward",
    "Investigation":          "launched an investigation involving",
    "Demand":                 "issued a formal demand toward",
    "Disapprove":             "publicly disapproved of actions by",
    "Reject":                 "rejected a proposal or action from",
    "Threaten":               "issued a threat directed at",
    "Protest":                "staged a protest against",
    "Exhibit Force":          "exhibited a show of force against",
    "Reduce Relations":       "moved to reduce diplomatic relations with",
    "Coerce":                 "applied coercive pressure on",
    "Assault":                "was involved in an assault incident with",
    "Fight":                  "engaged in active fighting with",
    "Mass Violence":          "was implicated in mass violence involving",
    "Other":                  "was involved in an undetermined event with",
}

# Specific 3-digit CAMEO codes, for the dramatic root categories where the
# difference between "engaged in active fighting" and "shelled positions
# held by" actually matters. Falls back to VERB_MAP's root-level phrase
# for any code not listed here — this only ever adds specificity, never
# removes the existing fallback.
CAMEO_DETAIL_MAP = {
    # Threaten (13)
    "130": "issued a general threat toward",
    "131": "threatened non-military action against",
    "132": "threatened to cut off aid or support to",
    "133": "threatened with sanctions or a boycott against",
    "134": "threatened to halt negotiations with",
    "135": "threatened to use military force against",
    "136": "threatened to use weapons of mass destruction against",
    "137": "issued an ultimatum to",
    # Protest (14)
    "140": "saw demonstrators rally against",
    "141": "saw demonstrators demand a leadership change from",
    "142": "saw demonstrators rally over policy involving",
    "143": "saw demonstrators rally for the rights of",
    "144": "saw demonstrators demand institutional change involving",
    "145": "saw a hunger strike staged against",
    # Coerce (17)
    "170": "applied coercive measures against",
    "171": "seized or destroyed property belonging to",
    "172": "imposed administrative sanctions on",
    "173": "arrested or detained individuals linked to",
    "174": "expelled or deported individuals linked to",
    "175": "carried out violent repression against",
    "176": "launched a cyberattack against",
    # Assault (18)
    "180": "carried out an unconventional attack on",
    "181": "abducted or took hostages from",
    "182": "physically assaulted",
    "183": "carried out a bombing targeting",
    "185": "attempted to assassinate a figure linked to",
    "186": "assassinated a figure linked to",
    # Fight (19)
    "190": "carried out a direct military confrontation with",
    "191": "imposed a blockade on",
    "192": "moved to occupy territory belonging to",
    "193": "exchanged small-arms fire with",
    "194": "shelled positions held by",
    "195": "carried out airstrikes against",
    "196": "violated a ceasefire with",
    # Mass violence (20)
    "200": "was implicated in mass violence against",
    "201": "carried out a mass expulsion targeting",
    "202": "was implicated in mass killings affecting",
    "203": "was implicated in ethnic-cleansing actions against",
    "204": "was accused of using weapons of mass destruction against",
}

# GDELT often resolves an actor to a generic role rather than a proper
# name. When we know which country that role belongs to, "Armed Forces"
# becomes "Bahrain's armed forces" instead of staying a bare label.
GENERIC_ROLE_TERMS = {
    # Political / role labels
    "Politician", "Leader", "Minister", "President", "Prime Minister",
    "Governor", "Mayor", "Senator", "Ambassador", "Diplomat",
    "Judge", "Justice", "Court", "Judiciary", "Official", "Officer",
    "Executive", "Director", "Chairman", "Commissioner", "Secretary",
    # Military / security
    "Police", "Military", "Armed Forces", "Forces", "Security Forces",
    "Insurgents", "Militants", "Rebel", "Rebels",
    # Government / institutions
    "Government", "Parliament", "Court", "Judiciary", "Legislature",
    "Administration", "Authorities", "Officials", "Ministry",
    # Civil society / public
    "Opposition", "Protesters", "Demonstrators", "Activists",
    "Students", "Workers", "Citizens", "Civilians", "Public",
    # Sector labels
    "Business", "Corporate", "Media", "Education", "School", "University",
    "Church", "Religious", "Clergy",
    # Conflict actors
    "Uprising", "Insurgent", "Insurgents", "Rebel", "Rebels",
    "Extremist", "Extremists", "Jihadist", "Jihadists",
    "Gunman", "Gunmen", "Attacker", "Attackers",
    # Criminal / legal
    "Criminal", "Crime", "Suspect", "Accused", "Defendant",
    # Ethnic / community
    "Tribe", "Ethnic", "Minority", "Community",
    # Religious-community labels — GDELT sometimes resolves an actor to an
    # entire faith community rather than any specific person, group, or
    # organization. Treating "Muslim" or "Christian" as a single political
    # actor the way "Muslim condemned Bangladesh" implies is both
    # inaccurate and in poor taste — this gives it a properly qualified,
    # non-monolithic label instead.
    "Muslim", "Christian", "Hindu", "Jewish", "Sikh", "Buddhist",
    "Catholic", "Protestant", "Shia", "Sunni", "Orthodox",
    # Royalty / monarchy — GDELT frequently resolves a head-of-state actor
    # to a bare title like "King" or "Crown Prince" with no name attached.
    "King", "Queen", "Prince", "Princess", "Crown Prince", "Crown Princess",
    "Monarch", "Monarchy", "Royal Family", "Royals", "Royalty",
    "Sultan", "Emir", "Emirs", "Duke", "Duchess",
    # Regional / bloc labels — GDELT codes some events to a continent or
    # political bloc rather than a specific country or organization. These
    # are just as unattributable as a bare role label, and are a common
    # source of keyword-matching noise (an unrelated article mentioning
    # "European" style/culture gets coded as a "European" diplomatic actor).
    "European", "Western", "Eastern", "Arab", "Asian", "African",
    "Latin American", "Middle Eastern", "Scandinavian", "Balkan",
    "Caribbean", "Pacific", "Nordic", "Slavic",
}

# Demonym / adjective forms GDELT sometimes uses in place of a country name
# ("Finn" for Finland, "Kingdom" for Saudi Arabia). Applied BEFORE NER so
# a demonym is never mistaken for a person's name (spaCy will happily tag
# "Finn" as PERSON since it's also a common first name).
ACTOR_NORMALIZE = {
    "U. S.": "United States", "U.S.": "United States",
    "Us": "United States", "U S": "United States", "American": "United States",
    "Uk": "United Kingdom", "U. K.": "United Kingdom", "British": "United Kingdom",
    "Kingdom": "Saudi Arabia",  # GDELT shorthand for Kingdom of Saudi Arabia
    "Bahraini": "Bahrain", "Iraqi": "Iraq", "Iranian": "Iran",
    "Yemeni": "Yemen", "Qatari": "Qatar", "Kuwaiti": "Kuwait",
    "Emirati": "UAE", "Omani": "Oman", "Jordanian": "Jordan",
    "Lebanese": "Lebanon", "Syrian": "Syria", "Egyptian": "Egypt",
    "Israeli": "Israel", "Turkish": "Turkey", "Afghan": "Afghanistan",
    "Pakistani": "Pakistan", "Indian": "India", "Nigerian": "Nigeria",
    "Kenyan": "Kenya", "Ghanaian": "Ghana", "Ugandan": "Uganda",
    "French": "France", "German": "Germany", "Spanish": "Spain",
    "Australian": "Australia", "Canadian": "Canada", "Brazilian": "Brazil",
    "Mexican": "Mexico", "Russian": "Russia", "Chinese": "China",
    "Japanese": "Japan", "Italian": "Italy", "Greek": "Greece",
    "Portuguese": "Portugal", "Swiss": "Switzerland", "Austrian": "Austria",
    "Hungarian": "Hungary", "Czech": "Czech Republic", "Romanian": "Romania",
    "Bulgarian": "Bulgaria", "Croatian": "Croatia", "Serbian": "Serbia",
    "Dutch": "Netherlands", "Swedish": "Sweden", "Norwegian": "Norway",
    "Danish": "Denmark", "Finnish": "Finland", "Finn": "Finland", "Finns": "Finland",
    "Belgian": "Belgium", "Polish": "Poland",
    "Ukrainian": "Ukraine", "Belarusian": "Belarus", "Moldovan": "Moldova",
    "Georgian": "Georgia", "Armenian": "Armenia", "Azerbaijani": "Azerbaijan",
    "Lithuanian": "Lithuania", "Latvian": "Latvia", "Estonian": "Estonia",
    "Slovak": "Slovakia", "Slovenian": "Slovenia", "Macedonian": "North Macedonia",
    "Albanian": "Albania", "Bosnian": "Bosnia and Herzegovina",
    "Montenegrin": "Montenegro", "Maltese": "Malta", "Icelandic": "Iceland",
    "Mongolian": "Mongolia", "Kyrgyz": "Kyrgyzstan", "Tajik": "Tajikistan",
    "Turkmen": "Turkmenistan", "Uzbek": "Uzbekistan", "Kazakh": "Kazakhstan",
    "Korean": "South Korea", "Vietnamese": "Vietnam", "Thai": "Thailand",
    "Filipino": "Philippines", "Indonesian": "Indonesia", "Malaysian": "Malaysia",
    "Singaporean": "Singapore", "Taiwanese": "Taiwan", "Nepali": "Nepal",
    "Bangladeshi": "Bangladesh", "Sri Lankan": "Sri Lanka",
    "Burmese": "Myanmar", "Zimbabwean": "Zimbabwe", "Zambian": "Zambia",
    "Ivorian": "Ivory Coast", "Senegalese": "Senegal", "Malian": "Mali",
    "Moroccan": "Morocco", "Tunisian": "Tunisia", "Algerian": "Algeria",
    "Libyan": "Libya", "Sudanese": "Sudan", "Somali": "Somalia",
    "Ethiopian": "Ethiopia",
    "Venezuelan": "Venezuela", "Colombian": "Colombia", "Peruvian": "Peru",
    "Ecuadorian": "Ecuador", "Bolivian": "Bolivia", "Paraguayan": "Paraguay",
    "Uruguayan": "Uruguay", "Chilean": "Chile", "Argentine": "Argentina",
    "Argentinian": "Argentina", "Guatemalan": "Guatemala", "Honduran": "Honduras",
    "Salvadoran": "El Salvador", "Costa Rican": "Costa Rica",
    "Panamanian": "Panama", "Nicaraguan": "Nicaragua",
    "Cuban": "Cuba", "Haitian": "Haiti", "Dominican": "Dominican Republic",
    "Jamaican": "Jamaica", "Trinidadian": "Trinidad and Tobago",
    # Country nicknames / capitals GDELT sometimes uses AS the actor name
    # instead of the country ("Britain", "London") — without this, the
    # same country shows up as 3-4 different, unlinked graph nodes.
    "Britain": "United Kingdom", "England": "United Kingdom",
    "London": "United Kingdom", "Uk.": "United Kingdom",
    "America": "United States", "Washington": "United States",
    "Beijing": "China", "Moscow": "Russia", "Paris": "France",
    "Berlin": "Germany", "Tokyo": "Japan", "Delhi": "India",
    "New Delhi": "India", "Canberra": "Australia", "Ottawa": "Canada",
    "Islamabad": "Pakistan", "Tehran": "Iran", "Riyadh": "Saudi Arabia",
    "Cairo": "Egypt", "Ankara": "Turkey", "Kyiv": "Ukraine",
    "Kiev": "Ukraine", "Brussels": "Belgium", "Jerusalem": "Israel",
    "Damascus": "Syria", "Baghdad": "Iraq", "Kabul": "Afghanistan",
    "Seoul": "South Korea", "Pyongyang": "North Korea",
    "Bangkok": "Thailand", "Hanoi": "Vietnam", "Manila": "Philippines",
    "Jakarta": "Indonesia", "Kuala Lumpur": "Malaysia",
}

CLUSTER_THEME_MAP = {
    frozenset(["01","02","03","04","05","06","07","08"]): "Diplomatic Cooperation",
    frozenset(["09","10","11","12"]):                     "Diplomatic Pressure",
    frozenset(["13","14","15","16"]):                     "Escalation & Protest",
    frozenset(["17","18","19","20"]):                     "Conflict & Violence",
}

# ---------------------------------------------------------------------------
# Cache management (last 5 dates)
# ---------------------------------------------------------------------------

def _load_cache_index() -> list:
    """Returns ordered list of cached dates (oldest first)."""
    if CACHE_INDEX.exists():
        try:
            return json.loads(CACHE_INDEX.read_text())
        except Exception:
            return []
    return []


def _save_cache_index(dates: list):
    CACHE_INDEX.write_text(json.dumps(dates))


def _evict_oldest(dates: list) -> list:
    """Remove oldest cached CSV files until we're under MAX_CACHE."""
    while len(dates) >= MAX_CACHE:
        oldest = dates.pop(0)
        old_path = DATA_DIR / f"{oldest}.export.CSV"
        if old_path.exists():
            old_path.unlink()
    return dates


def _register_date(date: str):
    """Add date to cache index, evicting oldest if needed."""
    DATA_DIR.mkdir(exist_ok=True)
    dates = _load_cache_index()
    if date in dates:
        # Move to end (most recent)
        dates.remove(date)
        dates.append(date)
    else:
        dates = _evict_oldest(dates)
        dates.append(date)
    _save_cache_index(dates)


# ---------------------------------------------------------------------------
# GDELT auto-downloader
# ---------------------------------------------------------------------------

def fetch_gdelt_file(date: str) -> Path:
    """
    Ensures the GDELT V1 export CSV for `date` (YYYYMMDD) is present locally.
    Downloads and unzips from data.gdeltproject.org when not cached.
    Maintains a cache of the last 5 dates.
    """
    DATA_DIR.mkdir(exist_ok=True)
    csv_path = DATA_DIR / f"{date}.export.CSV"

    if csv_path.exists():
        _register_date(date)   # refresh its position in cache
        return csv_path

    zip_url  = f"{GDELT_BASE_URL}/{date}.export.CSV.zip"
    zip_path = DATA_DIR / f"{date}.export.CSV.zip"

    try:
        r = requests.get(zip_url, stream=True, timeout=120)
        r.raise_for_status()
    except requests.HTTPError as e:
        status = getattr(r, "status_code", None)
        if status == 404:
            raise FileNotFoundError(
                f"No GDELT data found for {date}. "
                "GDELT V1 coverage starts from ~2013. "
                "Check the date is valid and not in the future."
            ) from e
        raise

    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(DATA_DIR)

    zip_path.unlink(missing_ok=True)

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Zip extracted but {csv_path.name} not found inside archive."
        )

    _register_date(date)
    return csv_path


def get_cached_dates() -> list:
    """Returns list of currently cached dates for display."""
    return _load_cache_index()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_tone(score):
    if pd.isna(score):  return "neutral"
    if score >= 5:      return "strongly cooperative"
    elif score >= 1:    return "cooperative"
    elif score > -1:    return "neutral"
    elif score >= -5:   return "tense"
    else:               return "highly conflictual"


def _clean_actor(name):
    s = str(name).strip()
    return None if s.lower() in ("nan", "none", "") else s.title()


def _clean_code(value):
    """Normalizes a raw GDELT code cell — handles real NaN *and* the string
    'nan' that str(float('nan')) produces, which the original fallback
    logic didn't account for (that was the 'A nan-linked actor' bug)."""
    s = str(value).strip().upper()
    return None if s in ("", "NAN", "NONE") else s


def _describe_unknown_actor(country_label, type_code) -> str:
    """Builds a readable stand-in for an actor GDELT didn't name, using
    whatever it *did* record — actor type (government, military, ...)
    and/or country — instead of a bare 'Unidentified'."""
    if country_label is not None and str(country_label).strip().lower() in ("nan", "none", ""):
        country_label = None
    type_label = ACTOR_TYPE_MAP.get(_clean_code(type_code))
    if country_label and type_label:
        return f"a {type_label} source in {country_label}"
    if country_label:
        return f"an unnamed party from {country_label}"
    if type_label:
        return f"a {type_label} source"
    return "an unidentified party"


# These get a direct label instead of the possessive form,
# because "Afghanistan's uprising" or "Pakistan's gunmen" reads oddly.
_EXPLICIT_ROLE_LABEL = {
    "Uprising":   "insurgent forces",
    "Insurgent":  "insurgent forces",
    "Insurgents": "insurgent forces",
    "Rebel":      "rebel forces",
    "Rebels":     "rebel forces",
    "Extremist":  "extremist actors",
    "Extremists": "extremist actors",
    "Jihadist":   "jihadist forces",
    "Jihadists":  "jihadist forces",
    "Gunman":     "an armed gunman",
    "Gunmen":     "armed gunmen",
    "Attacker":   "an unidentified attacker",
    "Attackers":  "unidentified attackers",
    "Criminal":   "a criminal actor",
    "Crime":      "a criminal actor",
    "Suspect":    "a suspect",
    "Accused":    "the accused",
    "Defendant":  "the defendant",
    # Royalty / monarchy — GDELT resolves these to a bare title with no
    # name, so "Finland -> King" (no monarchy in Finland) is really GDELT
    # miscoding an unspecified royal figure, not a real diplomatic contact.
    "King":           "an unnamed monarch",
    "Queen":          "an unnamed monarch",
    "Prince":         "an unnamed royal figure",
    "Princess":       "an unnamed royal figure",
    "Crown Prince":   "the crown prince",
    "Crown Princess": "the crown princess",
    "Monarch":        "an unnamed monarch",
    "Monarchy":       "the monarchy",
    "Royal Family":   "the royal family",
    "Royals":         "royal family members",
    "Royalty":        "royal family members",
    "Sultan":         "an unnamed monarch",
    "Emir":           "an unnamed monarch",
    "Emirs":          "royal rulers",
    "Duke":           "a noble figure",
    "Duchess":        "a noble figure",
    # Regional/bloc labels — named explicitly so it's clear this is a
    # continent-or-bloc-level GDELT code, not a specific country or
    # organization actually confirmed to be involved.
    "European":       "an unspecified European bloc actor",
    "Western":        "an unspecified Western bloc actor",
    "Eastern":        "an unspecified Eastern bloc actor",
    "Arab":           "an unspecified Arab bloc actor",
    "Asian":          "an unspecified Asian bloc actor",
    "African":        "an unspecified African bloc actor",
    "Latin American": "an unspecified Latin American bloc actor",
    "Middle Eastern": "an unspecified Middle Eastern bloc actor",
    "Scandinavian":   "an unspecified Scandinavian bloc actor",
    "Balkan":         "an unspecified Balkan bloc actor",
    "Caribbean":      "an unspecified Caribbean bloc actor",
    "Pacific":        "an unspecified Pacific bloc actor",
    "Nordic":         "an unspecified Nordic bloc actor",
    "Slavic":         "an unspecified Slavic bloc actor",
    # Religious communities — plural/collective phrasing, never treated
    # as a single actor.
    "Muslim":         "members of the Muslim community",
    "Christian":      "members of the Christian community",
    "Hindu":          "members of the Hindu community",
    "Jewish":         "members of the Jewish community",
    "Sikh":           "members of the Sikh community",
    "Buddhist":       "members of the Buddhist community",
    "Catholic":       "members of the Catholic community",
    "Protestant":     "members of the Protestant community",
    "Shia":           "members of the Shia community",
    "Sunni":          "members of the Sunni community",
    "Orthodox":       "members of the Orthodox Christian community",
}


def _enrich_generic_role(name: str, country_label) -> str:
    """Turns a bare role label GDELT resolved — 'Armed Forces', 'Police',
    'Uprising' — into something readable. Uses explicit labels for conflict
    actors (so we get 'insurgent forces' not 'Afghanistan's uprising') and
    the possessive form for institutional roles."""
    if name not in GENERIC_ROLE_TERMS:
        return name
    # Defensive: never let a stray "nan"/"none"/"" string become a
    # possessive prefix ("nan's police"). _clean_code() should already
    # catch this upstream, but a bad label here is worse than none.
    if country_label is not None and str(country_label).strip().lower() in ("nan", "none", ""):
        country_label = None
    # Explicit mapping takes priority
    if name in _EXPLICIT_ROLE_LABEL:
        label = _EXPLICIT_ROLE_LABEL[name]
        # Add country context where it makes sense
        if country_label and not label.startswith("the ") and not label.startswith("an ") and not label.startswith("a "):
            return f"{label} in {country_label}"
        return label
    # Possessive for institutional roles — "Bahrain's police", "Iran's government"
    if not country_label:
        return name.lower()
    return f"{country_label}'s {name.lower()}"


# ---------------------------------------------------------------------------
# ML Layer 1 — spaCy NER
# ---------------------------------------------------------------------------

def _ner_enrich(name):
    nlp = _get_nlp()
    if not nlp or not name:
        return name
    doc = nlp(str(name))
    for ent in doc.ents:
        if ent.label_ in ("PERSON", "ORG"):
            return ent.text.strip().title()
    return name


def _ner_enrich_series(s: pd.Series) -> pd.Series:
    """
    Batched, de-duplicated NER enrichment.

    The original per-cell version calls nlp(name) once per row, re-running
    the full spaCy pipeline for every event even though actor names repeat
    constantly within a single day. This dedupes to the unique names, runs
    them once through nlp.pipe() (spaCy's batched mode), then maps results
    back onto the full column — identical output, far fewer pipeline runs.
    """
    nlp = _get_nlp()
    if not nlp:
        return s

    uniques = s.dropna().unique().tolist()
    if not uniques:
        return s

    mapping = {}
    for name, doc in zip(uniques, nlp.pipe(uniques, batch_size=64)):
        enriched = name
        for ent in doc.ents:
            if ent.label_ in ("PERSON", "ORG"):
                enriched = ent.text.strip().title()
                break
        mapping[name] = enriched

    return s.map(mapping)


def _get_nlp():
    global _NLP, _NLP_LOAD_ATTEMPTED, NER_AVAILABLE
    if _NLP or _NLP_LOAD_ATTEMPTED:
        return _NLP
    _NLP_LOAD_ATTEMPTED = True
    try:
        import spacy
        _NLP = spacy.load("en_core_web_sm")
    except Exception:
        _NLP = None
        NER_AVAILABLE = False
    return _NLP


# ---------------------------------------------------------------------------
# ML Layer 2 — DistilBERT Sentiment
# ---------------------------------------------------------------------------

def _build_event_text(a1, a2, event_type) -> str:
    a1   = str(a1 or "Unknown")
    a2   = str(a2 or "Unknown")
    verb = VERB_MAP.get(str(event_type or "Other"), "was involved in an event with")
    return f"{a1} {verb} {a2}"


def _run_sentiment_batch(texts: list) -> list:
    sentiment = _get_sentiment_pipeline()
    if not sentiment or not texts:
        return [{"label": "UNKNOWN", "score": 0.0}] * len(texts)
    results = []
    for i in range(0, len(texts), 32):
        batch = texts[i:i + 32]
        try:
            results.extend(sentiment(batch))
        except Exception:
            results.extend([{"label": "UNKNOWN", "score": 0.0}] * len(batch))
    return results


def _get_sentiment_pipeline():
    global _SENTIMENT, _SENTIMENT_LOAD_ATTEMPTED, SENTIMENT_AVAILABLE
    if _SENTIMENT or _SENTIMENT_LOAD_ATTEMPTED:
        return _SENTIMENT
    _SENTIMENT_LOAD_ATTEMPTED = True
    try:
        from transformers import pipeline as hf_pipeline
        _SENTIMENT = hf_pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            truncation=True,
            max_length=128,
        )
    except Exception:
        _SENTIMENT = None
        SENTIMENT_AVAILABLE = False
    return _SENTIMENT


def _sentiment_agreement(goldstein_tone: str, bert_label: str) -> str:
    if bert_label == "UNKNOWN":
        return "N/A"
    coop = {"strongly cooperative", "cooperative", "neutral"}
    if (goldstein_tone in coop) == (bert_label == "POSITIVE"):
        return "✓ Confirmed"
    return "⚠ Ambiguous"


# ---------------------------------------------------------------------------
# ML warmup (for API / server use)
# ---------------------------------------------------------------------------

def warmup_models():
    """
    Eagerly loads spaCy/DistilBERT once, at server startup, instead of
    lazily on whichever request happens to be first. Call this from a
    FastAPI lifespan hook (or anywhere at process start) so the first
    real /analyze call isn't the one that eats the multi-second model
    load time.
    """
    if NER_AVAILABLE:
        _get_nlp()
    if SENTIMENT_AVAILABLE:
        _get_sentiment_pipeline()


# ---------------------------------------------------------------------------
# ML Layer 3 — KMeans Clustering
# ---------------------------------------------------------------------------

def _cluster_events(df: pd.DataFrame, n_clusters: int = 4) -> pd.Series:
    if not CLUSTER_AVAILABLE or df.empty:
        return pd.Series(["Unclustered"] * len(df), index=df.index)

    le       = LabelEncoder()
    code_enc = le.fit_transform(df["EventRootCode"].fillna("00").astype(str))
    goldstein = df["GoldsteinScale"].fillna(0).values
    X = np.column_stack([code_enc, goldstein]).astype(float)

    k = min(n_clusters, len(df))
    if k < 2:
        return pd.Series(["Single Event"] * len(df), index=df.index)

    # Scale before clustering. EventRootCode (~0-19) and GoldsteinScale
    # (~-10..10) sit on different numeric ranges, and KMeans is purely
    # distance-based — without scaling, the cluster split is dominated by
    # whichever feature happens to have the larger spread rather than by
    # which one actually matters.
    X_scaled = StandardScaler().fit_transform(X)

    km     = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X_scaled)

    cluster_names = {}
    for cid in range(k):
        mask = labels == cid
        subset = df.loc[df.index[mask], "EventRootCode"]
        if subset.empty:
            cluster_names[cid] = "Mixed Activity"
            continue
        dominant = subset.value_counts().idxmax()
        theme = "Mixed Activity"
        for code_set, label in CLUSTER_THEME_MAP.items():
            if dominant in code_set:
                theme = label
                break
        cluster_names[cid] = theme

    return pd.Series([cluster_names[l] for l in labels], index=df.index)


# ---------------------------------------------------------------------------
# Core preprocessing
# ---------------------------------------------------------------------------

def preprocess(date: str, country_code: str) -> pd.DataFrame:
    csv_path = fetch_gdelt_file(date)

    df = pd.read_csv(csv_path, sep="\t", header=None,
                     low_memory=False, usecols=GDELT_COLS, dtype=str)
    df.columns = COL_NAMES

    cc = str(country_code).strip().upper()
    for col in ("Actor1CountryCode", "Actor2CountryCode"):
        df[col] = df[col].astype(str).str.strip().str.upper()

    mask = (df["Actor1CountryCode"] == cc) | (df["Actor2CountryCode"] == cc)
    df   = df[mask].copy()

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["SOURCEURL"])
    df = df.dropna(subset=["EventCode"])
    df = df.reset_index(drop=True)

    df["GoldsteinScale"] = pd.to_numeric(df["GoldsteinScale"], errors="coerce")
    df["EventCode"]      = df["EventCode"].astype(str).str.strip()
    df["EventRootCode"]  = df["EventCode"].str[:2]
    df["EventType"]      = df["EventRootCode"].map(EVENT_MAP).fillna("Other")

    df["Actor1Name"] = df["Actor1Name"].apply(_clean_actor)
    df["Actor2Name"] = df["Actor2Name"].apply(_clean_actor)

    # Fix demonym/adjective forms ("Finn" -> "Finland") BEFORE NER, so NER
    # never gets a chance to mistake a country demonym for a person's name.
    df["Actor1Name"] = df["Actor1Name"].replace(ACTOR_NORMALIZE)
    df["Actor2Name"] = df["Actor2Name"].replace(ACTOR_NORMALIZE)

    df["Tone"]       = df["GoldsteinScale"].apply(get_tone)

    def actor_role(row):
        a1 = row["Actor1CountryCode"] == cc
        a2 = row["Actor2CountryCode"] == cc
        if a1 and a2: return "Both"
        elif a1:      return "Initiator"
        else:         return "Recipient"

    df["CountryRole"] = df.apply(actor_role, axis=1)

    # ML 1 — NER (batched + deduped)
    if NER_AVAILABLE:
        df["Actor1Name"] = _ner_enrich_series(df["Actor1Name"])
        df["Actor2Name"] = _ner_enrich_series(df["Actor2Name"])
    df["Actor1Name"] = df["Actor1Name"].fillna("Unidentified")
    df["Actor2Name"] = df["Actor2Name"].fillna("Unidentified")

    # Resolve generic role labels ("King", "Police", "Government") and bare
    # "Unidentified" actors into readable, attributable text. This used to
    # only run inside get_top5_events() for the dossier cards, which is why
    # NetworkGraph / ActorExplorer / the raw table still showed bare "King"
    # even though the top5 cards looked fine — now every consumer of df
    # gets the same enriched names.
    from src.utils import get_country_name as _gcn

    def _enrich_actor_col(name_col: str, cc_col: str, type_col: str):
        cc_clean = df[cc_col].apply(_clean_code) if cc_col in df.columns else pd.Series([None] * len(df))
        countries = cc_clean.apply(lambda c: _gcn(c) if c else None)
        type_codes = df[type_col] if type_col in df.columns else pd.Series([None] * len(df))
        out = []
        for name, country, type_code in zip(df[name_col], countries, type_codes):
            if name == "Unidentified":
                out.append(_describe_unknown_actor(country, type_code))
            else:
                out.append(_enrich_generic_role(name, country))
        return out

    df["Actor1Name"] = _enrich_actor_col("Actor1Name", "Actor1CountryCode", "Actor1Type1Code")
    df["Actor2Name"] = _enrich_actor_col("Actor2Name", "Actor2CountryCode", "Actor2Type1Code")

    # ML 2 — Sentiment (vectorized text-building, no iterrows)
    if SENTIMENT_AVAILABLE:
        texts = [
            _build_event_text(a1, a2, et)
            for a1, a2, et in zip(df["Actor1Name"], df["Actor2Name"], df["EventType"])
        ]
        sent_res = _run_sentiment_batch(texts)
        df["SentimentLabel"]     = [r["label"].title() for r in sent_res]
        df["SentimentScore"]     = [round(r["score"], 3) for r in sent_res]
        df["SentimentAgreement"] = [
            _sentiment_agreement(t, l.upper())
            for t, l in zip(df["Tone"], df["SentimentLabel"])
        ]
    else:
        df["SentimentLabel"]     = "N/A"
        df["SentimentScore"]     = 0.0
        df["SentimentAgreement"] = "N/A"

    # ML 3 — Clustering (scaled features)
    df["EventCluster"] = _cluster_events(df, n_clusters=4)

    return df


# ---------------------------------------------------------------------------
# Top-5 significant events
# ---------------------------------------------------------------------------

def get_top5_events(df: pd.DataFrame, country_name: str) -> list:
    df_s = df.dropna(subset=["GoldsteinScale"]).copy()
    if df_s.empty:
        return []

    # ── Normalise known noisy actor strings ──────────────────────────────
    _ACTOR_FIXES = {
        # USA
        "U. S.": "United States", "U.S.": "United States",
        "Us":    "United States", "U S":  "United States",
        # UK
        "Uk":    "United Kingdom", "U. K.": "United Kingdom",
        # Kingdom = Kingdom of Saudi Arabia in GDELT
        "Kingdom": "Saudi Arabia",
        # Common GDELT adjective forms that should be country names
        "Bahraini": "Bahrain", "Iraqi":   "Iraq",    "Iranian":  "Iran",
        "Yemeni":   "Yemen",   "Qatari":  "Qatar",   "Kuwaiti":  "Kuwait",
        "Emirati":  "UAE",     "Omani":   "Oman",    "Jordanian":"Jordan",
        "Lebanese": "Lebanon", "Syrian":  "Syria",   "Egyptian": "Egypt",
        "Israeli":  "Israel",  "Turkish": "Turkey",  "Afghan":   "Afghanistan",
        "Pakistani":"Pakistan","Indian":  "India",   "Nigerian": "Nigeria",
        "Kenyan":   "Kenya",   "Ghanaian":"Ghana",   "Ugandan":  "Uganda",
        "French":   "France",  "German":  "Germany", "Spanish":  "Spain",
        "British":  "United Kingdom", "Australian": "Australia",
        "Canadian": "Canada",  "Brazilian":"Brazil", "Mexican":  "Mexico",
        "Russian":  "Russia",  "Chinese": "China",   "Japanese": "Japan",
    }
    for col in ("Actor1Name", "Actor2Name"):
        df_s[col] = df_s[col].replace(_ACTOR_FIXES)

    # ── Filter same-country events ───────────────────────────────────────
    # When both actor names resolve to the same value (e.g. both become
    # "Israel") the event is an internal domestic event that adds no
    # geopolitical signal. Remove these from the top-events selection.
    norm = {k.lower(): v for k, v in _ACTOR_FIXES.items()}
    def _norm(name):
        n = str(name).strip()
        return norm.get(n.lower(), n)

    a1_norm = df_s["Actor1Name"].fillna("").apply(_norm)
    a2_norm = df_s["Actor2Name"].fillna("").apply(_norm)
    # Generic-role phrases ("an unnamed monarch", "an unnamed party from X")
    # can now be textually identical across two DIFFERENT countries after
    # global enrichment — that's not the same actor, so don't dedup on
    # phrase text alone when either side reads like a generic description.
    _GENERIC_PHRASE_PREFIXES = ("a ", "an ", "the ")
    is_generic = a1_norm.str.lower().str.startswith(_GENERIC_PHRASE_PREFIXES) | \
                 a2_norm.str.lower().str.startswith(_GENERIC_PHRASE_PREFIXES)
    same_mask = (a1_norm == a2_norm) & ~is_generic
    if same_mask.any() and not same_mask.all():
        df_s = df_s[~same_mask]

    # Also filter where both country codes are the same (internal events)
    if "Actor1CountryCode" in df_s.columns and "Actor2CountryCode" in df_s.columns:
        cc_same = (
            df_s["Actor1CountryCode"].fillna("") == df_s["Actor2CountryCode"].fillna("")
        ) & (df_s["Actor1CountryCode"].fillna("") != "")
        if cc_same.any() and not cc_same.all():
            df_s = df_s[~cc_same]

    # ── Semantic deduplication ────────────────────────────────────────────
    # GDELT records one row per news article, so the same real-world event
    # covered by N outlets appears as N rows with identical actors, event
    # type, and Goldstein score.  We group by (actor pair + event root code)
    # and keep only the best-supported row (most articles) per group, which
    # is the most reliably reported version of that event.
    num_col = "NumArticles" if "NumArticles" in df_s.columns else None
    if num_col:
        df_s[num_col] = pd.to_numeric(df_s[num_col], errors="coerce").fillna(1)
    else:
        df_s["_art"] = 1
        num_col = "_art"

    group_key = ["Actor1CountryCode", "Actor2CountryCode", "EventRootCode"]
    df_s = (
        df_s.sort_values(num_col, ascending=False)
            .drop_duplicates(subset=group_key, keep="first")
    )

    # Guard: only call nsmallest/nlargest if we have rows
    conflict_n = min(3, len(df_s))
    coop_n     = min(2, len(df_s))

    top5 = (
        pd.concat([
            df_s.nsmallest(conflict_n, "GoldsteinScale"),
            df_s.nlargest(coop_n,     "GoldsteinScale"),
        ])
        .drop_duplicates()
        .copy()
    )
    top5["_abs"] = top5["GoldsteinScale"].abs()
    top5 = top5.sort_values("_abs", ascending=False).head(5).reset_index(drop=True)

    events = []
    for i, row in top5.iterrows():
        score      = row["GoldsteinScale"]
        event_type = row["EventType"]
        a1         = row["Actor1Name"]
        a2         = row["Actor2Name"]
        url        = str(row["SOURCEURL"]).strip()

        # Prefer the specific 3-digit CAMEO code's verb when we have one
        # ("shelled positions held by") over the generic root-level phrase
        # ("engaged in active fighting with").
        event_code = str(row.get("EventCode", "")).strip()
        verb = CAMEO_DETAIL_MAP.get(event_code) or VERB_MAP.get(
            event_type, "was involved in an event with"
        )

        from src.utils import get_country_name

        a1_cc = _clean_code(row.get("Actor1CountryCode"))
        a2_cc = _clean_code(row.get("Actor2CountryCode"))
        a1_country = get_country_name(a1_cc) if a1_cc else None
        a2_country = get_country_name(a2_cc) if a2_cc else None

        # Describe actors GDELT didn't name at all, using whatever it did
        # record (actor type, country) instead of a bare "Unidentified" —
        # and turn bare role labels it DID resolve ("Armed Forces") into
        # something attributable ("Bahrain's armed forces").
        if a1 == "Unidentified":
            a1 = _describe_unknown_actor(a1_country, row.get("Actor1Type1Code"))
        else:
            a1 = _enrich_generic_role(a1, a1_country)
        if a2 == "Unidentified":
            a2 = _describe_unknown_actor(a2_country, row.get("Actor2Type1Code"))
        else:
            a2 = _enrich_generic_role(a2, a2_country)

        try:
            num_articles = int(float(row.get("NumArticles")))
        except (TypeError, ValueError):
            num_articles = None

        country_role = row["CountryRole"]
        sentence = _build_sentence(
            rank=i + 1,
            a1=a1, a2=a2,
            verb=verb,
            event_type=event_type,
            score=score,
            country_role=country_role,
            country_name=country_name,
            num_articles=num_articles,
        )

        events.append({
            "rank":         i + 1,
            "actor1":       a1,
            "actor2":       a2,
            "event_type":   event_type,
            "score":        score,
            "tone":         row["Tone"],
            "role":         country_role,
            "url":          url if url.startswith("http") else None,
            "sentence":     sentence,
            "sentiment":    row.get("SentimentLabel", "N/A"),
            "agreement":    row.get("SentimentAgreement", "N/A"),
            "cluster":      row.get("EventCluster", ""),
            "num_articles": num_articles,
        })

    return events


def _build_sentence(
    rank: int, a1: str, a2: str, verb: str, event_type: str,
    score: float, country_role: str, country_name: str,
    num_articles
) -> str:
    """
    Builds a varied, informative one-sentence event description.

    Avoids the "flat qualifier + actor + verb" pattern that produced
    identical-sounding descriptions for every event of the same type.
    Instead varies the opening based on: whether this country was the
    initiator or recipient, how extreme the score is relative to the
    list's rank, how widely covered the event was, and the event type.
    """
    score_str = f"{score:+.1f}"

    # --- Coverage context ---
    if num_articles and num_articles >= 20:
        coverage = f"widely reported across {num_articles} sources"
    elif num_articles and num_articles >= 5:
        coverage = f"reported across {num_articles} sources"
    else:
        coverage = None

    # --- Role-aware opening ---
    if country_role == "Initiator":
        if score <= -5:
            if rank == 1:
                lead = f"The most alarming development of the day saw **{a1}** {verb} **{a2}**"
            else:
                lead = f"**{a1}** {verb} **{a2}** in one of the day's most serious escalations"
        elif score <= -1:
            lead = f"**{a1}** took an adversarial stance, {verb} **{a2}**"
        elif score >= 7:
            lead = f"In a major diplomatic move, **{a1}** {verb} **{a2}**"
        elif score >= 3:
            lead = f"In a show of cooperative intent, **{a1}** {verb} **{a2}**"
        else:
            lead = f"**{a1}** {verb} **{a2}**"

    elif country_role == "Recipient":
        if score <= -5:
            if rank == 1:
                lead = f"**{country_name}** faced its most serious incident of the day — **{a1}** {verb} **{a2}**"
            else:
                lead = f"**{country_name}** came under pressure as **{a1}** {verb} **{a2}**"
        elif score <= -1:
            lead = f"**{country_name}** was on the receiving end as **{a1}** {verb} **{a2}**"
        elif score >= 5:
            lead = f"**{country_name}** benefited from positive engagement — **{a1}** {verb} **{a2}**"
        else:
            lead = f"**{a1}** {verb} **{a2}**"

    else:  # Both
        lead = f"**{a1}** {verb} **{a2}** in an event involving both sides"

    # --- Tail: score + coverage ---
    tail_parts = [f"Goldstein score: {score_str}"]
    if coverage:
        tail_parts.append(coverage)
    tail = " · ".join(tail_parts)

    return f"{lead} ({tail})."


# ---------------------------------------------------------------------------
# Concise narrative summary
# ---------------------------------------------------------------------------

def summarize(df: pd.DataFrame, country_name: str, date: str, top5_events: list) -> str:
    if df.empty:
        return f"No events found for {country_name} on {date}."

    from src.utils import get_country_name

    fmt_date   = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    total      = len(df)
    avg_score  = df["GoldsteinScale"].mean()
    tone       = get_tone(avg_score)
    g_min      = df["GoldsteinScale"].min()
    g_max      = df["GoldsteinScale"].max()

    top_types = df["EventType"].value_counts().head(3).index.tolist()
    types_str = ", ".join(top_types)

    initiator_pct = round((df["CountryRole"] == "Initiator").sum() / total * 100)
    recipient_pct = round((df["CountryRole"] == "Recipient").sum() / total * 100)

    partner_series = pd.concat([
        df[df["CountryRole"] == "Initiator"]["Actor2CountryCode"],
        df[df["CountryRole"] == "Recipient"]["Actor1CountryCode"],
        df[df["CountryRole"] == "Both"]["Actor2CountryCode"],
    ]).dropna()
    # Missing codes arrive as the string "NAN" after upper-casing; drop them.
    partner_series = partner_series[(partner_series.str.len() == 3) & ~partner_series.isin(["NAN", "NONE"])]
    top_partners   = partner_series.value_counts().head(4).index.tolist()
    partners_str   = ", ".join([get_country_name(c) for c in top_partners]) or "various nations"

    # Cooperative / conflictual split — guard against empty subsets
    coop_df = df[df["GoldsteinScale"] >= 1]
    conf_df = df[df["GoldsteinScale"] <= -1]
    coop_pct = round(len(coop_df) / total * 100)
    conf_pct = round(len(conf_df) / total * 100)

    dom_coop = coop_df["EventType"].value_counts().idxmax() if not coop_df.empty else None
    dom_conf = conf_df["EventType"].value_counts().idxmax() if not conf_df.empty else None

    ambiguous_count = int((df.get("SentimentAgreement", pd.Series(dtype=str)) == "⚠ Ambiguous").sum())

    top_clusters = (
        df["EventCluster"].value_counts().head(2).index.tolist()
        if "EventCluster" in df.columns else []
    )
    cluster_str = " & ".join([f"**{c}**" for c in top_clusters]) if top_clusters else "mixed activity"

    # ── Section 1: Snapshot ──────────────────────────────────────────────
    p1 = (
        f"### 🌐 {country_name} — {fmt_date}\n\n"
        f"**{total} events** recorded (Goldstein range {g_min:+.1f} → {g_max:+.1f}, "
        f"average **{avg_score:+.2f}** — *{tone}*). "
        f"Dominant event types: **{types_str}**. "
        f"ML clustering identified two main activity themes: {cluster_str}."
    )

    # ── Section 2: Top 5 events (compact) ───────────────────────────────
    if top5_events:
        event_lines = []
        for e in top5_events:
            agr_icon = "✓" if e["agreement"] == "✓ Confirmed" else ("⚠" if e["agreement"] == "⚠ Ambiguous" else "·")
            event_lines.append(
                f"**#{e['rank']}** `{e['score']:+.1f}` · {e['event_type']} · "
                f"{e['actor1']} → {e['actor2']} · BERT {agr_icon}"
                + (f" · [source]({e['url']})" if e["url"] else "")
            )
        p2 = "### 📌 Top 5 Events\n\n" + "\n\n".join(event_lines)
    else:
        p2 = ""

    # ── Section 3: Tone breakdown ────────────────────────────────────────
    coop_line = f"**{coop_pct}%** cooperative" + (f" ({dom_coop})" if dom_coop else "")
    conf_line = f"**{conf_pct}%** conflictual" + (f" ({dom_conf})" if dom_conf else "")
    ambig_line = (
        f" · **{ambiguous_count}** events flagged ambiguous by DistilBERT vs Goldstein."
        if ambiguous_count > 0 else ""
    )
    p3 = f"### ⚖️ Tone Breakdown\n\n{coop_line} · {conf_line}{ambig_line}"

    # ── Section 4: Posture ───────────────────────────────────────────────
    p4 = (
        f"### 🤝 Posture & Partners\n\n"
        f"Initiator in **{initiator_pct}%** of events, recipient in **{recipient_pct}%**. "
        f"Key partners: **{partners_str}**."
    )

    # ── Section 5: One-line outlook ──────────────────────────────────────
    if avg_score >= 3:
        outlook = "**Stable & diplomatically active.** Low-volatility signal."
    elif avg_score >= 0:
        outlook = "**Mixed.** Cooperative signals alongside tension. Medium-stability."
    else:
        outlook = "**Turbulent & high-risk.** Conflictual signals dominated."

    p5 = f"### 📡 Outlook\n\n{outlook}"

    footer = (
        "---\n*Auto-generated by GDELT Video Intelligence ML pipeline. "
        "NER · DistilBERT · KMeans applied. "
        "Phase 3: Claude API → TTS → video brief.*"
    )

    parts = [p for p in [p1, p2, p3, p4, p5, footer] if p]
    return "\n\n".join(parts)