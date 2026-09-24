"""ISO3 crosswalk: the universal join key across the four agents.

Each agent names countries its own way:

    Soft Power      ISO3 already ("IND")
    Policy Stance   Gleditsch-Ward numeric codes (750) and its own display names ("India", "UK")
    Trade           BACI names or ISO3 ("Rep. of Korea", "KOR") - accepts ISO3 on input
    Events          CAMEO actor country codes - ISO3 except for a handful of legacy codes

Everything the orchestrator does is keyed on ISO3. This module owns the mapping in
both directions and the free-text gazetteer the intent parser uses to find
countries in a question.

Gleditsch-Ward codes follow Gleditsch & Ward (1999) as used by UCDP, which is the
coding the Policy Stance agent's conflict data actually carries.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional


@dataclass(frozen=True)
class Country:
    iso3: str
    name: str
    gw: Optional[int] = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


# (iso3, display name, Gleditsch-Ward code or None, aliases incl. demonyms)
_TABLE: tuple[tuple[str, str, Optional[int], tuple[str, ...]], ...] = (
    # --- Americas ---
    ("USA", "United States", 2, ("united states of america", "u.s.", "u.s.a.", "america", "american", "americans", "washington")),
    ("CAN", "Canada", 20, ("canadian",)),
    ("BHS", "Bahamas", 31, ("the bahamas", "bahamian")),
    ("CUB", "Cuba", 40, ("cuban",)),
    ("HTI", "Haiti", 41, ("haitian",)),
    ("DOM", "Dominican Republic", 42, ("dominican rep.",)),
    ("JAM", "Jamaica", 51, ("jamaican",)),
    ("TTO", "Trinidad and Tobago", 52, ("trinidad & tobago", "trinidad")),
    ("BRB", "Barbados", 53, ()),
    ("DMA", "Dominica", 54, ()),
    ("GRD", "Grenada", 55, ()),
    ("LCA", "Saint Lucia", 56, ("st. lucia", "st lucia")),
    ("VCT", "Saint Vincent and the Grenadines", 57, ("st. vincent", "saint vincent")),
    ("ATG", "Antigua and Barbuda", 58, ("antigua & barbuda", "antigua")),
    ("KNA", "Saint Kitts and Nevis", 60, ("st. kitts & nevis", "st. kitts and nevis", "saint kitts")),
    ("MEX", "Mexico", 70, ("mexican",)),
    ("BLZ", "Belize", 80, ()),
    ("GTM", "Guatemala", 90, ("guatemalan",)),
    ("HND", "Honduras", 91, ("honduran",)),
    ("SLV", "El Salvador", 92, ("salvadoran",)),
    ("NIC", "Nicaragua", 93, ("nicaraguan",)),
    ("CRI", "Costa Rica", 94, ("costa rican",)),
    ("PAN", "Panama", 95, ("panamanian",)),
    ("COL", "Colombia", 100, ("colombian",)),
    ("VEN", "Venezuela", 101, ("venezuelan",)),
    ("GUY", "Guyana", 110, ()),
    ("SUR", "Suriname", 115, ()),
    ("ECU", "Ecuador", 130, ("ecuadorian",)),
    ("PER", "Peru", 135, ("peruvian",)),
    ("BRA", "Brazil", 140, ("brazilian", "brasil")),
    ("BOL", "Bolivia", 145, ("bolivian",)),
    ("PRY", "Paraguay", 150, ("paraguayan",)),
    ("CHL", "Chile", 155, ("chilean",)),
    ("ARG", "Argentina", 160, ("argentine", "argentinian")),
    ("URY", "Uruguay", 165, ("uruguayan",)),
    # --- Europe ---
    ("GBR", "United Kingdom", 200, ("uk", "u.k.", "britain", "great britain", "british", "england")),
    ("IRL", "Ireland", 205, ("irish",)),
    ("NLD", "Netherlands", 210, ("the netherlands", "holland", "dutch")),
    ("BEL", "Belgium", 211, ("belgian",)),
    ("LUX", "Luxembourg", 212, ()),
    ("FRA", "France", 220, ("french",)),
    ("MCO", "Monaco", 221, ()),
    ("LIE", "Liechtenstein", 223, ()),
    ("CHE", "Switzerland", 225, ("swiss",)),
    ("ESP", "Spain", 230, ("spanish",)),
    ("AND", "Andorra", 232, ()),
    ("PRT", "Portugal", 235, ("portuguese",)),
    ("DEU", "Germany", 260, ("german", "germans")),
    ("POL", "Poland", 290, ("polish",)),
    ("AUT", "Austria", 305, ("austrian",)),
    ("HUN", "Hungary", 310, ("hungarian",)),
    ("CZE", "Czechia", 316, ("czech republic", "czech")),
    ("SVK", "Slovakia", 317, ("slovak",)),
    ("ITA", "Italy", 325, ("italian",)),
    ("SMR", "San Marino", 331, ()),
    ("MLT", "Malta", 338, ("maltese",)),
    ("ALB", "Albania", 339, ("albanian",)),
    ("SRB", "Serbia", 340, ("serbian",)),
    ("MNE", "Montenegro", 341, ()),
    ("MKD", "North Macedonia", 343, ("macedonia",)),
    ("HRV", "Croatia", 344, ("croatian",)),
    ("BIH", "Bosnia and Herzegovina", 346, ("bosnia", "bosnian")),
    ("XKX", "Kosovo", 347, ()),
    ("SVN", "Slovenia", 349, ("slovenian",)),
    ("GRC", "Greece", 350, ("greek",)),
    ("CYP", "Cyprus", 352, ("cypriot",)),
    ("BGR", "Bulgaria", 355, ("bulgarian",)),
    ("MDA", "Moldova", 359, ("moldovan",)),
    ("ROU", "Romania", 360, ("romanian",)),
    ("RUS", "Russia", 365, ("russian federation", "russian", "russians", "moscow", "kremlin")),
    ("EST", "Estonia", 366, ("estonian",)),
    ("LVA", "Latvia", 367, ("latvian",)),
    ("LTU", "Lithuania", 368, ("lithuanian",)),
    ("UKR", "Ukraine", 369, ("ukrainian", "kyiv")),
    ("BLR", "Belarus", 370, ("belarusian",)),
    ("ARM", "Armenia", 371, ("armenian",)),
    ("GEO", "Georgia", 372, ("georgian",)),
    ("AZE", "Azerbaijan", 373, ("azerbaijani",)),
    ("FIN", "Finland", 375, ("finnish",)),
    ("SWE", "Sweden", 380, ("swedish",)),
    ("NOR", "Norway", 385, ("norwegian",)),
    ("DNK", "Denmark", 390, ("danish",)),
    ("ISL", "Iceland", 395, ("icelandic",)),
    # --- Africa ---
    ("CPV", "Cabo Verde", 402, ("cape verde",)),
    ("STP", "Sao Tome and Principe", 403, ("são tomé & príncipe", "sao tome")),
    ("GNB", "Guinea-Bissau", 404, ("guinea bissau",)),
    ("GNQ", "Equatorial Guinea", 411, ()),
    ("GMB", "Gambia", 420, ("the gambia",)),
    ("MLI", "Mali", 432, ("malian",)),
    ("SEN", "Senegal", 433, ("senegalese",)),
    ("BEN", "Benin", 434, ()),
    ("MRT", "Mauritania", 435, ()),
    ("NER", "Niger", 436, ()),
    ("CIV", "Cote d'Ivoire", 437, ("côte d'ivoire", "ivory coast", "ivorian")),
    ("GIN", "Guinea", 438, ()),
    ("BFA", "Burkina Faso", 439, ()),
    ("LBR", "Liberia", 450, ("liberian",)),
    ("SLE", "Sierra Leone", 451, ()),
    ("GHA", "Ghana", 452, ("ghanaian",)),
    ("TGO", "Togo", 461, ()),
    ("CMR", "Cameroon", 471, ("cameroonian",)),
    ("NGA", "Nigeria", 475, ("nigerian",)),
    ("GAB", "Gabon", 481, ()),
    ("CAF", "Central African Republic", 482, ()),
    ("TCD", "Chad", 483, ("chadian",)),
    ("COG", "Republic of the Congo", 484, ("congo-brazzaville", "congo brazzaville", "rep. of congo")),
    ("COD", "DR Congo", 490, ("democratic republic of the congo", "drc", "d.r. congo", "congo-kinshasa", "congo")),
    ("UGA", "Uganda", 500, ("ugandan",)),
    ("KEN", "Kenya", 501, ("kenyan",)),
    ("TZA", "Tanzania", 510, ("tanzanian",)),
    ("BDI", "Burundi", 516, ()),
    ("RWA", "Rwanda", 517, ("rwandan",)),
    ("SOM", "Somalia", 520, ("somali",)),
    ("DJI", "Djibouti", 522, ()),
    ("ETH", "Ethiopia", 530, ("ethiopian",)),
    ("ERI", "Eritrea", 531, ("eritrean",)),
    ("AGO", "Angola", 540, ("angolan",)),
    ("MOZ", "Mozambique", 541, ()),
    ("ZMB", "Zambia", 551, ("zambian",)),
    ("ZWE", "Zimbabwe", 552, ("zimbabwean",)),
    ("MWI", "Malawi", 553, ()),
    ("ZAF", "South Africa", 560, ("south african",)),
    ("NAM", "Namibia", 565, ()),
    ("LSO", "Lesotho", 570, ()),
    ("BWA", "Botswana", 571, ()),
    ("SWZ", "Eswatini", 572, ("swaziland",)),
    ("MDG", "Madagascar", 580, ()),
    ("COM", "Comoros", 581, ()),
    ("MUS", "Mauritius", 590, ()),
    ("SYC", "Seychelles", 591, ()),
    ("MAR", "Morocco", 600, ("moroccan",)),
    ("DZA", "Algeria", 615, ("algerian",)),
    ("TUN", "Tunisia", 616, ("tunisian",)),
    ("LBY", "Libya", 620, ("libyan",)),
    ("SDN", "Sudan", 625, ("sudanese",)),
    ("SSD", "South Sudan", 626, ()),
    # --- Middle East ---
    ("IRN", "Iran", 630, ("iranian", "tehran", "persia")),
    ("TUR", "Turkiye", 640, ("turkey", "türkiye", "turkish")),
    ("IRQ", "Iraq", 645, ("iraqi",)),
    ("EGY", "Egypt", 651, ("egyptian",)),
    ("SYR", "Syria", 652, ("syrian",)),
    ("LBN", "Lebanon", 660, ("lebanese",)),
    ("JOR", "Jordan", 663, ("jordanian",)),
    ("ISR", "Israel", 666, ("israeli",)),
    ("PSE", "Palestine", None, ("palestinian", "state of palestine", "gaza", "west bank")),
    ("SAU", "Saudi Arabia", 670, ("saudi",)),
    ("YEM", "Yemen", 678, ("yemeni",)),
    ("KWT", "Kuwait", 690, ()),
    ("BHR", "Bahrain", 692, ()),
    ("QAT", "Qatar", 694, ("qatari",)),
    ("ARE", "United Arab Emirates", 696, ("uae", "u.a.e.", "emirates", "emirati")),
    ("OMN", "Oman", 698, ()),
    # --- Asia ---
    ("AFG", "Afghanistan", 700, ("afghan",)),
    ("TKM", "Turkmenistan", 701, ()),
    ("TJK", "Tajikistan", 702, ()),
    ("KGZ", "Kyrgyzstan", 703, ()),
    ("UZB", "Uzbekistan", 704, ()),
    ("KAZ", "Kazakhstan", 705, ("kazakh",)),
    ("CHN", "China", 710, ("people's republic of china", "prc", "chinese", "beijing")),
    ("MNG", "Mongolia", 712, ("mongolian",)),
    ("TWN", "Taiwan", 713, ("taiwanese", "taipei")),
    ("PRK", "North Korea", 731, ("dprk", "democratic people's republic of korea", "pyongyang")),
    ("KOR", "South Korea", 732, ("republic of korea", "korea", "korean", "seoul")),
    ("JPN", "Japan", 740, ("japanese", "tokyo")),
    ("IND", "India", 750, ("indian", "new delhi")),
    ("BTN", "Bhutan", 760, ()),
    ("PAK", "Pakistan", 770, ("pakistani",)),
    ("BGD", "Bangladesh", 771, ("bangladeshi",)),
    ("MMR", "Myanmar", 775, ("burma", "burmese")),
    ("LKA", "Sri Lanka", 780, ("sri lankan",)),
    ("MDV", "Maldives", 781, ()),
    ("NPL", "Nepal", 790, ("nepali", "nepalese")),
    ("THA", "Thailand", 800, ("thai",)),
    ("KHM", "Cambodia", 811, ("cambodian",)),
    ("LAO", "Laos", 812, ("lao pdr",)),
    ("VNM", "Vietnam", 816, ("viet nam", "vietnamese")),
    ("MYS", "Malaysia", 820, ("malaysian",)),
    ("SGP", "Singapore", 830, ("singaporean",)),
    ("BRN", "Brunei", 835, ()),
    ("PHL", "Philippines", 840, ("filipino", "philippine")),
    ("IDN", "Indonesia", 850, ("indonesian",)),
    ("TLS", "Timor-Leste", 860, ("east timor",)),
    # --- Oceania ---
    ("AUS", "Australia", 900, ("australian",)),
    ("PNG", "Papua New Guinea", 910, ()),
    ("NZL", "New Zealand", 920, ()),
    ("VUT", "Vanuatu", 935, ()),
    ("SLB", "Solomon Islands", 940, ()),
    ("KIR", "Kiribati", 946, ()),
    ("TUV", "Tuvalu", 947, ()),
    ("FJI", "Fiji", 950, ()),
    ("TON", "Tonga", 955, ()),
    ("NRU", "Nauru", 970, ()),
    ("MHL", "Marshall Islands", 983, ()),
    ("PLW", "Palau", 986, ()),
    ("FSM", "Micronesia", 987, ()),
    ("WSM", "Samoa", 990, ()),
    # --- territories other agents report on (no GW code) ---
    ("HKG", "Hong Kong", None, ("hong kong sar",)),
    ("MAC", "Macao", None, ("macau",)),
    ("PRI", "Puerto Rico", None, ()),
    ("GRL", "Greenland", None, ()),
)

# CAMEO actor country codes that differ from ISO3. GDELT V1 codes actors with
# CAMEO, which predates a few ISO changes. Verified against a GDELT V1 daily
# export (see docs/MODULE_NOTES.md); anything not listed uses the ISO3 code.
CAMEO_OVERRIDES: dict[str, str] = {
    "TLS": "TMP",  # seen in the 2026-09-22 export (16 events); "TLS" does not occur
    "ROU": "ROM",  # CAMEO manual; neither code occurred in the sampled export
}

# Upper-case three-letter tokens that are also English words. An ISO3 token in a
# question is only trusted when it is not one of these.
_ISO3_STOPWORDS = {"AND", "ARE", "CAN", "PER", "BEN", "MAR", "TON", "COM", "GIN", "DOM", "GAB", "CAF", "MAC", "NIC", "SUR", "PAN", "ISL", "CHE", "POL", "SEN"}

COUNTRIES: dict[str, Country] = {
    iso3: Country(iso3=iso3, name=name, gw=gw, aliases=aliases) for iso3, name, gw, aliases in _TABLE
}
GW_TO_ISO3: dict[int, str] = {c.gw: c.iso3 for c in COUNTRIES.values() if c.gw is not None}
_CAMEO_TO_ISO3 = {code: iso3 for iso3, code in CAMEO_OVERRIDES.items()}


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'Türkiye' and 'Turkiye' match."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


@lru_cache(maxsize=1)
def _name_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for country in COUNTRIES.values():
        for label in (country.name, *country.aliases):
            index.setdefault(_fold(label), country.iso3)
    return index


def get(iso3: Optional[str]) -> Optional[Country]:
    if not iso3:
        return None
    return COUNTRIES.get(str(iso3).upper())


def name_of(iso3: Optional[str]) -> str:
    country = get(iso3)
    return country.name if country else (iso3 or "unknown")


def resolve(value: object) -> Optional[str]:
    """Resolve an ISO3 code, GW code, CAMEO code, or country name to ISO3."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return GW_TO_ISO3.get(int(value))
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return GW_TO_ISO3.get(int(text))
    upper = text.upper()
    if len(upper) == 3 and upper.isalpha():
        if upper in COUNTRIES:
            return upper
        if upper in _CAMEO_TO_ISO3:
            return _CAMEO_TO_ISO3[upper]
    return _name_index().get(_fold(text))


def to_cameo(iso3: str) -> str:
    """The code GDELT's Actor*CountryCode columns use for this country."""
    return CAMEO_OVERRIDES.get(iso3.upper(), iso3.upper())


def from_cameo(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    upper = str(code).strip().upper()
    if upper in _CAMEO_TO_ISO3:
        return _CAMEO_TO_ISO3[upper]
    return upper if upper in COUNTRIES else None


@dataclass(frozen=True)
class Mention:
    iso3: str
    name: str
    matched: str
    start: int


@lru_cache(maxsize=1)
def _mention_pattern() -> re.Pattern[str]:
    labels = sorted(_name_index().keys(), key=len, reverse=True)
    escaped = [re.escape(label) for label in labels]
    # Word-bounded, longest label first, so "South Korea" wins over "Korea" and
    # "Nigeria" is never read as "Niger".
    return re.compile(r"(?<![\w.])(" + "|".join(escaped) + r")(?![\w])", re.IGNORECASE)


def find_mentions(text: str) -> list[Mention]:
    """Every distinct country mentioned in free text, in order of appearance."""
    folded = _fold(text)
    found: list[Mention] = []
    seen: set[str] = set()
    index = _name_index()

    for match in _mention_pattern().finditer(folded):
        label = match.group(1)
        if label in ("america", "american", "americans") and re.search(r"\b(latin|south|north|central)\s+$", folded[: match.start(1)]):
            continue
        iso3 = index.get(label)
        if iso3 and iso3 not in seen:
            seen.add(iso3)
            found.append(Mention(iso3=iso3, name=COUNTRIES[iso3].name, matched=text[match.start(1):match.end(1)], start=match.start(1)))

    for match in re.finditer(r"\b(US|USA|UK|UAE|EU|[A-Z]{3})\b", text):
        token = match.group(1)
        if token == "US":
            iso3 = "USA"
        elif token in ("UK",):
            iso3 = "GBR"
        elif token == "UAE":
            iso3 = "ARE"
        elif token in _ISO3_STOPWORDS or token == "EU":
            continue
        else:
            iso3 = token if token in COUNTRIES else None
        if iso3 and iso3 not in seen:
            seen.add(iso3)
            found.append(Mention(iso3=iso3, name=COUNTRIES[iso3].name, matched=token, start=match.start(1)))

    found.sort(key=lambda m: m.start)
    return found


def all_iso3() -> Iterable[str]:
    return COUNTRIES.keys()
