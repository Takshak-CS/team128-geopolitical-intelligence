"""Read access to the product-level (HS6) trade store.

The sector cache answers "energy" or "base metals". An analyst usually wants
something narrower: raw cane sugar, crude oil, integrated circuits, rare-earth
compounds. The product store keeps BACI's HS6 rows so any analysis can be
narrowed to an HS chapter (2 digits), heading (4) or subheading (6).

Layout, written by ``scripts/build_cache.py``:

    cache/products/products_<year>.parquet   k, i, j, v   (HS6 code, exporter, importer, value)
    cache/products/product_year.parquet      world trade per product and year
    cache/products/catalog.parquet           HS6 codes, descriptions, grouping, latest world value
    cache/products/meta.json                 manifest

Rows are sorted by product code in small row groups, so reading one product
decodes only the row groups that can hold it. Flows under $10,000 are dropped:
that halves the store while keeping 99.95% of trade value. Values are thousand
USD, as everywhere else in BACI.

The store is optional. Without it every query still works at sector level;
asking for a product returns an error that says what is missing.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from core.sector_mapper import (
    HS_CHAPTERS,
    SECTOR_DEFINITIONS,
    normalize_product,
    normalize_sector,
    product_code_range,
    sector_for_product,
    sector_label,
)

PRODUCT_STORE_VERSION = 1
# BACI values are thousand USD, so 10 is $10,000.
MIN_FLOW_THOUSAND_USD = 10
MAX_CACHED_PRODUCT_FRAMES = 64

_LEVELS = {2: "chapter", 4: "heading", 6: "subheading"}
_MEMORY_LOCK = threading.Lock()
_MEMORY: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()


def products_dir(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / "products"


def products_path(cache_dir: str | Path, year: int) -> Path:
    return products_dir(cache_dir) / f"products_{int(year)}.parquet"


def catalog_path(cache_dir: str | Path) -> Path:
    return products_dir(cache_dir) / "catalog.parquet"


def product_year_path(cache_dir: str | Path) -> Path:
    return products_dir(cache_dir) / "product_year.parquet"


def product_meta_path(cache_dir: str | Path) -> Path:
    return products_dir(cache_dir) / "meta.json"


def product_years(cache_dir: str | Path) -> list[int]:
    """Years present in the product store."""
    directory = products_dir(cache_dir)
    if not directory.is_dir():
        return []
    years = []
    for path in directory.glob("products_*.parquet"):
        try:
            years.append(int(path.stem.rsplit("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(years)


def product_store_available(cache_dir: str | Path) -> bool:
    """True when products can be searched and analysed."""
    return catalog_path(cache_dir).exists() and bool(product_years(cache_dir))


def product_meta(cache_dir: str | Path) -> dict:
    path = product_meta_path(cache_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def require_store(cache_dir: str | Path) -> None:
    if not product_store_available(cache_dir):
        raise ValueError(
            "Product-level data is not installed on this deployment, so analyses can be "
            "narrowed to a sector but not to a single product. Build it with "
            "scripts/build_cache.py from the raw BACI files."
        )


@lru_cache(maxsize=4)
def _catalog(key: str, stamp: float) -> pd.DataFrame:
    return pd.read_parquet(catalog_path(key))


def load_catalog(cache_dir: str | Path) -> pd.DataFrame:
    """The HS6 catalog, memoised until the file changes."""
    path = catalog_path(cache_dir)
    if not path.exists():
        require_store(cache_dir)
    return _catalog(str(Path(cache_dir).resolve()), path.stat().st_mtime)


@lru_cache(maxsize=4)
def _country_names(key: str, stamp: float) -> dict[int, str]:
    codes = pd.read_parquet(Path(key) / "countries.parquet")
    return dict(zip(codes["country_code"].astype(int), codes["country_name"].astype(str)))


def country_names(cache_dir: str | Path) -> dict[int, str]:
    """BACI numeric code -> country name."""
    path = Path(cache_dir) / "countries.parquet"
    return _country_names(str(Path(cache_dir).resolve()), path.stat().st_mtime)


def country_code(cache_dir: str | Path, name: str) -> int:
    for code, country in country_names(cache_dir).items():
        if country == name:
            return code
    raise ValueError(f"Country '{name}' is not in the BACI country table.")


def _short(text: str, width: int = 72) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else f"{text[: width - 3].rstrip()}..."


def describe_product(cache_dir: str | Path, code: object) -> dict:
    """What an HS code covers: its level, label, sector and size."""
    normalized = normalize_product(code)
    if normalized is None:
        raise ValueError("A product code is required.")
    catalog = load_catalog(cache_dir)
    low, high = product_code_range(normalized)
    rows = catalog[(catalog["k"] >= low) & (catalog["k"] <= high)]
    if rows.empty:
        raise ValueError(f"HS code {normalized} is not in the HS92 product catalog.")

    level = _LEVELS[len(normalized)]
    chapter = int(normalized[:2])
    if level == "chapter":
        label = HS_CHAPTERS.get(chapter, f"Chapter {normalized}")
    elif level == "heading":
        label = str(rows.iloc[0]["hs4_label"])
    else:
        label = str(rows.iloc[0]["description"])

    sector = sector_for_product(normalized)
    value_year = int(rows["value_year"].max()) if "value_year" in rows else None
    return {
        "code": normalized,
        "level": level,
        "label": label,
        "short_label": _short(label, 60),
        "sector": sector,
        "sector_label": sector_label(sector),
        "chapter": f"{chapter:02d}",
        "chapter_name": HS_CHAPTERS.get(chapter, ""),
        "subheadings": int(len(rows)),
        "world_value": float(rows["world_value"].sum()),
        "value_year": value_year or None,
    }


def product_scope_label(info: dict) -> str:
    """How a claim names a product: "HS 170111 (Sugars: cane sugar, raw, ...)"."""
    return f"HS {info['code']} ({info['short_label']})"


def search_products(
    cache_dir: str | Path,
    query: str = "",
    sector: Optional[str] = None,
    limit: int = 25,
) -> list[dict]:
    """Find products by words in their description or by HS code prefix.

    Returns headings (HS4) and subheadings (HS6), largest world trade first, so
    the first suggestions are the products that matter most. With no query it
    lists the biggest products in the sector.
    """
    catalog = load_catalog(cache_dir)
    selected_sector = normalize_sector(sector)
    if selected_sector != "all":
        catalog = catalog[catalog["sector"] == selected_sector]

    # Products with no trade in the latest year cannot be analysed for it, and
    # BACI's HS92 list carries a few codes that are never used.
    catalog = catalog[catalog["world_value"] > 0]

    text = " ".join(str(query or "").lower().replace(".", " ").split())
    digits = text.replace(" ", "")
    description = catalog["description"].str.lower()
    heading = catalog["hs4_label"].str.lower()
    if digits.isdigit():
        relevance = catalog["code"].str.startswith(digits).astype(int) * 3
        heading_phrase = None
    elif text:
        tokens = text.split()
        in_description = pd.Series(True, index=catalog.index)
        in_heading = pd.Series(True, index=catalog.index)
        anywhere = pd.Series(True, index=catalog.index)
        context = description + " | " + heading + " | " + catalog["chapter_name"].str.lower()
        for token in tokens:
            in_description &= description.str.contains(token, regex=False)
            in_heading &= (description + " | " + heading).str.contains(token, regex=False)
            anywhere &= context.str.contains(token, regex=False)
        # A phrase match ("sugar cane") beats the same words scattered across a
        # description, which beats words that only occur in the chapter name.
        relevance = (
            description.str.startswith(text).astype(int)
            + description.str.contains(text, regex=False).astype(int)
            + in_description.astype(int)
            + in_heading.astype(int)
            + anywhere.astype(int)
        )
        heading_phrase = text
    else:
        relevance = pd.Series(1, index=catalog.index)
        heading_phrase = None

    matched = catalog[relevance > 0].assign(relevance=relevance[relevance > 0])
    if matched.empty:
        return []

    options: list[dict] = []
    sizes = catalog.groupby("hs4")["k"].size()
    for hs4, group in matched.groupby("hs4"):
        # A heading with a single subheading is the same product twice.
        if int(sizes.get(hs4, 0)) <= 1:
            continue
        members = catalog[catalog["hs4"] == hs4]
        first = members.iloc[0]
        # A heading is broader than its best-matching product, so it ranks just
        # below it, unless the heading itself is what was asked for.
        relevance = int(group["relevance"].max()) - 1
        if digits.isdigit() and hs4 == digits[:4] and len(digits) <= 4:
            relevance += 2
        elif heading_phrase and heading_phrase in str(first["hs4_label"]).lower():
            relevance += 1
        options.append(
            {
                "code": hs4,
                "level": "heading",
                "label": str(first["hs4_label"]),
                "detail": f"All {int(sizes.get(hs4, 0))} products in heading {hs4} · {first['chapter_name']}",
                "sector": str(first["sector"]),
                "world_value": float(members["world_value"].sum()),
                "relevance": relevance,
            }
        )
    for row in matched.itertuples(index=False):
        options.append(
            {
                "code": str(row.code),
                "level": "subheading",
                "label": str(row.description),
                "detail": f"{row.hs4_label} · {row.chapter_name}",
                "sector": str(row.sector),
                "world_value": float(row.world_value),
                "relevance": int(row.relevance),
            }
        )

    options.sort(key=lambda item: (item["relevance"], item["world_value"]), reverse=True)
    for item in options:
        item.pop("relevance", None)
    return options[: max(1, int(limit))]


def sector_products(cache_dir: str | Path, sector: str) -> dict:
    """The chapters in a sector with their world trade, for browsing."""
    selected_sector = normalize_sector(sector)
    catalog = load_catalog(cache_dir)
    if selected_sector != "all":
        catalog = catalog[catalog["sector"] == selected_sector]
    chapters = (
        catalog.groupby("chapter")
        .agg(world_value=("world_value", "sum"), subheadings=("k", "size"))
        .reset_index()
        .sort_values("world_value", ascending=False)
    )
    return {
        "sector": selected_sector,
        "chapters": [
            {
                "code": f"{int(row.chapter):02d}",
                "level": "chapter",
                "label": HS_CHAPTERS.get(int(row.chapter), ""),
                "subheadings": int(row.subheadings),
                "world_value": float(row.world_value),
            }
            for row in chapters.itertuples(index=False)
        ],
    }


def _read_year(
    cache_dir: str | Path,
    year: int,
    code: Optional[str] = None,
    countries: Optional[list[int]] = None,
    chapters: Optional[tuple[int, ...]] = None,
) -> pd.DataFrame:
    """Raw product rows for a year, filtered at read time."""
    import pyarrow.parquet as pq

    path = products_path(cache_dir, year)
    if not path.exists():
        available = product_years(cache_dir)
        span = f"{min(available)}-{max(available)}" if available else "none"
        raise ValueError(f"Product-level data for {int(year)} is not available. Coverage: {span}.")

    filters: list = []
    if code is not None:
        low, high = product_code_range(code)
        filters += [("k", ">=", low), ("k", "<=", high)]
    if countries is not None:
        filters += [("i", "in", countries), ("j", "in", countries)]
    table = pq.read_table(path, columns=["k", "i", "j", "v"], filters=filters or None)
    frame = table.to_pandas()
    if chapters is not None and not frame.empty:
        frame = frame[(frame["k"] // 10000).isin(chapters)]
    return frame


def load_product_year(cache_dir: str | Path, year: int, code: str) -> pd.DataFrame:
    """Country-to-country flows of one product in one year, in the edge-frame shape."""
    require_store(cache_dir)
    normalized = normalize_product(code)
    info = describe_product(cache_dir, normalized)
    key = (str(Path(cache_dir).resolve()), int(year), normalized)

    with _MEMORY_LOCK:
        hit = _MEMORY.get(key)
        if hit is not None:
            _MEMORY.move_to_end(key)
            return _copy(hit)

    rows = _read_year(cache_dir, year, code=normalized)
    if rows.empty:
        raise ValueError(f"No trade in {product_scope_label(info)} is recorded for {int(year)}.")

    names = country_names(cache_dir)
    grouped = rows.groupby(["i", "j"], as_index=False)["v"].sum()
    frame = pd.DataFrame(
        {
            "exporter": grouped["i"].astype(int).map(names),
            "importer": grouped["j"].astype(int).map(names),
            "year": int(year),
            "trade_value": grouped["v"].astype(float),
            "sector": info["sector"],
        }
    ).dropna(subset=["exporter", "importer"])
    frame = frame.sort_values(["exporter", "importer"]).reset_index(drop=True)

    from core import baci_cache

    quality = dict(baci_cache.load_quality(cache_dir, year=int(year), sector="all"))
    quality["min_flow_usd"] = MIN_FLOW_THOUSAND_USD * 1000
    frame.attrs["data_quality"] = quality
    frame.attrs["sector"] = info["sector"]
    frame.attrs["product"] = info

    with _MEMORY_LOCK:
        _MEMORY[key] = frame
        _MEMORY.move_to_end(key)
        while len(_MEMORY) > MAX_CACHED_PRODUCT_FRAMES:
            _MEMORY.popitem(last=False)
    return _copy(frame)


def load_product_country_series(cache_dir: str | Path, code: str, country: str) -> pd.DataFrame:
    """Yearly imports and exports of one product for one country."""
    require_store(cache_dir)
    normalized = normalize_product(code)
    target = country_code(cache_dir, country)
    records = []
    for year in product_years(cache_dir):
        rows = _read_year(cache_dir, year, code=normalized)
        exports = float(rows.loc[rows["i"] == target, "v"].sum())
        imports = float(rows.loc[rows["j"] == target, "v"].sum())
        total = exports + imports
        records.append(
            {
                "year": int(year),
                "imports": imports,
                "exports": exports,
                "trade_total": total,
                "import_dependency_ratio": imports / total if total else 0.0,
                "export_dependency_ratio": exports / total if total else 0.0,
            }
        )
    series = pd.DataFrame(records)
    if series.empty or float(series["trade_total"].sum()) <= 0:
        info = describe_product(cache_dir, normalized)
        raise ValueError(f"{country} has no recorded trade in {product_scope_label(info)}.")
    return series


def load_product_pair_series(cache_dir: str | Path, code: Optional[str], first: str, second: str,
                             chapters: Optional[tuple[int, ...]] = None) -> pd.DataFrame:
    """Yearly flows in both directions between two countries, for a product or chapter set."""
    require_store(cache_dir)
    a, b = country_code(cache_dir, first), country_code(cache_dir, second)
    records = []
    for year in product_years(cache_dir):
        rows = _read_year(cache_dir, year, code=code, countries=[a, b], chapters=chapters)
        records.append(
            {
                "year": int(year),
                "a_to_b": float(rows.loc[(rows["i"] == a) & (rows["j"] == b), "v"].sum()),
                "b_to_a": float(rows.loc[(rows["i"] == b) & (rows["j"] == a), "v"].sum()),
            }
        )
    return pd.DataFrame(records)


def top_products_between(
    cache_dir: str | Path,
    year: int,
    first: str,
    second: str,
    code: Optional[str] = None,
    sector: Optional[str] = None,
    limit: int = 8,
) -> dict:
    """The largest products flowing each way between two countries in a year."""
    require_store(cache_dir)
    a, b = country_code(cache_dir, first), country_code(cache_dir, second)
    selected_sector = normalize_sector(sector)
    chapters = None
    if code is None and selected_sector != "all":
        chapters = tuple(SECTOR_DEFINITIONS[selected_sector]["chapters"])
    rows = _read_year(cache_dir, year, code=code, countries=[a, b], chapters=chapters)
    catalog = load_catalog(cache_dir).set_index("k")

    def direction(exporter: int, importer: int) -> list[dict]:
        flows = rows[(rows["i"] == exporter) & (rows["j"] == importer)]
        total = float(flows["v"].sum())
        top = flows.sort_values("v", ascending=False).head(limit)
        out = []
        for row in top.itertuples(index=False):
            entry = catalog.loc[int(row.k)] if int(row.k) in catalog.index else None
            out.append(
                {
                    "code": f"{int(row.k):06d}",
                    "description": str(entry["description"]) if entry is not None else "",
                    "heading": str(entry["hs4_label"]) if entry is not None else "",
                    "value": float(row.v),
                    "share": float(row.v) / total if total else 0.0,
                }
            )
        return out

    return {"a_to_b": direction(a, b), "b_to_a": direction(b, a), "year": int(year)}


def product_world_series(cache_dir: str | Path, code: str) -> list[dict]:
    """World trade in a product for every year in the store."""
    normalized = normalize_product(code)
    path = product_year_path(cache_dir)
    if not path.exists():
        return []
    low, high = product_code_range(normalized)
    frame = pd.read_parquet(path, filters=[("k", ">=", low), ("k", "<=", high)])
    totals = frame.groupby("year")["world_value"].sum().sort_index()
    return [{"year": int(year), "value": float(value)} for year, value in totals.items()]


def clear_memory() -> None:
    with _MEMORY_LOCK:
        _MEMORY.clear()


def _copy(frame: pd.DataFrame) -> pd.DataFrame:
    copied = frame.copy(deep=True)
    copied.attrs = dict(frame.attrs)
    return copied
