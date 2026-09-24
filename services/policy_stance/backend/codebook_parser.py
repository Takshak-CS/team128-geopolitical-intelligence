import difflib
import json
import os
import re
from collections import defaultdict
from typing import DefaultDict

import pdfplumber

from backend.paths import ROOT_DIR, ensure_directories, output_file


GW_COUNTRY_CODES = {
    # Americas
    "2": "USA", "20": "Canada", "31": "Bahamas", "40": "Cuba", "41": "Haiti",
    "42": "Dominican Republic", "51": "Jamaica", "52": "Trinidad & Tobago",
    "53": "Barbados", "54": "Dominica", "55": "Grenada", "56": "St. Lucia",
    "57": "St. Vincent", "58": "Antigua & Barbuda", "60": "St. Kitts & Nevis",
    "70": "Mexico", "80": "Belize", "90": "Guatemala", "91": "Honduras",
    "92": "El Salvador", "93": "Nicaragua", "94": "Costa Rica", "95": "Panama",
    "100": "Colombia", "101": "Venezuela", "110": "Guyana", "115": "Suriname",
    "130": "Ecuador", "135": "Peru", "140": "Brazil", "145": "Bolivia",
    "150": "Paraguay", "155": "Chile", "160": "Argentina", "165": "Uruguay",
    # Europe
    "200": "UK", "205": "Ireland", "210": "Netherlands", "211": "Belgium",
    "212": "Luxembourg", "220": "France", "221": "Monaco", "225": "Switzerland",
    "230": "Spain", "232": "Andorra", "235": "Portugal", "255": "Germany",
    "260": "West Germany", "265": "East Germany", "269": "Liechtenstein",
    "290": "Poland", "300": "Austro-Hungary", "305": "Austria", "310": "Hungary",
    "315": "Czechoslovakia", "316": "Czech Republic", "317": "Slovakia",
    "325": "Italy", "327": "Vatican", "331": "San Marino", "338": "Malta",
    "339": "Albania", "341": "Kosovo", "343": "North Macedonia", "344": "Croatia",
    "345": "Yugoslavia", "346": "Bosnia", "347": "Serbia", "348": "Slovenia",
    "349": "Montenegro", "350": "Greece", "352": "Cyprus", "355": "Bulgaria",
    "360": "Romania", "365": "Russia", "366": "Estonia", "367": "Latvia",
    "368": "Lithuania", "369": "Ukraine", "370": "Belarus", "371": "Armenia",
    "372": "Georgia", "373": "Azerbaijan", "375": "Finland", "380": "Sweden",
    "385": "Norway", "390": "Denmark", "395": "Iceland",
    # Africa
    "402": "Cape Verde", "403": "São Tomé & Príncipe", "404": "Guinea-Bissau",
    "411": "Equatorial Guinea", "420": "Gambia", "432": "Mali",
    "433": "Senegal", "434": "Benin", "435": "Mauritania", "436": "Niger",
    "437": "Ivory Coast", "438": "Guinea", "439": "Burkina Faso",
    "450": "Liberia", "451": "Sierra Leone", "452": "Ghana", "461": "Togo",
    "471": "Cameroon", "475": "Nigeria", "481": "Gabon",
    "482": "Central African Republic", "483": "Congo", "484": "DRC",
    "490": "Uganda", "500": "Rwanda", "501": "Burundi",
    "510": "Ethiopia", "516": "Burundi", "517": "Rwanda",
    "520": "Eritrea", "522": "Djibouti", "530": "Somalia",
    "531": "Somaliland", "540": "Angola", "541": "Mozambique",
    "551": "Zambia", "552": "Zimbabwe", "553": "Malawi",
    "560": "South Africa", "565": "Namibia", "570": "Lesotho",
    "571": "Botswana", "572": "Swaziland", "580": "Madagascar",
    "581": "Comoros", "590": "Mauritius", "600": "Morocco",
    "615": "Algeria", "616": "Tunisia", "620": "Libya", "625": "Sudan",
    "626": "South Sudan",
    # Middle East
    "630": "Iran", "640": "Turkey", "645": "Iraq", "651": "Egypt",
    "652": "Syria", "660": "Lebanon", "663": "Jordan", "666": "Israel",
    "667": "Palestine", "670": "Saudi Arabia", "672": "Yemen",
    "678": "Yemen", "679": "Yemen Arab Republic", "680": "Yemen PDR",
    "690": "Kuwait", "692": "Bahrain", "694": "Qatar", "696": "UAE",
    "698": "Oman",
    # Asia
    "700": "Afghanistan", "701": "Tajikistan", "702": "Kyrgyzstan",
    "703": "Turkmenistan", "704": "Uzbekistan", "705": "Kazakhstan",
    "710": "China", "711": "Mongolia", "712": "Tibet", "713": "Taiwan",
    "730": "Korea", "731": "North Korea", "732": "South Korea",
    "740": "Japan", "750": "India", "760": "Bhutan", "770": "Pakistan",
    "771": "Bangladesh", "772": "Myanmar", "775": "Myanmar",
    "780": "Sri Lanka", "790": "Nepal", "800": "Thailand",
    "811": "Cambodia", "812": "Laos", "816": "Vietnam",
    "817": "South Vietnam", "820": "Malaysia", "830": "Singapore",
    "835": "Brunei", "840": "Philippines", "850": "Indonesia",
    "860": "East Timor", "900": "Australia", "910": "Papua New Guinea",
    "920": "New Zealand", "935": "Vanuatu", "940": "Solomon Islands",
    "950": "Fiji", "955": "Tonga", "983": "Marshall Islands",
    "986": "Palau", "987": "Micronesia", "990": "Nauru",
}

# --- Team 128 integration fix (see docs/MODULE_NOTES.md in the platform repo) ---
# Several entries above do not match the Gleditsch-Ward codes UCDP actually uses,
# so conflict records were labelled with the wrong country: 490 is DR Congo (not
# Uganda), 501 Kenya (not Burundi), 510 Tanzania, 530 Ethiopia (not Somalia),
# 701-703 are Turkmenistan/Tajikistan/Kyrgyzstan, 711/712 Tibet/Mongolia, and
# 340-349 the post-Yugoslav states. Two codes sharing one display name also made
# one country's profile overwrite the other's (country profiles are keyed by name).
# Germany is 260 in GW; 255 is pre-1945 Germany.
GW_COUNTRY_CODES.update({
    "223": "Liechtenstein", "255": "Germany (pre-1945)", "260": "Germany",
    "340": "Serbia", "341": "Montenegro", "343": "North Macedonia", "344": "Croatia",
    "345": "Yugoslavia", "346": "Bosnia", "347": "Kosovo", "349": "Slovenia", "359": "Moldova",
    "483": "Chad", "484": "Congo", "490": "DRC", "500": "Uganda", "501": "Kenya",
    "510": "Tanzania", "516": "Burundi", "517": "Rwanda", "520": "Somalia",
    "522": "Djibouti", "530": "Ethiopia", "531": "Eritrea", "591": "Seychelles",
    "701": "Turkmenistan", "702": "Tajikistan", "703": "Kyrgyzstan",
    "711": "Tibet", "712": "Mongolia", "781": "Maldives",
    "946": "Kiribati", "947": "Tuvalu", "970": "Nauru", "990": "Samoa",
})
for _not_a_gw_code in ("269", "348", "672", "772"):
    GW_COUNTRY_CODES.pop(_not_a_gw_code, None)

COMMON_CODEBOOKS = {
    "global": {
        "incompatibility": {"1": "territory", "2": "government"},
        "intensity_level": {"0": "none", "1": "minor", "2": "war"},
        "type_of_conflict": {
            "1": "extrasystemic",
            "2": "interstate",
            "3": "intrastate",
            "4": "internationalized intrastate",
        },
        "vote": {
            "1": "yes",
            "2": "abstain",
            "3": "no",
            "8": "not present",
            "9": "absent",
            "Y": "yes",
            "N": "no",
            "A": "abstain",
            "X": "absent",
            "9.0": "absent",
        },
        "ms_vote": {"Y": "yes", "N": "no", "A": "abstain", "X": "absent"},
        "vote_enc": {"1": "no", "2": "absent", "3": "yes", "8": "not present", "9": "abstain"},
        "where_prec": {
            "1": "exact location",
            "2": "near exact location",
            "3": "administrative area",
            "4": "provincial area",
            "5": "national estimate",
        },
        "country_codes": GW_COUNTRY_CODES,
    }
}

COUNTRY_COLUMNS = {
    "gwno",
    "gwno_a",
    "gwno_b",
    "gwno_loc",
    "gwno_location",
    "gwno_battle",
    "gwnoa",
    "gwnob",
    "country_id",
    "ccode",
    "ccode1",
    "ccode2",
    "ms_code",
}

_CODEBOOK_CACHE = None


def normalize_key(value: str) -> str:
    value = os.path.splitext(os.path.basename(str(value)))[0]
    value = value.lower()
    value = re.sub(r"codebook|csv|xlsx|zip|pdf|v\d+|version", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def canonical_dataset_name(value: str) -> str:
    text = normalize_key(value)
    mapping = {
        "ucdp prio acd": "ucdp-prio-acd",
        "ucdp dyadic": "ucdp-dyadic",
        "ucdp nonstate": "ucdp-nonstate",
        "ucdp onesided": "ucdp-onesided",
        "ucdp candidate": "ucdp-candidate",
        "ucdp brd": "ucdp-brd",
        "battledeaths": "ucdp-brd",
        "ucdp actor": "ucdp-actor",
        "issues dataset dyadyear": "ucdp_issues_dataset_dyadyear",
        "peace agreements": "ucdp-peace-agreements",
        "organizedviolencecy": "organizedviolencecy",
        "par": "par",
        "cace 1989 2017": "CACE_1989-2017",
        "ged251": "GED",
        "gedevent": "GED",
        "un votes clean": "un_votes_clean",
        "ga voting": "2025_7_23_ga_voting",
        "2025 7 23 ga voting": "2025_7_23_ga_voting",
    }
    for needle, dataset_name in mapping.items():
        if needle in text:
            return dataset_name
    return text.replace(" ", "-") or "unknown_dataset"


def _column_name_from_line(line: str) -> str | None:
    compact = normalize_key(line)
    normalized = compact.replace(" ", "_")
    for column in COUNTRY_COLUMNS | set(COMMON_CODEBOOKS["global"].keys()):
        if column in normalized:
            return column
    match = re.search(r"\b([a-z][a-z0-9_]{2,40})\b", normalized)
    if match and match.group(1) not in {"page", "table", "codes", "values"}:
        return match.group(1)
    return None


def _looks_like_label(value: str) -> bool:
    if not value:
        return False
    cleaned = value.strip(" -:;,.\t")
    return bool(cleaned) and any(ch.isalpha() for ch in cleaned)


def _add_mapping(target: DefaultDict[str, dict[str, str]], column_name: str, code: str, label: str) -> None:
    code = str(code).strip()
    label = re.sub(r"\s+", " ", str(label)).strip(" -:;,.\t")
    if not code or not label:
        return
    if len(code) > 8 or not _looks_like_label(label):
        return
    target[column_name][code] = label


def _parse_lines(text: str) -> DefaultDict[str, dict[str, str]]:
    parsed: DefaultDict[str, dict[str, str]] = defaultdict(dict)
    current_column = "global"
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        maybe_column = _column_name_from_line(line)
        if maybe_column and len(line.split()) <= 10:
            current_column = maybe_column
        explicit_match = re.match(r"^\s*([A-Za-z0-9._-]{1,12})\s*[:=]\s*(.+)$", line)
        if explicit_match:
            _add_mapping(parsed, current_column, explicit_match.group(1), explicit_match.group(2))
            continue
        numeric_match = re.match(r"^\s*(\d{1,6})\s+([A-Za-z][A-Za-z0-9 &'()/.,-]{2,})$", line)
        if numeric_match:
            _add_mapping(parsed, current_column, numeric_match.group(1), numeric_match.group(2))
    return parsed


def _parse_tables(tables: list[list[list[str]]]) -> DefaultDict[str, dict[str, str]]:
    parsed: DefaultDict[str, dict[str, str]] = defaultdict(dict)
    current_column = "global"
    for table in tables:
        if not table:
            continue
        header_text = " ".join(filter(None, [str(cell).strip() for cell in table[0] if cell]))
        maybe_column = _column_name_from_line(header_text)
        if maybe_column:
            current_column = maybe_column
        for row in table:
            cells = [re.sub(r"\s+", " ", str(cell)).strip() for cell in row if cell is not None]
            if len(cells) < 2:
                continue
            left, right = cells[0], cells[1]
            if re.fullmatch(r"[A-Za-z0-9._-]{1,12}", left) and _looks_like_label(right):
                _add_mapping(parsed, current_column, left, right)
    return parsed


def _merge_nested(target: dict[str, dict[str, str]], source: DefaultDict[str, dict[str, str]]) -> None:
    for column_name, mapping in source.items():
        target.setdefault(column_name, {})
        target[column_name].update(mapping)


def build_codebook(force_rebuild: bool = False) -> dict[str, dict[str, dict[str, str]]]:
    global _CODEBOOK_CACHE
    ensure_directories()
    output_path = output_file("codebook_merged.json")
    if _CODEBOOK_CACHE is not None and not force_rebuild:
        return _CODEBOOK_CACHE
    if os.path.exists(output_path) and not force_rebuild:
        with open(output_path, "r", encoding="utf-8") as handle:
            _CODEBOOK_CACHE = json.load(handle)
            return _CODEBOOK_CACHE

    codebook: dict[str, dict[str, dict[str, str]]] = {}
    data_candidates = [name for name in os.listdir(ROOT_DIR) if name.lower().endswith((".csv", ".zip", ".xlsx"))]
    normalized_candidates = {normalize_key(name): name for name in data_candidates}

    for file_name in os.listdir(ROOT_DIR):
        if not file_name.lower().endswith(".pdf"):
            continue
        pdf_path = os.path.join(ROOT_DIR, file_name)
        dataset_name = canonical_dataset_name(file_name)
        best = difflib.get_close_matches(normalize_key(file_name), list(normalized_candidates.keys()), n=1, cutoff=0.3)
        if best:
            dataset_name = canonical_dataset_name(normalized_candidates[best[0]])
        dataset_bucket = codebook.setdefault(dataset_name, {})
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    tables = page.extract_tables() or []
                    _merge_nested(dataset_bucket, _parse_lines(text))
                    _merge_nested(dataset_bucket, _parse_tables(tables))
        except Exception:
            continue

    defaults = {
        "global",
        "ucdp-prio-acd",
        "ucdp-dyadic",
        "ucdp-brd",
        "GED",
        "par",
        "CACE_1989-2017",
        "ucdp-peace-agreements",
        "un_votes_clean",
        "2025_7_23_ga_voting",
    }
    for dataset_name in set(codebook.keys()) | defaults:
        bucket = codebook.setdefault(dataset_name, {})
        for column_name, mapping in COMMON_CODEBOOKS["global"].items():
            bucket.setdefault(column_name, {})
            bucket[column_name].update(mapping)
        for country_column in COUNTRY_COLUMNS:
            bucket.setdefault(country_column, {})
            bucket[country_column].update(GW_COUNTRY_CODES)

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(codebook, handle, indent=2, ensure_ascii=False, sort_keys=True)

    _CODEBOOK_CACHE = codebook
    return codebook


def decode(dataset_name: str, column_name: str, code) -> str:
    if code is None:
        return ""
    codebook = build_codebook()
    dataset_key = canonical_dataset_name(dataset_name or "global")
    column_key = str(column_name or "global").strip().lower()
    raw_code = str(code).strip()
    search_order = [
        (dataset_key, column_key),
        (dataset_key, "country_codes"),
        (dataset_key, "global"),
        ("global", column_key),
        ("global", "country_codes"),
        ("global", "global"),
    ]
    if column_key in COUNTRY_COLUMNS:
        search_order.insert(1, ("global", column_key))
    for ds_key, col_key in search_order:
        label = codebook.get(ds_key, {}).get(col_key, {}).get(raw_code)
        if label:
            return label
        if raw_code.endswith(".0"):
            label = codebook.get(ds_key, {}).get(col_key, {}).get(raw_code[:-2])
            if label:
                return label
    return raw_code
