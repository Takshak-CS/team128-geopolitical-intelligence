"""FastAPI application exposing the trade intelligence agent.

Surfaces:

    POST /query            run an analysis and get the standard agent envelope
    GET  /graph            a visualization-friendly network snapshot
    GET  /sectors          the sector catalog with world trade per sector
    GET  /products         search HS products by name or code
    GET  /products/{code}  what one HS code covers, with its world trade history
    GET  /capabilities     what this agent can answer, and over what data
    GET  /health           liveness and readiness for container orchestration

``/capabilities`` exists for the orchestration layer. An orchestrator deciding
whether to route a question here should not have to read this file to find out
which query types, sectors, years, and countries the agent supports.
"""

from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent import trade_agent
from core import baci_cache, product_store
from core.data_loader import (
    cache_directory,
    cache_ready,
    coverage_years,
    latest_year,
    load_trade_data,
    product_data_ready,
    resolve_baci_country,
)
from core.graph_builder import build_graph_payload, build_trade_graph
from core.metadata import metadata_available
from core.output_formatter import AGENT_NAME
from core.sector_mapper import SUPPORTED_SECTORS, normalize_product, sector_catalog

QueryType = Literal["risk", "shock", "forecast", "leverage", "blocs", "fragility", "market", "bilateral"]
SectorName = Literal[SUPPORTED_SECTORS]  # type: ignore[valid-type]

API_VERSION = "2.1.0"

# Queries that operate on a single-year network snapshot rather than a history.
SNAPSHOT_QUERIES = {"risk", "shock", "leverage", "blocs", "fragility", "market", "bilateral"}

# Parameters that only mean something to one family of query types. Sending
# them elsewhere is dropped before the agent sees it, as before.
SHOCK_ONLY = ("severity", "steps", "propagation_factor")
FORECAST_FIELDS = ("metric", "forecast_model", "periods")

# The frontend is served separately, so the API needs CORS - but a wildcard lets
# any page the user has open reach a locally running instance. Default to the
# origins the bundled frontend actually uses, and let a deployment override it.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def configured_origins() -> list[str]:
    """Allowed CORS origins, overridable with TRADE_CORS_ORIGINS."""
    configured = os.environ.get("TRADE_CORS_ORIGINS", "").strip()
    if not configured:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


class TradeQuery(BaseModel):
    """Validated request body for the trade intelligence endpoint."""

    # Reject unknown fields rather than dropping them. Pydantic's default is to
    # ignore them, which means a caller that misspells a parameter -- "yr"
    # instead of "year" -- gets a successful response computed against the
    # default instead of an error. Across four agents wiring up to this API,
    # a plausible-but-wrong answer is far more expensive than a 422.
    model_config = ConfigDict(extra="forbid")

    query_type: QueryType
    country: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Country name, ISO2, ISO3, or BACI numeric code. "
        "For risk, leverage, blocs, and fragility this switches from a ranked "
        "network view to a single-country profile.",
    )
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    severity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    limit: int = Field(default=5, ge=1, le=50)
    sector: SectorName = "all"
    product: Optional[str] = Field(
        default=None,
        max_length=12,
        description="HS code narrowing the analysis to one product: 2 digits for a chapter "
        "(17), 4 for a heading (1701) or 6 for a subheading (170111). Not used by fragility.",
    )
    partner: Optional[str] = Field(
        default=None,
        max_length=64,
        description="The second country of a bilateral query.",
    )
    metric: Optional[Literal["imports", "exports"]] = None
    forecast_model: Optional[Literal["auto", "linear", "arima", "hybrid"]] = None
    periods: Optional[int] = Field(default=None, ge=1, le=10)
    steps: Optional[int] = Field(default=3, ge=1, le=10)
    top_n_partners: Optional[int] = Field(default=3, ge=1, le=10)
    propagation_factor: Optional[float] = Field(default=0.7, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_by_query_type(self) -> "TradeQuery":
        """Apply query-type-specific defaults and validation."""
        if self.query_type == "shock":
            if not self.country:
                raise ValueError("Shock queries require a country.")
            if self.severity is None:
                raise ValueError("Shock queries require a severity between 0 and 1.")

        if self.query_type == "forecast":
            if not self.country:
                raise ValueError("Forecast queries require a country.")
            if self.metric is None:
                self.metric = "exports"
            if self.forecast_model is None:
                self.forecast_model = "auto"
            if self.periods is None:
                self.periods = 3

        if self.query_type == "bilateral":
            if not self.country or not self.partner:
                raise ValueError("Bilateral queries require a country and a partner.")
            if self.forecast_model is None:
                self.forecast_model = "auto"
            if self.periods is None:
                self.periods = 3
        elif self.partner:
            raise ValueError("partner applies only to bilateral queries.")

        if self.product is not None:
            self.product = normalize_product(self.product)
            if self.query_type == "fragility":
                raise ValueError(
                    "Fragility compares sectors, so it cannot be narrowed to one product."
                )

        return self

    def to_agent_query(self) -> dict:
        """Convert the request model into the agent query dictionary."""
        payload = self.model_dump(exclude_none=True)

        if self.query_type == "forecast":
            payload.pop("year", None)
            payload.pop("severity", None)
            payload.pop("steps", None)
            payload.pop("top_n_partners", None)
            payload.pop("propagation_factor", None)
            payload["metric"] = self.metric or "exports"
            payload["forecast_model"] = self.forecast_model or "auto"
            payload["periods"] = self.periods or 3
        elif self.query_type == "bilateral":
            for key in (*SHOCK_ONLY, "metric", "top_n_partners"):
                payload.pop(key, None)
            payload["forecast_model"] = self.forecast_model or "auto"
            payload["periods"] = self.periods or 3
        else:
            payload.pop("metric", None)
            payload.pop("forecast_model", None)
            payload.pop("periods", None)
            if self.query_type != "shock":
                payload.pop("severity", None)

        return payload


app = FastAPI(
    title="Trade Graph Intelligence API",
    description=(
        "Graph-based trade intelligence over the CEPII BACI dataset. "
        "Answers risk, shock propagation, forecasting, dependence leverage, "
        "trade bloc, sector fragility, market structure, and two-country relationship "
        "questions, for 14 sectors or any single HS product."
    ),
    version=API_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.post("/query")
def query_trade_agent(request: TradeQuery) -> dict:
    """Run a trade analysis query and return structured insights."""
    try:
        return trade_agent.execute(request.to_agent_query())
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {exc}") from exc


@app.get("/graph")
def get_trade_graph(
    year: Optional[int] = Query(default=None, ge=1900, le=2100),
    sector: SectorName = "all",
    product: Optional[str] = Query(default=None, max_length=12),
    max_edges: int = Query(default=140, ge=20, le=400),
    focus: Optional[list[str]] = Query(
        default=None,
        description="Countries to centre on (repeat the parameter). Only flows touching them are kept.",
    ),
) -> dict:
    """Return a visualization-friendly graph snapshot for a year and a sector or product.

    ``focus`` keeps the strongest flows that touch the named countries, which is
    what a shock view needs when the shocked country is too small to appear
    among the network's strongest flows.
    """
    try:
        source_path = trade_agent.DEFAULT_DATA_PATH
        code = normalize_product(product)
        if code:
            info = product_store.describe_product(cache_directory(), code)
            sector = info["sector"]
            selected_year = max(product_store.product_years(cache_directory())) if year is None else int(year)
        else:
            selected_year = latest_year(source_path) if year is None else int(year)
        trade_data = load_trade_data(source_path, year=selected_year, sector=sector, product=code)
        graph = build_trade_graph(trade_data, sector=sector)
        focus_names: list[str] = []
        for name in (focus or [])[:60]:
            try:
                focus_names.append(resolve_baci_country(source_path, name)[1])
            except ValueError:
                continue
        payload = build_graph_payload(graph, max_edges=max_edges, focus=focus_names)
        payload["year"] = selected_year
        payload["sector"] = sector
        payload["product"] = code
        payload["focus"] = [name for name in focus_names if name in graph]
        return payload
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {exc}") from exc


@app.get("/sectors")
def get_sectors(year: Optional[int] = Query(default=None, ge=1900, le=2100)) -> dict:
    """The sector catalog, with each sector's world trade in a year."""
    sectors = sector_catalog()
    selected_year = None
    if cache_ready():
        try:
            selected_year = latest_year(trade_agent.DEFAULT_DATA_PATH) if year is None else int(year)
            totals = baci_cache.sector_world_totals(cache_directory(), selected_year)
            for sector in sectors:
                sector["world_trade"] = totals.get(sector["id"])
        except (ValueError, OSError):
            pass
    return {
        "year": selected_year,
        "value_unit": "thousand USD",
        "products_available": product_data_ready(),
        "sectors": sectors,
    }


@app.get("/products")
def get_products(
    q: str = Query(default="", max_length=80),
    sector: SectorName = "all",
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    """Search HS products by words in their description or by code prefix.

    Answers with ``available: false`` and no products when the product store
    is not installed, so a dashboard can hide its product picker.
    """
    if not product_data_ready():
        return {"available": False, "products": [], "chapters": []}
    try:
        cache_dir = cache_directory()
        products = product_store.search_products(cache_dir, q, sector=sector, limit=limit)
        chapters = [] if q.strip() else product_store.sector_products(cache_dir, sector)["chapters"]
        meta = product_store.product_meta(cache_dir)
        return {
            "available": True,
            "query": q,
            "sector": sector,
            "value_unit": "thousand USD",
            "value_year": max(meta.get("years") or [0]) or None,
            "products": products,
            "chapters": chapters,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/products/{code}")
def get_product(code: str) -> dict:
    """What one HS code covers, and its world trade in every year."""
    if not product_data_ready():
        raise HTTPException(status_code=404, detail="Product-level data is not installed on this deployment.")
    try:
        cache_dir = cache_directory()
        info = product_store.describe_product(cache_dir, code)
        info["world_trade_series"] = product_store.product_world_series(cache_dir, info["code"])
        return info
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    """Liveness and readiness.

    ``ready`` is False when no data source is reachable, which is the state a
    container orchestrator should treat as "do not route traffic here yet".
    """
    years = coverage_years(trade_agent.DEFAULT_DATA_PATH)
    return {
        "status": "ok" if years else "degraded",
        "ready": bool(years),
        "agent": AGENT_NAME,
        "version": API_VERSION,
        "cache_enabled": cache_ready(),
        "years_available": len(years),
    }


@app.get("/capabilities")
def capabilities() -> dict:
    """Describe what this agent can answer, for orchestrator discovery."""
    data_path = trade_agent.DEFAULT_DATA_PATH
    years = coverage_years(data_path)
    using_cache = cache_ready()

    countries: list[str] = []
    if using_cache:
        try:
            countries = baci_cache.known_countries(cache_directory())
        except (ValueError, OSError):
            countries = []

    return {
        "agent": AGENT_NAME,
        "version": API_VERSION,
        "description": (
            "Models international trade as a directed weighted graph and answers "
            "questions about structural risk, disruption propagation, dependence "
            "asymmetry, trading blocs, sector substitutability, and trade trends."
        ),
        "response_envelope": {
            "agent": AGENT_NAME,
            "metadata": "object: query_type, year, sector, data_quality, method",
            "insights": [
                {
                    "entity_iso3": "string or null, the shared join key across agents",
                    "entity_name": "string, human-readable label for the same entity",
                    "claim": "string, one self-contained human-readable finding",
                    "score": "float, sortable, meaning depends on query_type",
                    "confidence": "float 0-1",
                    "reason": "string explaining what limited the confidence",
                    "evidence": "object, the numbers the claim rests on",
                }
            ],
        },
        "join_key": "entity_iso3",
        "contract": "Team 128 shared four-agent response envelope",
        "query_types": {
            "risk": {
                "description": "Rank countries by structural exposure in the trade network.",
                "country": "optional; supplying it returns that country's profile and rank",
                "score_meaning": "composite risk score, higher is more exposed",
            },
            "shock": {
                "description": "Propagate an export disruption and rank affected countries.",
                "country": "required; the country whose exports are disrupted",
                "requires": ["severity"],
                "score_meaning": "share of imports lost, 0-1",
            },
            "forecast": {
                "description": "Project a country's imports or exports forward.",
                "country": "required",
                "score_meaning": "projected fractional change over the horizon",
            },
            "leverage": {
                "description": "Find asymmetric dependence: who needs whom more.",
                "country": "optional; supplying it returns that country's leverage position",
                "score_meaning": "dependence asymmetry, higher means more lopsided",
            },
            "blocs": {
                "description": "Detect trading blocs via Louvain community detection.",
                "country": "optional; supplying it returns that country's bloc membership",
                "score_meaning": "share of world trade for a bloc, or internal trade share for a country",
            },
            "fragility": {
                "description": "Compare sectors to find where supply is hardest to substitute.",
                "country": "optional; supplying it returns that country's sector profile",
                "score_meaning": "fragility score, higher is more brittle",
            },
            "market": {
                "description": "Rank the exporters and importers of a sector or product, with concentration.",
                "country": "optional; supplying it returns that country's exporter and importer position",
                "score_meaning": "share of world trade in the sector or product",
            },
            "bilateral": {
                "description": "Two countries' trade with each other: flows, balance, dependence, history, forecast.",
                "country": "required",
                "requires": ["partner"],
                "score_meaning": "share of the country's trade that runs through the partner",
            },
        },
        "parameters": {
            "sector": list(SUPPORTED_SECTORS),
            "sectors": sector_catalog(),
            "product": {
                "available": product_data_ready(),
                "format": "HS92 code: 2 digits (chapter), 4 (heading) or 6 (subheading)",
                "search": "/products?q=",
                "not_for": ["fragility"],
            },
            "partner": "country identifier; bilateral only",
            "limit": {"min": 1, "max": 50, "default": 5},
            "severity": {"min": 0.0, "max": 1.0},
            "steps": {"min": 1, "max": 10, "default": 3},
            "periods": {"min": 1, "max": 10, "default": 3},
            "forecast_model": ["auto", "linear", "arima", "hybrid"],
            "metric": ["imports", "exports"],
        },
        "coverage": {
            "source": "CEPII BACI HS92",
            "years": years,
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "country_count": len(countries),
            "countries": countries,
        },
        "country_identifiers": ["name", "iso2", "iso3", "baci_numeric"],
        "enrichment": {
            "economic_metadata": using_cache and metadata_available(cache_directory()),
            "precomputed_centrality": using_cache
            and baci_cache.centrality_path(cache_directory()).exists(),
        },
    }
