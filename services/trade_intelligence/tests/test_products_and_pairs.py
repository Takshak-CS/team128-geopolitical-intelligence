"""Sectors, product filtering, market structure, and two-country relationships.

The sector catalog tests need nothing. The rest need the parquet cache, and the
product tests also need the product store (cache/products/), which is not in
git; they skip cleanly when it has not been built.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import app
from core import baci_cache, product_store
from core.data_loader import cache_directory, cache_ready, latest_year, product_data_ready
from core.sector_mapper import (
    CHAPTER_TO_SECTOR,
    HS_CHAPTERS,
    LEGACY_SECTORS,
    SECTOR_DEFINITIONS,
    SUPPORTED_SECTORS,
    normalize_product,
    normalize_sector,
    product_code_range,
    sector_for_product,
    sector_summary_label,
)

client = TestClient(app)

requires_cache = pytest.mark.skipif(not cache_ready(), reason="Needs the parquet cache.")
requires_products = pytest.mark.skipif(
    not product_data_ready(), reason="Needs the product store (scripts/build_cache.py)."
)


# --------------------------------------------------------------------------
# Sector catalog
# --------------------------------------------------------------------------


def test_sectors_partition_the_hs_chapters():
    """Every chapter belongs to exactly one sector, so sectors add up to 'all'."""
    seen: dict[int, str] = {}
    for sector, definition in SECTOR_DEFINITIONS.items():
        for chapter in definition["chapters"]:
            assert chapter not in seen, f"chapter {chapter} is in {seen.get(chapter)} and {sector}"
            seen[chapter] = sector
    assert set(seen) == set(HS_CHAPTERS)
    assert CHAPTER_TO_SECTOR == seen


def test_original_sectors_keep_their_chapters_and_labels():
    assert SUPPORTED_SECTORS[:4] == ("all", "energy", "agriculture", "electronics")
    assert SECTOR_DEFINITIONS["agriculture"]["chapters"] == tuple(range(1, 25))
    assert SECTOR_DEFINITIONS["energy"]["chapters"] == (27,)
    assert SECTOR_DEFINITIONS["electronics"]["chapters"] == (84, 85, 90)
    for sector in LEGACY_SECTORS:
        assert sector_summary_label(sector) == f"{sector.title()} sector"
    assert sector_summary_label("metals") == "Base metals sector"


def test_sector_names_are_forgiving():
    assert normalize_sector("Wood Paper") == "wood_paper"
    assert normalize_sector("precious-metals") == "precious_metals"
    assert normalize_sector(None) == "all"
    with pytest.raises(ValueError):
        normalize_sector("spaceships")


def test_build_labels_match_the_catalog():
    from scripts.build_cache import label_sectors

    chapters = pd.Series(sorted(HS_CHAPTERS))
    labels = label_sectors(chapters)
    assert list(labels) == [CHAPTER_TO_SECTOR[c] for c in chapters]


@pytest.mark.parametrize(
    "given, expected",
    [("1701", "1701"), ("17.01", "1701"), ("1701.11", "170111"), ("170111", "170111"),
     ("10111", "010111"), ("101", "0101"), ("27", "27"), (" 8542 ", "8542")],
)
def test_product_codes_normalize(given, expected):
    assert normalize_product(given) == expected


@pytest.mark.parametrize("bad", ["sugar", "1701111", "77", "98", "12a4"])
def test_bad_product_codes_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_product(bad)


def test_product_code_ranges_and_sectors():
    assert product_code_range("17") == (170000, 179999)
    assert product_code_range("1701") == (170100, 170199)
    assert product_code_range("170111") == (170111, 170111)
    assert sector_for_product("121292") == "agriculture"
    assert sector_for_product("8542") == "electronics"
    assert sector_for_product("9301") == "arms"


# --------------------------------------------------------------------------
# Request validation (no data needed)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"query_type": "bilateral", "country": "India"},
        {"query_type": "risk", "partner": "China"},
        {"query_type": "fragility", "product": "1701"},
        {"query_type": "market", "product": "sugar"},
        {"query_type": "market", "sector": "spaceships"},
    ],
)
def test_invalid_new_parameters_are_rejected(body):
    assert client.post("/query", json=body).status_code == 422


# --------------------------------------------------------------------------
# Sector cache
# --------------------------------------------------------------------------


@requires_cache
def test_named_sectors_add_up_to_all():
    year = latest_year("dataset")
    edges = pd.read_parquet(baci_cache.edges_path(cache_directory(), year))
    totals = edges.groupby("sector")["trade_value"].sum()
    assert set(SUPPORTED_SECTORS) <= set(totals.index)
    named = float(totals.drop("all").sum())
    assert named == pytest.approx(float(totals["all"]), rel=1e-9)


@requires_cache
def test_sectors_endpoint_lists_every_sector_with_world_trade():
    payload = client.get("/sectors").json()
    ids = [sector["id"] for sector in payload["sectors"]]
    assert ids == list(SUPPORTED_SECTORS)
    world = {s["id"]: s.get("world_trade") for s in payload["sectors"]}
    assert world["all"] > 0
    assert sum(value for key, value in world.items() if key != "all") == pytest.approx(world["all"], rel=1e-6)


# --------------------------------------------------------------------------
# Market structure
# --------------------------------------------------------------------------


@requires_cache
def test_market_ranks_exporters_and_importers():
    payload = client.post("/query", json={"query_type": "market", "sector": "energy", "limit": 5}).json()
    roles = [insight["evidence"]["role"] for insight in payload["insights"]]
    assert roles == ["exporter"] * 5 + ["importer"] * 5
    shares = [i["evidence"]["world_share"] for i in payload["insights"] if i["evidence"]["role"] == "exporter"]
    assert shares == sorted(shares, reverse=True)
    meta = payload["metadata"]
    assert 0 < meta["top3_exporter_share"] <= 1
    assert 0 < meta["exporter_concentration"] <= 1
    assert meta["world_trade_series"], "expected the world trade history"


@requires_cache
def test_market_profile_reports_both_roles():
    payload = client.post("/query", json={"query_type": "market", "country": "India", "sector": "pharmaceuticals"}).json()
    assert [i["evidence"]["role"] for i in payload["insights"]] == ["exporter", "importer"]
    assert all(i["entity_iso3"] == "IND" for i in payload["insights"])


# --------------------------------------------------------------------------
# Two-country relationship
# --------------------------------------------------------------------------


@requires_cache
def test_bilateral_reports_both_sides_consistently():
    response = client.post(
        "/query", json={"query_type": "bilateral", "country": "India", "partner": "China", "periods": 3}
    )
    assert response.status_code == 200, response.text
    first, second = response.json()["insights"]
    a, b = first["evidence"], second["evidence"]
    assert (first["entity_iso3"], second["entity_iso3"]) == ("IND", "CHN")
    assert a["exports_to_partner"] == b["imports_from_partner"]
    assert a["imports_from_partner"] == b["exports_to_partner"]
    assert a["trade_balance"] == pytest.approx(-b["trade_balance"])
    assert a["bilateral_trade"] == pytest.approx(a["exports_to_partner"] + a["imports_from_partner"])
    assert a["leverage_holder"] in {"India", "China"}
    assert len(a["forecast"]["values"]) == 3
    assert len(a["history"]) == len(baci_cache.cached_years(cache_directory()))


@requires_cache
def test_bilateral_matches_the_snapshot_graph_and_sector_breakdown():
    year = latest_year("dataset")
    payload = client.post(
        "/query", json={"query_type": "bilateral", "country": "USA", "partner": "Mexico", "year": year}
    ).json()
    evidence = payload["insights"][0]["evidence"]
    edges = baci_cache.load_year(cache_directory(), year, "all")
    flow = edges[(edges["exporter"] == "USA") & (edges["importer"] == "Mexico")]["trade_value"].sum()
    assert evidence["exports_to_partner"] == pytest.approx(float(flow))
    sectors = evidence["sectors"]
    assert {s["sector"] for s in sectors} <= set(SECTOR_DEFINITIONS)
    assert sum(s["a_to_b"] for s in sectors) == pytest.approx(evidence["exports_to_partner"], rel=1e-9)
    assert evidence["history"][-1]["a_to_b"] == pytest.approx(evidence["exports_to_partner"])


@requires_cache
def test_bilateral_rejects_the_same_country_twice():
    response = client.post("/query", json={"query_type": "bilateral", "country": "India", "partner": "IND"})
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Product store
# --------------------------------------------------------------------------


@requires_products
def test_product_search_finds_sugar_cane_first():
    results = product_store.search_products(cache_directory(), "sugar cane", limit=5)
    assert results[0]["code"] == "121292"
    by_code = {item["code"] for item in client.get("/products?q=8542").json()["products"]}
    assert "8542" in by_code


@requires_products
def test_product_search_respects_the_sector():
    results = client.get("/products?q=oil&sector=energy&limit=20").json()["products"]
    assert results and all(item["sector"] == "energy" for item in results)


@requires_products
def test_describe_product_levels():
    directory = cache_directory()
    assert product_store.describe_product(directory, "17")["level"] == "chapter"
    assert product_store.describe_product(directory, "1701")["level"] == "heading"
    sub = product_store.describe_product(directory, "170111")
    assert sub["level"] == "subheading" and sub["sector"] == "agriculture"
    detail = client.get("/products/170111").json()
    assert detail["world_trade_series"]
    assert client.get("/products/0199").status_code == 404


@requires_products
def test_product_flows_add_up_to_world_trade():
    """The $10,000 floor drops a sliver of value, never a material share."""
    directory = cache_directory()
    year = max(product_store.product_years(directory))
    frame = product_store.load_product_year(directory, year, "2709")
    world = [p for p in product_store.product_world_series(directory, "2709") if p["year"] == year][0]["value"]
    assert float(frame["trade_value"].sum()) == pytest.approx(world, rel=0.005)


@requires_products
def test_product_store_matches_the_sector_cache():
    directory = cache_directory()
    year = max(product_store.product_years(directory))
    energy = baci_cache.load_year(directory, year, "energy")["trade_value"].sum()
    chapter = product_store.load_product_year(directory, year, "27")["trade_value"].sum()
    assert float(chapter) == pytest.approx(float(energy), rel=0.005)


@requires_products
@pytest.mark.parametrize(
    "body",
    [
        {"query_type": "market", "product": "170111", "limit": 3},
        {"query_type": "risk", "product": "1001", "limit": 3},
        {"query_type": "shock", "product": "2846", "country": "China", "severity": 1.0, "limit": 3},
        {"query_type": "leverage", "product": "8542", "country": "China"},
        {"query_type": "leverage", "product": "8542", "limit": 3},
        {"query_type": "blocs", "product": "2709", "limit": 3},
        {"query_type": "forecast", "product": "170111", "country": "Brazil", "periods": 2},
        {"query_type": "bilateral", "product": "1201", "country": "Brazil", "partner": "China", "periods": 2},
    ],
)
def test_every_query_type_accepts_a_product(body):
    response = client.post("/query", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["metadata"]["product"] == body["product"]
    assert payload["insights"]
    assert all(i["evidence"].get("product") == body["product"] for i in payload["insights"])
    assert all(i["claim"].startswith(f"HS {body['product']}") for i in payload["insights"])


@requires_products
def test_a_product_outside_the_chosen_sector_is_explained():
    response = client.post("/query", json={"query_type": "market", "product": "1701", "sector": "energy"})
    assert response.status_code == 400
    assert "agriculture" in response.json()["detail"]


@requires_products
def test_graph_can_show_one_product():
    payload = client.get("/graph?product=170111&max_edges=40").json()
    assert payload["product"] == "170111" and payload["sector"] == "agriculture"
    assert 0 < len(payload["edges"]) <= 40
