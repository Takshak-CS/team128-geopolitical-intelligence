import hashlib
import json
import math
import os
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.codebook_parser import canonical_dataset_name, decode
from backend.paths import ROOT_DIR, ensure_directories


ISO3_TO_GW = {
    "USA": 2, "CAN": 20, "CUB": 40, "MEX": 70, "COL": 100, "PER": 135, "BRA": 140, "CHL": 155,
    "GBR": 200, "NLD": 210, "BEL": 211, "LUX": 212, "FRA": 220, "CHE": 225, "ESP": 230, "PRT": 235,
    "DEU": 255, "POL": 290, "AUT": 305, "HUN": 310, "SVK": 317, "ITA": 325, "MLT": 338, "ALB": 339,
    "BIH": 346, "MNE": 349, "GRC": 350, "CYP": 352, "BGR": 355, "ROU": 360, "RUS": 365, "EST": 366,
    "LVA": 367, "LTU": 368, "UKR": 369, "BLR": 370, "ARM": 371, "GEO": 372, "AZE": 373, "FIN": 375,
    "SWE": 380, "NOR": 385, "DNK": 390, "ISL": 395, "MAR": 600, "DZA": 615, "TUN": 616, "LBY": 620,
    "SDN": 625, "IRN": 630, "TUR": 640, "IRQ": 645, "EGY": 651, "SYR": 652, "LBN": 660, "JOR": 663,
    "ISR": 666, "SAU": 670, "KWT": 690, "QAT": 694, "ARE": 696, "AFG": 700, "CHN": 710, "TWN": 713,
    "PRK": 731, "KOR": 732, "JPN": 740, "IND": 750, "BTN": 760, "PAK": 770, "LKA": 780, "NPL": 790,
    "THA": 800, "KHM": 811, "LAO": 812, "VNM": 816, "MYS": 820, "SGP": 830, "PHL": 840, "IDN": 850,
    "AUS": 900, "NZL": 920,
}

# --- Team 128 integration fix (see docs/MODULE_NOTES.md in the platform repo) ---
# UN voting rows identify members by ISO3 (ms_code). The table above covers ~85
# countries; every other member fell through to a synthetic code, which drops it
# from country profiles and alliance blocs (profiles only cover GW 2-920). This
# completes the mapping for UN members, plus the legacy codes the 1989-1992 votes
# use. DEU is 260 in Gleditsch-Ward, matching the UCDP conflict data.
ISO3_TO_GW.update({
    "BHS": 31, "HTI": 41, "DOM": 42, "JAM": 51, "TTO": 52, "BRB": 53, "DMA": 54, "GRD": 55,
    "LCA": 56, "VCT": 57, "ATG": 58, "KNA": 60, "BLZ": 80, "GTM": 90, "HND": 91, "SLV": 92,
    "NIC": 93, "CRI": 94, "PAN": 95, "VEN": 101, "GUY": 110, "SUR": 115, "ECU": 130,
    "BOL": 145, "PRY": 150, "ARG": 160, "URY": 165, "IRL": 205, "MCO": 221, "LIE": 223,
    "AND": 232, "DEU": 260, "CZE": 316, "SMR": 331, "SRB": 340, "MKD": 343, "HRV": 344,
    "SVN": 349, "MDA": 359, "CPV": 402, "STP": 403, "GNB": 404, "GNQ": 411, "GMB": 420,
    "MLI": 432, "SEN": 433, "BEN": 434, "MRT": 435, "NER": 436, "CIV": 437, "GIN": 438,
    "BFA": 439, "LBR": 450, "SLE": 451, "GHA": 452, "TGO": 461, "CMR": 471, "NGA": 475,
    "GAB": 481, "CAF": 482, "TCD": 483, "COG": 484, "COD": 490, "UGA": 500, "KEN": 501,
    "TZA": 510, "BDI": 516, "RWA": 517, "SOM": 520, "DJI": 522, "ETH": 530, "ERI": 531,
    "AGO": 540, "MOZ": 541, "ZMB": 551, "ZWE": 552, "MWI": 553, "ZAF": 560, "NAM": 565,
    "LSO": 570, "BWA": 571, "SWZ": 572, "MDG": 580, "COM": 581, "MUS": 590, "SYC": 591,
    "SSD": 626, "YEM": 678, "BHR": 692, "OMN": 698, "TKM": 701, "TJK": 702, "KGZ": 703,
    "UZB": 704, "KAZ": 705, "MNG": 712, "BGD": 771, "MMR": 775, "MDV": 781, "BRN": 835,
    "TLS": 860, "PNG": 910, "VUT": 935, "SLB": 940, "KIR": 946, "TUV": 947, "FJI": 950,
    "TON": 955, "NRU": 970, "MHL": 983, "PLW": 986, "FSM": 987, "WSM": 990,
    # Legacy UN member codes still present in 1989-1992 votes.
    "SUN": 365, "YUG": 345, "CSK": 315, "DDR": 265, "ZAR": 490, "YMD": 680, "YAR": 678, "BUR": 775,
    "GER": 260, "SCG": 345,
})

COUNTRY_NAME_ALIASES = {
    "united states": 2,
    "usa": 2,
    "united states of america": 2,
    "uk": 200,
    "united kingdom": 200,
    "russian federation": 365,
    "south korea": 732,
    "republic of korea": 732,
    "north korea": 731,
    "democratic people's republic of korea": 731,
    "uae": 696,
    "united arab emirates": 696,
    "iran": 630,
    "china": 710,
    "taiwan": 713,
}

VOTE_MAP = {"Y": 1.0, "YES": 1.0, "N": -1.0, "NO": -1.0, "A": 0.0, "ABSTAIN": 0.0, "X": np.nan, "ABSENT": np.nan}
VOTE_DATASETS = {"un_votes_clean", "2025_7_23_ga_voting"}
ACTIVE_DATASETS = {
    "un_votes_clean",
    "2025_7_23_ga_voting",
    "ucdp-prio-acd",
    "ucdp-dyadic",
    "ucdp-nonstate",
    "ucdp-onesided",
    "ucdp-brd",
    "ucdp-candidate",
    "GED",
    "par",
    "CACE_1989-2017",
    "ucdp_issues_dataset_dyadyear",
    "ucdp-peace-agreements",
}


@dataclass
class LoadedData:
    master_df: pd.DataFrame
    dataset_frames: dict[str, pd.DataFrame]
    dataset_summaries: list[dict[str, Any]]
    votes_df: pd.DataFrame
    issues_summary: list[dict[str, Any]]


MASTER_COLUMNS = [
    'year', 'country_a', 'country_b', 'country_a_code', 'country_b_code', 'dataset', 'issue',
    'intensity', 'deaths', 'relationship_type', 'resolution', 'topic', 'conflict_name',
    'dyad_id', 'conflict_id', 'raw_row_json'
]

VOTE_COLUMNS = ['dataset', 'country_code', 'country_name', 'year', 'resolution', 'topic', 'vote', 'vote_numeric', 'title']


def _stable_synthetic_code(name: str) -> int:
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return 10000 + int(digest, 16) % 900000


def _clean_name(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return " ".join(str(value).replace("_", " ").split()).strip()


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return float(value)
    except Exception:
        return None


def _normalize_year(value: Any) -> int | None:
    if isinstance(value, pd.Timestamp):
        return int(value.year)
    year = _safe_int(value)
    if year is not None and 1800 <= year <= 2100:
        return year
    if isinstance(value, str):
        parsed = pd.to_datetime(value, errors="coerce")
        if not pd.isna(parsed):
            year = int(parsed.year)
            if 1800 <= year <= 2100:
                return year
    return None


def _country_from_any(dataset_name: str, code_value: Any = None, label_value: Any = None) -> tuple[int | None, str]:
    code = _safe_int(code_value)
    label = _clean_name(label_value)

    # Handle comma-separated GW codes (e.g. "2, 220, 365" = multi-country coalition).
    # Use the first valid real GW code (2-920) from the list rather than treating the
    # whole string as a non-state actor name.
    if code is None and isinstance(code_value, (str, int, float)):
        raw_str = str(code_value)
        if ',' in raw_str:
            for part in raw_str.split(','):
                candidate = _safe_int(part.strip())
                if candidate is not None and 2 <= candidate <= 920:
                    code = candidate
                    break

    if code is not None:
        decoded = decode(dataset_name, "country_codes", code)
        if decoded == str(code):
            decoded = decode(dataset_name, "gwno", code)
        # For real GW codes (< 10000), prefer codebook-decoded name over raw UCDP actor text
        # (which often says "Government of X" instead of just "X")
        has_proper_name = decoded and decoded != str(code)
        if code < 10000 and has_proper_name:
            return code, decoded
        return code, label or decoded or str(code)

    raw_text = _clean_name(code_value) or label
    upper = raw_text.upper()
    if len(upper) == 3 and upper in ISO3_TO_GW:
        gw_code = ISO3_TO_GW[upper]
        pretty = decode("global", "country_codes", gw_code)
        return gw_code, pretty

    normalized = raw_text.lower()
    if normalized in COUNTRY_NAME_ALIASES:
        gw_code = COUNTRY_NAME_ALIASES[normalized]
        pretty = decode("global", "country_codes", gw_code)
        return gw_code, pretty

    if raw_text:
        return _stable_synthetic_code(raw_text.lower()), raw_text.title() if raw_text.isupper() else raw_text
    return None, ""


def _looks_like_country_column(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ["country", "gwno", "ccode", "iso3", "ms_code"])


def _read_csv_with_fallback(path_or_buffer, *, from_zip: bool = False) -> pd.DataFrame:
    encodings = ["utf-8", "utf-8-sig", "latin1", "cp1252"]
    separators = [None, ";"]
    last_error = None
    for encoding in encodings:
        for sep in separators:
            try:
                kwargs = {"encoding": encoding, "low_memory": False}
                if sep:
                    kwargs["sep"] = sep
                df = pd.read_csv(path_or_buffer, **kwargs)
                if len(df.columns) == 1 and ";" in str(df.columns[0]) and sep is None:
                    continue
                return df
            except Exception as exc:
                last_error = exc
                if from_zip and hasattr(path_or_buffer, "seek"):
                    path_or_buffer.seek(0)
    raise last_error


EXCEL_EPOCH = pd.Timestamp('1899-12-30')
XLSX_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _excel_serial_to_year(value: Any) -> int | None:
    serial = _safe_float(value)
    if serial is None:
        return None
    try:
        date_value = EXCEL_EPOCH + pd.to_timedelta(float(serial), unit='D')
        year = int(date_value.year)
        if 1800 <= year <= 2100:
            return year
    except Exception:
        return None
    return None


def _column_letters(cell_ref: str) -> str:
    return ''.join(char for char in str(cell_ref) if char.isalpha())


def _stream_vote_xlsx(path: str, dataset_name: str) -> pd.DataFrame:
    columns = ['ms_code', 'ms_name', 'vote', 'date', 'resolution', 'subjects', 'agenda_title', 'title']
    payload = {column: [] for column in columns}
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        try:
            with archive.open('xl/sharedStrings.xml') as handle:
                for _event, element in ET.iterparse(handle, events=('end',)):
                    if element.tag == XLSX_NS + 'si':
                        shared_strings.append(''.join(node.text or '' for node in element.iter(XLSX_NS + 't')))
                        element.clear()
        except KeyError:
            shared_strings = []

        with archive.open('xl/worksheets/sheet1.xml') as handle:
            header_by_ref: dict[str, str] | None = None
            wanted_refs: dict[str, str] = {}
            for _event, element in ET.iterparse(handle, events=('end',)):
                if element.tag != XLSX_NS + 'row':
                    continue
                row_values: dict[str, str] = {}
                for cell in element.findall(XLSX_NS + 'c'):
                    ref = _column_letters(cell.attrib.get('r', ''))
                    if not ref:
                        continue
                    raw_value = ''
                    value_node = cell.find(XLSX_NS + 'v')
                    if value_node is not None and value_node.text is not None:
                        raw_value = value_node.text
                    if cell.attrib.get('t') == 's' and raw_value:
                        try:
                            raw_value = shared_strings[int(raw_value)]
                        except Exception:
                            pass
                    row_values[ref] = raw_value

                if header_by_ref is None:
                    header_by_ref = row_values
                    # The UN Digital Library export names the vote column "ms_vote"
                    # (the CSV path below already handles that); without this alias
                    # the vote list stays empty, the frame cannot be built, and the
                    # whole voting file is silently skipped. (Team 128 integration fix)
                    header_alias = {'ms_vote': 'vote'}
                    wanted_refs = {ref: header_alias.get(name, name) for ref, name in header_by_ref.items() if header_alias.get(name, name) in payload}
                elif wanted_refs:
                    for ref, name in wanted_refs.items():
                        payload[name].append(row_values.get(ref, ''))
                element.clear()

    frame = pd.DataFrame(payload)
    if frame.empty:
        return pd.DataFrame(columns=VOTE_COLUMNS)

    frame['year'] = frame['date'].map(_excel_serial_to_year)
    frame = frame[frame['year'].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=VOTE_COLUMNS)

    unique_codes = {code: _country_from_any(dataset_name, code, '') for code in frame['ms_code'].dropna().astype(str).unique()}
    frame['country_code'] = frame['ms_code'].astype(str).map(lambda code: unique_codes.get(code, (None, ''))[0])
    frame['country_name'] = frame['ms_code'].astype(str).map(lambda code: unique_codes.get(code, (None, ''))[1])
    frame['vote'] = frame['vote'].astype(str).str.upper().str.strip()
    frame['vote_numeric'] = frame['vote'].map(VOTE_MAP)
    frame['topic'] = frame['subjects'].replace('', pd.NA).fillna(frame['agenda_title'].replace('', pd.NA)).fillna(frame['title']).astype(str)
    frame['resolution'] = frame['resolution'].astype(str)
    frame['title'] = frame['title'].astype(str)
    frame['dataset'] = dataset_name
    frame = frame[['dataset', 'country_code', 'country_name', 'year', 'resolution', 'topic', 'vote', 'vote_numeric', 'title']]
    frame = frame.dropna(subset=['country_code'])
    frame = frame[frame['resolution'].astype(str).str.strip().ne('')]
    frame = frame[(frame['year'] >= 1989) & (frame['year'] <= 2025)]
    frame = frame.drop_duplicates(subset=['country_code', 'year', 'resolution'], keep='last')
    return frame.reset_index(drop=True)


def _read_dataset_file(path: str, dataset_name: str) -> pd.DataFrame:
    lower = path.lower()
    if lower.endswith(".csv"):
        return _read_csv_with_fallback(path)
    if lower.endswith(".xlsx"):
        if dataset_name in VOTE_DATASETS:
            return _stream_vote_xlsx(path, dataset_name)
        return pd.read_excel(path)
    if lower.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith((".csv", ".xlsx"))]
            if not members:
                return pd.DataFrame()
            member = members[0]
            with archive.open(member) as handle:
                if member.lower().endswith(".csv"):
                    return _read_csv_with_fallback(handle, from_zip=True)
                return pd.read_excel(handle)
    return pd.DataFrame()


def _rank_path(path: str) -> tuple[int, int]:
    lower = path.lower()
    if lower.endswith(".csv"):
        return (0, len(path))
    if lower.endswith(".xlsx"):
        return (1, len(path))
    return (2, len(path))


def discover_datasets() -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for file_path in __import__("glob").glob(os.path.join(ROOT_DIR, "**", "*"), recursive=True):
        file_name = os.path.basename(file_path)
        if any(part in file_path for part in ["node_modules", "frontend", "backend", "outputs"]):
            continue
        if not file_name.lower().endswith((".csv", ".zip", ".xlsx")):
            continue
        dataset_name = canonical_dataset_name(file_name)
        if dataset_name not in ACTIVE_DATASETS:
            continue
        grouped.setdefault(dataset_name, []).append(file_path)
    return {name: sorted(paths, key=_rank_path)[0] for name, paths in grouped.items()}


def _decode_numeric_columns(dataset_name: str, df: pd.DataFrame) -> pd.DataFrame:
    for column in list(df.columns):
        series = df[column]
        if not (pd.api.types.is_numeric_dtype(series) or _looks_like_country_column(column)):
            continue
        if len(df) > 200000 and column not in {"vote_enc"} and not _looks_like_country_column(column):
            continue
        if len(df) > 200000 and series.nunique(dropna=True) > 20 and not _looks_like_country_column(column):
            continue
        try:
            decoded = series.map(lambda value: decode(dataset_name, column, value) if not pd.isna(value) else "")
            if decoded.astype(str).ne(series.astype(str)).sum() > 0:
                df[f"{column}_label"] = decoded
        except Exception:
            continue
    return df


def _row_to_json(row: pd.Series) -> str:
    payload = {str(key): _json_safe(value) for key, value in row.to_dict().items()}
    return json.dumps(payload, ensure_ascii=False)


def _append_record(records: list[dict[str, Any]], dataset_name: str, row: pd.Series, **kwargs: Any) -> None:
    year = _normalize_year(kwargs.get("year"))
    if year is None or year < 1989 or year > 2025:
        return
    records.append({
        "year": year,
        "country_a": kwargs.get("country_a", ""),
        "country_b": kwargs.get("country_b", ""),
        "country_a_code": kwargs.get("country_a_code"),
        "country_b_code": kwargs.get("country_b_code"),
        "dataset": dataset_name,
        "issue": kwargs.get("issue", ""),
        "intensity": kwargs.get("intensity"),
        "deaths": kwargs.get("deaths"),
        "relationship_type": kwargs.get("relationship_type", "neutral"),
        "resolution": kwargs.get("resolution", ""),
        "topic": kwargs.get("topic", ""),
        "conflict_name": kwargs.get("conflict_name", ""),
        "dyad_id": kwargs.get("dyad_id"),
        "conflict_id": kwargs.get("conflict_id"),
        "raw_row_json": _row_to_json(row),
    })


def _issue_text_from_row(row: pd.Series, dataset_name: str) -> str:
    for column in ["incompatibility_label", "incompatibility", "issue", "topic", "subjects", "agenda_title"]:
        value = row.get(column)
        if value is not None and not pd.isna(value):
            if column == "incompatibility":
                return decode(dataset_name, column, value)
            return _clean_name(value)
    return ""


def _pair_from_row(dataset_name: str, row: pd.Series) -> tuple[tuple[int | None, str], tuple[int | None, str]]:
    left = _country_from_any(dataset_name, row.get("gwno_a"), row.get("side_a") or row.get("country"))
    right = _country_from_any(dataset_name, row.get("gwno_b"), row.get("side_b"))
    if not right[0]:
        right = _country_from_any(dataset_name, row.get("gwnob"), row.get("side_b"))
    if not left[0]:
        left = _country_from_any(dataset_name, row.get("gwnoa"), row.get("side_a"))
    return left, right


def _process_vote_dataset(dataset_name: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    if {'dataset', 'country_code', 'country_name', 'year', 'resolution', 'topic', 'vote', 'vote_numeric', 'title'}.issubset(df.columns):
        return df[['dataset', 'country_code', 'country_name', 'year', 'resolution', 'topic', 'vote', 'vote_numeric', 'title']].to_dict(orient='records')

    vote_column = "vote" if dataset_name == "un_votes_clean" else "ms_vote"
    if vote_column not in df.columns:
        return []
    working = df[[column for column in ["ms_code", "ms_name", vote_column, "date", "resolution", "subjects", "agenda_title", "title"] if column in df.columns]].copy()
    working["year"] = pd.to_datetime(working.get("date"), errors="coerce").dt.year
    working = working[working["year"].between(1989, 2025, inclusive="both")]
    if working.empty:
        return []
    unique_codes = {code: _country_from_any(dataset_name, code, "") for code in working["ms_code"].dropna().astype(str).unique()}
    working["country_code"] = working["ms_code"].astype(str).map(lambda code: unique_codes.get(code, (None, ""))[0])
    working["country_name"] = working["ms_code"].astype(str).map(lambda code: unique_codes.get(code, (None, ""))[1])
    working["vote"] = working[vote_column].astype(str).str.upper().str.strip()
    working["vote_numeric"] = working["vote"].map(VOTE_MAP)
    working["topic"] = working.get("subjects").fillna(working.get("agenda_title")).fillna(working.get("title")).astype(str)
    working["resolution"] = working.get("resolution", "").astype(str)
    working["title"] = working.get("title", "").astype(str)
    working["dataset"] = dataset_name
    working = working[["dataset", "country_code", "country_name", "year", "resolution", "topic", "vote", "vote_numeric", "title"]]
    working = working.dropna(subset=["country_code", "resolution"]).drop_duplicates(subset=["country_code", "year", "resolution"], keep="last")
    return working.to_dict(orient="records")


def _process_dataset(dataset_name: str, df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    votes: list[dict[str, Any]] = []

    if dataset_name in VOTE_DATASETS:
        return records, _process_vote_dataset(dataset_name, df)

    for _, row in df.iterrows():
        issue = _issue_text_from_row(row, dataset_name)
        if dataset_name in {"ucdp-prio-acd", "ucdp-dyadic", "ucdp-brd", "GED", "CACE_1989-2017"}:
            left, right = _pair_from_row(dataset_name, row)
            _append_record(records, dataset_name, row, year=row.get("year") or row.get("date_start"), country_a_code=left[0], country_a=left[1], country_b_code=right[0], country_b=right[1], issue=issue, intensity=_safe_float(row.get("intensity_level") or row.get("best") or row.get("bd_best")), deaths=_safe_float(row.get("bd_best") or row.get("best")), relationship_type="conflict", conflict_name=_clean_name(row.get("conflict_name") or row.get("location")), dyad_id=_safe_int(row.get("dyad_id") or row.get("dyad_new_id")), conflict_id=_safe_int(row.get("conflict_id") or row.get("conflict_new_id")))
        elif dataset_name == "ucdp-candidate":
            left = _country_from_any(dataset_name, row.get("country_id") or row.get("gwnoa"), row.get("country"))
            right = _country_from_any(dataset_name, row.get("gwnob"), row.get("side_b"))
            _append_record(records, dataset_name, row, year=row.get("year") or row.get("date_start"), country_a_code=left[0], country_a=left[1], country_b_code=right[0], country_b=right[1], issue=_clean_name(row.get("conflict_name")) or issue, intensity=_safe_float(row.get("best")), deaths=_safe_float(row.get("best")), relationship_type="conflict", conflict_name=_clean_name(row.get("conflict_name")), dyad_id=_safe_int(row.get("dyad_new_id")), conflict_id=_safe_int(row.get("conflict_new_id")))
        elif dataset_name == "ucdp-nonstate":
            location = _country_from_any(dataset_name, row.get("gwno_location"), row.get("location"))
            partner = _country_from_any(dataset_name, row.get("gwno_a_2nd"), row.get("side_a_name"))
            if not partner[0]:
                partner = _country_from_any(dataset_name, row.get("gwno_b_2nd"), row.get("side_b_name"))
            _append_record(records, dataset_name, row, year=row.get("year"), country_a_code=location[0], country_a=location[1], country_b_code=partner[0], country_b=partner[1], issue="non-state conflict", intensity=_safe_float(row.get("best_fatality_estimate")), deaths=_safe_float(row.get("best_fatality_estimate")), relationship_type="conflict", conflict_name=_clean_name(row.get("org")), dyad_id=_safe_int(row.get("dyad_id")), conflict_id=_safe_int(row.get("conflict_id")))
        elif dataset_name == "ucdp-onesided":
            location = _country_from_any(dataset_name, row.get("gwno_location") or row.get("gwnoa"), row.get("location"))
            _append_record(records, dataset_name, row, year=row.get("year"), country_a_code=location[0], country_a=location[1], country_b_code=None, country_b="", issue="one-sided violence", intensity=_safe_float(row.get("best_fatality_estimate")), deaths=_safe_float(row.get("best_fatality_estimate")), relationship_type="conflict", conflict_name=_clean_name(row.get("actor_name")), dyad_id=_safe_int(row.get("dyad_id")), conflict_id=_safe_int(row.get("conflict_id")))
        elif dataset_name == "par":
            country = _country_from_any(dataset_name, row.get("country_id"), row.get("country"))
            _append_record(records, dataset_name, row, year=row.get("year") or row.get("date_start"), country_a_code=country[0], country_a=country[1], country_b_code=None, country_b="", issue="peace agreement", intensity=1.0, deaths=_safe_float(row.get("best_est")), relationship_type="peace_partner", conflict_name=_clean_name(row.get("dyad_name")), dyad_id=_safe_int(row.get("dyad_dset_id")))
        elif dataset_name == "ucdp-peace-agreements":
            country = _country_from_any(dataset_name, row.get("gwno"), row.get("actor_name"))
            _append_record(records, dataset_name, row, year=row.get("year"), country_a_code=country[0], country_a=country[1], issue="peace agreement", intensity=1.0, deaths=0.0, relationship_type="peace_partner", conflict_name=_clean_name(row.get("conflict_name") or row.get("pa_name")), dyad_id=_safe_int(row.get("dyad_id")), conflict_id=_safe_int(row.get("conflict_id")))
        elif dataset_name == "ucdp_issues_dataset_dyadyear":
            continue
        else:
            country = _country_from_any(dataset_name, row.get("country_id") or row.get("ccode") or row.get("gwno"), row.get("country") or row.get("ms_name"))
            _append_record(records, dataset_name, row, year=row.get("year") or row.get("date_start") or row.get("date"), country_a_code=country[0], country_a=country[1], issue=issue or _clean_name(row.get("conflict_name") or row.get("resolution")), intensity=_safe_float(row.get("best") or row.get("votes")), deaths=_safe_float(row.get("best")), relationship_type="neutral", conflict_name=_clean_name(row.get("conflict_name")), dyad_id=_safe_int(row.get("dyad_id")), conflict_id=_safe_int(row.get("conflict_id")))
    return records, votes


def _extract_issue_flags(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    # Prefer human-readable named category columns (e.g. "ethnicity_1" = "Ethnicity: Kurdish")
    # over raw numeric flag columns. These give meaningful labels for public-facing display.
    named_cat_cols = [c for c in df.columns if any(c.startswith(p) for p in ("ethnicity_", "geography_", "ideology_", "religion_"))]
    numeric_flag_cols = [c for c in df.columns if str(c).isdigit()]
    # Codebook mapping for most common numeric UCDP issue codes → readable label
    ISSUE_CODE_LABELS = {
        "7101": "Ideology", "7201": "Communist ideology", "7501": "Islamist ideology",
        "7301": "Nationalism", "7302": "Ethnic nationalism", "7303": "Pan-nationalism",
        "7304": "Religious nationalism",
        "2103": "Political system", "2101": "Political exclusion", "2201": "Elections",
        "2202": "Governance reform", "2203": "Political rights", "2204": "Justice/accountability",
        "9102": "Territorial control", "9101": "Secession/independence", "9103": "Border demarcation",
        "9201": "Land use", "9202": "Land rights", "9301": "Water rights", "9302": "Maritime boundary",
        "6209": "Foreign military presence", "6201": "Decolonization", "6103": "International boundary",
        "6201": "Decolonization", "6202": "Post-colonial borders",
        "4101": "Natural resources", "4202": "Economic exclusion", "4201": "Economic development",
        "4301": "Drug trafficking", "4302": "Illegal trade", "4306": "Criminal control",
        "5103": "Ethnic discrimination", "5102": "Religious discrimination", "5203": "Ethnic rights",
        "8201": "Economic inequality", "8101": "Poverty", "2401": "Power sharing",
        "3102": "Autonomy", "3202": "Self-governance", "1101": "Independence",
        "10201": "State capacity", "9102": "Administrative control",
    }
    flagged = []
    for _, row in df.iterrows():
        year = _normalize_year(row.get("year"))
        if year is None or year < 1989 or year > 2025:
            continue
        active = []
        # First: extract human-readable labels from named columns
        for col in named_cat_cols:
            val = row.get(col)
            if val and not pd.isna(val):
                label = str(val).strip()
                if label and label not in active:
                    active.append(label)
        # Fallback: decode numeric flag columns using our label map
        if not active:
            for col in numeric_flag_cols:
                if _safe_int(row.get(col)) == 1:
                    label = ISSUE_CODE_LABELS.get(col, col)
                    if label not in active:
                        active.append(label)
        if active:
            flagged.append({"dyad_id": _safe_int(row.get("dyad_id")), "conflict_id": _safe_int(row.get("conflict_id")), "year": year, "issues": active})
    return pd.DataFrame(flagged)


def _merge_issue_flags(master_df: pd.DataFrame, issue_flags: pd.DataFrame) -> pd.DataFrame:
    if master_df.empty or issue_flags.empty:
        return master_df
    issue_lookup: dict[tuple[int | None, int | None, int], list[str]] = {}
    for _, row in issue_flags.iterrows():
        key = (_safe_int(row.get("dyad_id")), _safe_int(row.get("conflict_id")), _safe_int(row.get("year")) or 0)
        issue_lookup[key] = row.get("issues", [])

    enriched = master_df.copy()
    for index, row in enriched.iterrows():
        key = (_safe_int(row.get("dyad_id")), _safe_int(row.get("conflict_id")), _safe_int(row.get("year")) or 0)
        issues = issue_lookup.get(key)
        if issues:
            combined = [item for item in [row.get("issue")] + issues if item]
            deduped = []
            seen = set()
            for item in combined:
                if item not in seen:
                    deduped.append(item)
                    seen.add(item)
            enriched.at[index, "issue"] = ", ".join(deduped)
    return enriched


def _issue_summary_from_master(master_df: pd.DataFrame) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for value in master_df.get("issue", pd.Series(dtype=str)).fillna(""):
        for issue in [item.strip() for item in str(value).split(",") if item.strip()]:
            counts[issue] += 1
    return [{"issue": issue, "count": count} for issue, count in counts.most_common()]


def load_all_datasets(progress_callback=None) -> LoadedData:
    ensure_directories()
    dataset_frames: dict[str, pd.DataFrame] = {}
    dataset_summaries: list[dict[str, Any]] = []
    master_records: list[dict[str, Any]] = []
    vote_records: list[dict[str, Any]] = []

    discovered_items = list(discover_datasets().items())
    total_datasets = len(discovered_items)

    for index, (dataset_name, path) in enumerate(discovered_items, start=1):
        if progress_callback:
            progress_callback(dataset_name, index, total_datasets)
        try:
            df = _read_dataset_file(path, dataset_name)
        except Exception:
            continue
        if df.empty:
            continue
        if dataset_name not in ACTIVE_DATASETS:
            df = _decode_numeric_columns(dataset_name, df)
        dataset_frames[dataset_name] = df
        dataset_summaries.append({"dataset": dataset_name, "rows": int(len(df)), "columns": list(map(str, df.columns[:25])), "source": os.path.basename(path)})
        records, votes = _process_dataset(dataset_name, df)
        master_records.extend(records)
        vote_records.extend(votes)

    master_df = pd.DataFrame(master_records, columns=MASTER_COLUMNS)
    votes_df = pd.DataFrame(vote_records, columns=VOTE_COLUMNS)
    issue_flags = _extract_issue_flags(dataset_frames.get("ucdp_issues_dataset_dyadyear", pd.DataFrame()))
    master_df = _merge_issue_flags(master_df, issue_flags)

    if not master_df.empty:
        master_df["country_a_code"] = master_df["country_a_code"].apply(_safe_int)
        master_df["country_b_code"] = master_df["country_b_code"].apply(_safe_int)
        master_df["year"] = master_df["year"].apply(_normalize_year)
        master_df = master_df[master_df["year"].notna()].copy()
        master_df["year"] = master_df["year"].astype(int)
        master_df = master_df[(master_df["year"] >= 1989) & (master_df["year"] <= 2025)]

    if not votes_df.empty:
        votes_df["year"] = votes_df["year"].astype(int)
        votes_df = votes_df[(votes_df["year"] >= 1989) & (votes_df["year"] <= 2025)]
        votes_df = votes_df.drop_duplicates(subset=["country_code", "year", "resolution"], keep="last")

    return LoadedData(master_df=master_df, dataset_frames=dataset_frames, dataset_summaries=sorted(dataset_summaries, key=lambda item: item["dataset"]), votes_df=votes_df, issues_summary=_issue_summary_from_master(master_df))
