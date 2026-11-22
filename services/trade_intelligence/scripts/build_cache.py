"""Precompute a fast parquet cache from the raw BACI yearly CSV files.

The raw dataset is roughly 8 GB spread across thirty yearly CSVs of about ten
million product-level rows each. Re-parsing those per request is wasted work: a
cold forecast has to touch all thirty files and takes over five minutes.

This script makes one pass over each yearly file and writes:

    cache/edges/edges_<year>.parquet        exporter-importer flows for every sector
    cache/country_year.parquet              yearly totals per country and sector
    cache/quality.parquet                   data completeness per year and sector
    cache/centrality.parquet                PageRank and betweenness per year and sector
    cache/meta.json                         build manifest

and, unless ``--skip-products`` is given, the product-level store that lets an
analysis narrow to one HS chapter, heading or subheading:

    cache/products/products_<year>.parquet  HS6 flows of at least $10,000
    cache/products/product_year.parquet     world trade per product and year
    cache/products/catalog.parquet          every HS6 code with its description
    cache/products/meta.json                product store manifest

The sector tables are a few tens of megabytes and are committed. The product
store is a few hundred megabytes, so it is gitignored and shipped with the
deploy's data bundle instead; the module works without it, minus product
filtering.

Usage:
    python scripts/build_cache.py --dataset ../../../trade_intelligence_module/dataset
    python scripts/build_cache.py --years 2023 2024 --force --workers 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.baci_cache import (  # noqa: E402
    CACHE_VERSION,
    centrality_path,
    countries_path,
    country_year_path,
    edges_path,
    meta_path,
    quality_path,
)
from core.data_loader import (  # noqa: E402
    _find_baci_file,
    _load_country_codes_cached,
    available_years,
    is_baci_directory,
)
from core.product_store import (  # noqa: E402
    MIN_FLOW_THOUSAND_USD,
    PRODUCT_STORE_VERSION,
    catalog_path,
    product_meta_path,
    product_year_path,
    products_dir,
    products_path,
)
from core.sector_mapper import (  # noqa: E402
    CHAPTER_TO_SECTOR,
    HS_CHAPTERS,
    SPECIFIC_SECTORS,
    SUPPORTED_SECTORS,
    sector_for_chapter,
)

READ_CHUNKSIZE = 500_000
PRODUCT_ROW_GROUP = 50_000

# Chapter number -> index into SPECIFIC_SECTORS, so labelling a chunk is one
# array lookup instead of a string map over half a million rows.
_SECTOR_INDEX = np.full(100, SPECIFIC_SECTORS.index("manufactures"), dtype=np.int8)
for _chapter, _sector in CHAPTER_TO_SECTOR.items():
    _SECTOR_INDEX[_chapter] = SPECIFIC_SECTORS.index(_sector)


def label_sectors(chapters: pd.Series) -> pd.Series:
    """Map HS92 chapter numbers onto sector ids.

    The named sectors partition the HS chapters, so every product row gets
    exactly one label and the labels add up to the ``all`` totals.
    """
    indexes = _SECTOR_INDEX[np.clip(chapters.to_numpy(dtype=np.int64), 0, 99)]
    return pd.Series(np.asarray(SPECIFIC_SECTORS, dtype=object)[indexes], index=chapters.index)


def build_year(
    dataset_dir: Path,
    year: int,
    country_map: Dict[int, str],
    product_dir: Optional[Path] = None,
) -> tuple[pd.DataFrame, List[dict], Optional[pd.DataFrame]]:
    """Aggregate one BACI year into country-level edges for every sector.

    With ``product_dir`` the HS6 rows of at least ``MIN_FLOW_THOUSAND_USD`` are
    written there too, and per-product world totals are returned.
    """
    file_path = _find_baci_file(dataset_dir, year)

    partials: List[pd.DataFrame] = []
    product_rows: List[pd.DataFrame] = []
    product_totals: List[pd.Series] = []
    row_count = 0
    required_complete = 0
    value_present = 0
    quantity_present = 0

    reader = pd.read_csv(
        file_path,
        usecols=["t", "i", "j", "k", "v", "q"],
        dtype={"t": "int16", "i": "int32", "j": "int32", "k": "int32", "v": "float64", "q": "float64"},
        chunksize=READ_CHUNKSIZE,
    )

    for chunk in reader:
        row_count += len(chunk)
        required_complete += int(chunk[["t", "i", "j", "v"]].notna().all(axis=1).sum())
        value_present += int(chunk["v"].notna().sum())
        quantity_present += int(chunk["q"].notna().sum())

        labelled = chunk.assign(sector=label_sectors(chunk["k"] // 10000))
        partials.append(labelled.groupby(["i", "j", "sector"], as_index=False, observed=True)["v"].sum())

        if product_dir is not None:
            product_totals.append(chunk.groupby("k")["v"].sum())
            kept = chunk.loc[chunk["v"] >= MIN_FLOW_THOUSAND_USD, ["k", "i", "j", "v"]]
            product_rows.append(
                pd.DataFrame(
                    {
                        "k": kept["k"].astype("int32"),
                        "i": kept["i"].astype("int16"),
                        "j": kept["j"].astype("int16"),
                        "v": np.rint(kept["v"].to_numpy()).astype("int32"),
                    }
                )
            )

    if not partials:
        raise ValueError(f"No rows were read for year {year}.")

    labelled = (
        pd.concat(partials, ignore_index=True)
        .groupby(["i", "j", "sector"], as_index=False, observed=True)["v"]
        .sum()
    )

    # "all" is every product regardless of sector, so it is the sum over labels
    # rather than another pass over the file.
    everything = labelled.groupby(["i", "j"], as_index=False)["v"].sum()
    everything["sector"] = "all"

    combined = pd.concat([labelled, everything], ignore_index=True)
    combined["exporter"] = combined["i"].map(country_map)
    combined["importer"] = combined["j"].map(country_map)
    combined["year"] = int(year)

    edges = (
        combined.dropna(subset=["exporter", "importer"])
        .rename(columns={"v": "trade_value"})
        .loc[:, ["exporter", "importer", "year", "sector", "trade_value"]]
    )
    edges = edges[edges["exporter"] != edges["importer"]]
    edges = edges[edges["trade_value"] >= 0]
    edges = edges.sort_values(["sector", "exporter", "importer"]).reset_index(drop=True)

    # Completeness is measured once on the raw file, then attributed to each
    # sector slice carved out of it.
    quality_rows = [
        {
            "year": int(year),
            "sector": sector,
            "required_field_availability": required_complete / row_count if row_count else 0.0,
            "value_availability": value_present / row_count if row_count else 0.0,
            "quantity_availability": quantity_present / row_count if row_count else 0.0,
            "row_count": int(row_count),
            "quantity_observed": True,
            "aggregated_edges": int((edges["sector"] == sector).sum()),
        }
        for sector in SUPPORTED_SECTORS
    ]

    product_year = None
    if product_dir is not None:
        product_year = write_products(product_dir, year, product_rows, product_totals, set(country_map))

    return edges, quality_rows, product_year


def write_products(
    product_dir: Path,
    year: int,
    product_rows: List[pd.DataFrame],
    product_totals: List[pd.Series],
    known_codes: set,
) -> pd.DataFrame:
    """Write one year of the product store and return per-product world totals.

    Rows are sorted by product code with small row groups, so a read filtered
    to one code only decodes the few row groups whose code range covers it.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = pd.concat(product_rows, ignore_index=True)
    rows = rows[rows["i"].isin(known_codes) & rows["j"].isin(known_codes) & (rows["i"] != rows["j"])]
    rows = rows.sort_values(["k", "i", "j"]).reset_index(drop=True)

    product_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(rows, preserve_index=False),
        products_path(product_dir.parent, year),
        compression="zstd",
        compression_level=9,
        row_group_size=PRODUCT_ROW_GROUP,
    )

    totals = pd.concat(product_totals).groupby(level=0).sum()
    counts = rows.groupby("k").agg(exporters=("i", "nunique"), importers=("j", "nunique"))
    product_year = (
        pd.DataFrame({"world_value": totals})
        .join(counts, how="left")
        .fillna({"exporters": 0, "importers": 0})
        .rename_axis("k")
        .reset_index()
    )
    product_year["year"] = int(year)
    product_year["exporters"] = product_year["exporters"].astype("int32")
    product_year["importers"] = product_year["importers"].astype("int32")
    return product_year.loc[:, ["k", "year", "world_value", "exporters", "importers"]]


def compute_centrality(edges: pd.DataFrame) -> pd.DataFrame:
    """Precompute PageRank and betweenness for every sector in one year.

    Both metrics are deterministic for a given graph, and weighted betweenness
    is by far the most expensive thing a risk query does. Computing it once at
    build time turns risk analysis into a lookup.
    """
    import networkx as nx

    from core.graph_builder import build_trade_graph
    from core.risk_analyzer import _build_distance_graph

    records: List[pd.DataFrame] = []
    for sector in SUPPORTED_SECTORS:
        sector_edges = edges[edges["sector"] == sector]
        if sector_edges.empty:
            continue

        graph = build_trade_graph(sector_edges, sector=sector)
        pagerank = nx.pagerank(graph, weight="weight")
        betweenness = nx.betweenness_centrality(
            _build_distance_graph(graph), weight="weight", normalized=True
        )

        frame = pd.DataFrame(
            {
                "country": list(graph.nodes),
                "pagerank_centrality": [float(pagerank.get(node, 0.0)) for node in graph.nodes],
                "betweenness_centrality": [float(betweenness.get(node, 0.0)) for node in graph.nodes],
            }
        )
        frame["year"] = int(sector_edges["year"].iloc[0])
        frame["sector"] = sector
        records.append(frame)

    if not records:
        return pd.DataFrame(
            columns=["year", "sector", "country", "pagerank_centrality", "betweenness_centrality"]
        )

    return pd.concat(records, ignore_index=True).loc[
        :, ["year", "sector", "country", "pagerank_centrality", "betweenness_centrality"]
    ]


def summarize_country_year(edges: pd.DataFrame) -> pd.DataFrame:
    """Collapse aggregated edges into per-country yearly totals."""
    exports = (
        edges.groupby(["exporter", "year", "sector"], as_index=False)
        .agg(exports=("trade_value", "sum"), export_partners=("importer", "nunique"))
        .rename(columns={"exporter": "country"})
    )
    imports = (
        edges.groupby(["importer", "year", "sector"], as_index=False)
        .agg(imports=("trade_value", "sum"), import_partners=("exporter", "nunique"))
        .rename(columns={"importer": "country"})
    )

    totals = exports.merge(imports, on=["country", "year", "sector"], how="outer")
    numeric = ["exports", "imports", "export_partners", "import_partners"]
    totals[numeric] = totals[numeric].fillna(0.0)

    totals["trade_total"] = totals["imports"] + totals["exports"]
    safe_total = totals["trade_total"].replace(0.0, pd.NA)
    totals["import_dependency_ratio"] = (totals["imports"] / safe_total).fillna(0.0)
    totals["export_dependency_ratio"] = (totals["exports"] / safe_total).fillna(0.0)
    totals["export_partners"] = totals["export_partners"].astype(int)
    totals["import_partners"] = totals["import_partners"].astype(int)

    return totals.sort_values(["sector", "country", "year"]).reset_index(drop=True)


def process_year(
    dataset_dir: str,
    cache_dir: str,
    year: int,
    force: bool,
    with_centrality: bool,
    with_products: bool,
) -> dict:
    """Build one year end to end. Runs in a worker process."""
    started = time.time()
    dataset = Path(dataset_dir)
    cache = Path(cache_dir)
    target = edges_path(cache, year)
    product_target = products_path(cache, year)
    country_codes = _load_country_codes_cached(str(dataset))
    country_map = country_codes.set_index("country_code")["country_name"].to_dict()

    needs_products = with_products and (force or not product_target.exists())
    if target.exists() and not force and not needs_products:
        edges = pd.read_parquet(target)
        quality_rows: List[dict] = []
        product_year = None
        built = False
    else:
        edges, quality_rows, product_year = build_year(
            dataset, year, country_map, products_dir(cache) if with_products else None
        )
        edges.to_parquet(target, index=False, compression="zstd")
        built = True

    centrality_started = time.time()
    centrality = compute_centrality(edges) if with_centrality else None
    return {
        "year": int(year),
        "built": built,
        "edges": int(len(edges)),
        "summary": summarize_country_year(edges),
        "quality": pd.DataFrame(quality_rows),
        "centrality": centrality,
        "product_year": product_year,
        "seconds": time.time() - started,
        "centrality_seconds": time.time() - centrality_started,
        "size_mb": target.stat().st_size / 1_048_576,
    }


def write_catalog(dataset_dir: Path, cache_dir: Path, product_year: pd.DataFrame) -> None:
    """Write the HS6 catalog with descriptions, grouping, and latest world trade."""
    matches = sorted(dataset_dir.glob("product_codes_HS92_V*.csv"))
    if not matches:
        raise SystemExit(f"No product_codes_HS92 file was found in '{dataset_dir}'.")

    catalog = pd.read_csv(matches[0], dtype={"code": str}, encoding="utf-8")
    catalog["code"] = catalog["code"].astype(str).str.strip().str.zfill(6)
    # The code list carries a placeholder ("9999AA") that never occurs in trade rows.
    catalog = catalog[catalog["code"].str.fullmatch(r"\d{6}")].copy()
    catalog["description"] = catalog["description"].astype(str).str.strip()
    catalog["k"] = catalog["code"].astype(int)
    catalog["chapter"] = catalog["k"] // 10000
    catalog["hs4"] = catalog["code"].str[:4]
    catalog["sector"] = catalog["chapter"].map(sector_for_chapter)
    catalog["chapter_name"] = catalog["chapter"].map(HS_CHAPTERS).fillna("")
    catalog["hs4_label"] = catalog.groupby("hs4")["description"].transform(_heading_label)

    if not product_year.empty:
        latest = int(product_year["year"].max())
        recent = product_year[product_year["year"] == latest].set_index("k")
        catalog["world_value"] = catalog["k"].map(recent["world_value"]).fillna(0.0)
        catalog["exporters"] = catalog["k"].map(recent["exporters"]).fillna(0).astype(int)
        catalog["importers"] = catalog["k"].map(recent["importers"]).fillna(0).astype(int)
        catalog["value_year"] = latest
    else:
        catalog["world_value"] = 0.0
        catalog["exporters"] = 0
        catalog["importers"] = 0
        catalog["value_year"] = 0

    catalog = catalog.loc[
        :,
        [
            "k", "code", "hs4", "chapter", "sector", "description", "hs4_label", "chapter_name",
            "world_value", "exporters", "importers", "value_year",
        ],
    ].sort_values("k")
    catalog.to_parquet(catalog_path(cache_dir), index=False, compression="zstd")


def _heading_label(descriptions: pd.Series) -> str:
    """Name an HS4 heading from its subheadings' descriptions.

    BACI only describes six-digit codes, but most read "Heading: detail"
    ("Sugars: cane sugar, raw, ..."), so the distinct texts before the colon,
    in code order, name the heading ("Sugars; Sucrose" for 1701).
    """
    names: list[str] = []
    for text in descriptions:
        name = str(text).split(":", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    label = "; ".join(names[:3])
    return label if len(label) <= 80 else f"{label[:77].rstrip()}..."


def build(
    dataset_dir: Path,
    cache_dir: Path,
    years: Optional[Iterable[int]],
    force: bool,
    with_centrality: bool = True,
    with_products: bool = True,
    workers: int = 2,
) -> None:
    """Build the parquet cache for the requested years."""
    if not is_baci_directory(dataset_dir):
        raise SystemExit(f"'{dataset_dir}' does not contain BACI yearly files.")

    all_years = available_years(dataset_dir)
    selected = sorted(set(years) & set(all_years)) if years else all_years
    if not selected:
        raise SystemExit("No matching BACI years were found for the requested selection.")

    (cache_dir / "edges").mkdir(parents=True, exist_ok=True)
    if with_products:
        products_dir(cache_dir).mkdir(parents=True, exist_ok=True)

    country_codes = _load_country_codes_cached(str(dataset_dir))
    # Bundle the code table so the cache works without the raw dataset present.
    country_codes.to_parquet(countries_path(cache_dir), index=False, compression="snappy")

    # A partial rebuild keeps the rows the previous build wrote for other years,
    # and every year not selected still contributes its edges to the totals.
    other_years = [
        year for year in available_years(dataset_dir)
        if year not in selected and edges_path(cache_dir, year).exists()
    ]
    jobs = selected + other_years

    results: List[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {
            pool.submit(
                process_year,
                str(dataset_dir),
                str(cache_dir),
                year,
                force and year in selected,
                with_centrality,
                with_products and year in selected,
            ): year
            for year in jobs
        }
        for position, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(
                f"[{position}/{len(jobs)}] {result['year']}  "
                f"{'built ' if result['built'] else 'cached'}  {result['edges']:>7,} edges  "
                f"{result['size_mb']:5.1f} MB  {result['seconds']:5.1f}s "
                f"(centrality {result['centrality_seconds']:4.1f}s)",
                flush=True,
            )

    country_year = pd.concat([r["summary"] for r in results], ignore_index=True)
    country_year = country_year.sort_values(["sector", "country", "year"]).reset_index(drop=True)
    country_year.to_parquet(country_year_path(cache_dir), index=False, compression="zstd")

    quality = pd.concat([r["quality"] for r in results if not r["quality"].empty], ignore_index=True) \
        if any(not r["quality"].empty for r in results) else pd.DataFrame()
    if quality_path(cache_dir).exists():
        previous = pd.read_parquet(quality_path(cache_dir))
        if not quality.empty:
            previous = previous[~previous["year"].isin(quality["year"].unique())]
        quality = pd.concat([previous, quality], ignore_index=True)
    if not quality.empty:
        quality = quality.sort_values(["year", "sector"]).reset_index(drop=True)
        quality.to_parquet(quality_path(cache_dir), index=False, compression="snappy")

    if with_centrality:
        centrality = pd.concat([r["centrality"] for r in results if r["centrality"] is not None], ignore_index=True)
        centrality = centrality.sort_values(["year", "sector", "country"]).reset_index(drop=True)
        centrality.to_parquet(centrality_path(cache_dir), index=False, compression="zstd")

    if with_products:
        frames = [r["product_year"] for r in results if r["product_year"] is not None]
        if product_year_path(cache_dir).exists():
            previous = pd.read_parquet(product_year_path(cache_dir))
            fresh_years = {int(frame["year"].iloc[0]) for frame in frames if not frame.empty}
            frames.insert(0, previous[~previous["year"].isin(fresh_years)])
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            raise SystemExit("No product totals were produced; rebuild with --force to write the product store.")
        product_year = pd.concat(frames, ignore_index=True)
        product_year = product_year.sort_values(["k", "year"]).reset_index(drop=True)
        product_year.to_parquet(product_year_path(cache_dir), index=False, compression="zstd")
        write_catalog(dataset_dir, cache_dir, product_year)

        product_years = sorted(
            int(path.stem.rsplit("_", 1)[1]) for path in products_dir(cache_dir).glob("products_*.parquet")
        )
        product_meta_path(cache_dir).write_text(
            json.dumps(
                {
                    "store_version": PRODUCT_STORE_VERSION,
                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "years": product_years,
                    "min_flow_thousand_usd": MIN_FLOW_THOUSAND_USD,
                    "value_unit": "thousand USD, rounded to the nearest thousand",
                    "nomenclature": "HS92",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    built_years = sorted(
        int(path.stem.rsplit("_", 1)[1]) for path in (cache_dir / "edges").glob("edges_*.parquet")
    )
    meta_path(cache_dir).write_text(
        json.dumps(
            {
                "cache_version": CACHE_VERSION,
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_directory": str(dataset_dir.resolve()),
                "years": built_years,
                "sectors": list(SUPPORTED_SECTORS),
                "countries": int(country_year["country"].nunique()),
                "has_centrality": centrality_path(cache_dir).exists(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    total_mb = sum(path.stat().st_size for path in cache_dir.rglob("*.parquet")) / 1_048_576
    print(
        f"\nCache ready in {time.time() - started:.1f}s  |  "
        f"{len(built_years)} years  |  {country_year['country'].nunique()} countries  |  {total_mb:.1f} MB",
        flush=True,
    )
    print(f"Location: {cache_dir.resolve()}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BACI parquet cache.")
    parser.add_argument("--dataset", default="dataset", help="Directory holding the BACI yearly CSVs.")
    parser.add_argument("--cache", default="cache", help="Directory to write the parquet cache into.")
    parser.add_argument("--years", nargs="*", type=int, default=None, help="Limit the build to these years.")
    parser.add_argument("--force", action="store_true", help="Rebuild years that are already cached.")
    parser.add_argument("--workers", type=int, default=2, help="Years built in parallel (each needs ~1.5 GB RAM).")
    parser.add_argument(
        "--skip-centrality",
        action="store_true",
        help="Skip precomputing PageRank and betweenness. Builds faster; risk queries stay slow.",
    )
    parser.add_argument(
        "--skip-products",
        action="store_true",
        help="Skip the HS6 product store. The module then cannot filter to a single product.",
    )
    args = parser.parse_args()

    build(
        Path(args.dataset),
        Path(args.cache),
        args.years,
        args.force,
        with_centrality=not args.skip_centrality,
        with_products=not args.skip_products,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
