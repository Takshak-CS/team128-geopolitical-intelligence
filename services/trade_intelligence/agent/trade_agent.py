"""Main execution entry point for the Trade Graph Intelligence Agent.

One entry point, ``execute(query)``, routes a dictionary query to the right
analysis and returns the standard agent envelope described in
``core.output_formatter``. Eight query types are supported:

    market      who supplies and who buys a sector or product, and how concentrated it is
    risk        which countries are structurally exposed in the trade network
    shock       what happens downstream when one country's exports are cut
    forecast    where a country's trade is heading
    bilateral   how two countries trade with each other, and where it is heading
    leverage    who depends on whom, and who could walk away
    blocs       which countries cluster into trading blocs
    fragility   which sectors a country cannot easily substitute out of

``market``, ``risk``, ``leverage``, ``blocs``, and ``fragility`` all accept an
optional country. With one, they return that country's profile; without one,
they return a ranked view of the whole network.

Every query except fragility can be narrowed from a sector to one product with
``product``, an HS code of 2, 4 or 6 digits ("1701" cane or beet sugar).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx
import pandas as pd

from core import baci_cache, product_store
from core.community import detect_trade_blocs, inter_bloc_flows, summarize_blocs
from core.confidence import build_confidence_assessment, combine_forecast_confidence_assessment
from core.data_loader import (
    cache_directory,
    cache_ready,
    can_resolve_countries,
    latest_year,
    load_country_time_series,
    load_trade_data,
    product_data_ready,
    resolve_baci_country,
)
from core.feature_engineering import compute_country_features
from core.forecast import forecast_metric_from_series
from core.fragility import compute_sector_fragility, fragility_profile, rank_sector_fragility
from core.graph_builder import build_trade_graph
from core.leverage import (
    bilateral_totals,
    compute_country_leverage,
    compute_leverage_pairs,
    country_totals,
    leverage_profile,
)
from core.metadata import (
    attach_economic_exposure,
    describe_exposure,
    load_metadata,
    metadata_available,
)
from core.output_formatter import build_insight, build_metadata, format_agent_output
from core.risk_analyzer import analyze_trade_risk
from core.sector_mapper import (
    LEGACY_SECTORS,
    SECTOR_DEFINITIONS,
    SUPPORTED_SECTORS,
    normalize_product,
    normalize_sector,
    sector_for_product,
    sector_label as sector_display_label,
    sector_summary_label,
)
from core.shock_simulator import simulate_trade_shock


DEFAULT_DATA_PATH = "dataset" if Path("dataset").exists() else "trade_data.csv"
FORECAST_METRICS = {"imports", "exports"}
QUERY_TYPES = ("risk", "shock", "forecast", "leverage", "blocs", "fragility", "market", "bilateral")

# Sector graphs other than "all", used by fragility comparisons. The sectors
# partition the HS chapters, so together they cover a country's whole imports.
COMPARABLE_SECTORS = tuple(sector for sector in SUPPORTED_SECTORS if sector != "all")

# Trade below this value (BACI thousands of USD) is excluded from network-wide
# leverage and fragility rankings, so micro-territories do not crowd out
# economically significant findings. Country-specific queries ignore it.
RANKING_TRADE_FLOOR = 1_000_000.0

# For a narrow sector or a single product a $1B floor would exclude nearly
# every relationship, so there the floor is this share of world trade instead.
RELATIVE_RANKING_FLOOR = 0.001



def execute(query: dict) -> dict:
    """Execute a trade intelligence query and return structured insights."""
    if not isinstance(query, dict):
        raise ValueError("Query must be a dictionary.")

    query_type = str(query.get("query_type", "risk")).strip().lower()
    if query_type not in QUERY_TYPES:
        supported = ", ".join(QUERY_TYPES)
        raise ValueError(f"Unsupported query_type '{query_type}'. Supported values: {supported}")

    data_path = str(query.get("data_path", DEFAULT_DATA_PATH))
    limit = max(1, int(query.get("limit", 10)))
    sector = normalize_sector(query.get("sector", "all"))
    sector, product_info = _resolve_product(query.get("product"), sector, query_type)

    if query_type == "forecast":
        return _execute_forecast_query(data_path, query, sector=sector, product_info=product_info)

    snapshot_year = _resolve_snapshot_year(data_path, query.get("year"), product_info)
    country = _resolve_country_name(data_path, query.get("country"))

    if query_type == "fragility":
        return _execute_fragility_query(data_path, snapshot_year, country, limit)

    if query_type == "bilateral":
        partner = _resolve_country_name(data_path, query.get("partner"))
        return _execute_bilateral_query(
            data_path, query, sector, product_info, snapshot_year, country, partner
        )

    product = product_info["code"] if product_info else None
    snapshot_data = load_trade_data(data_path, year=snapshot_year, sector=sector, product=product)
    graph = build_trade_graph(snapshot_data, sector=sector)
    data_quality = snapshot_data.attrs.get("data_quality")

    if query_type == "market":
        return _execute_market_query(
            data_path, graph, snapshot_year, country, limit, sector, product_info, data_quality
        )

    if query_type == "blocs":
        return _execute_blocs_query(
            graph, snapshot_year, country, limit, sector, data_quality, product_info
        )

    if query_type == "leverage":
        return _execute_leverage_query(
            graph, snapshot_year, country, limit, sector, data_quality, product_info
        )

    features = compute_country_features(graph)
    risk = analyze_trade_risk(
        graph,
        top_n_partners=max(1, int(query.get("top_n_partners", 3))),
        centrality=None if product_info else _precomputed_centrality(snapshot_year, sector),
    )

    if query_type == "shock":
        if not country:
            raise ValueError("Shock queries must include a 'country'.")
        return _execute_shock_query(
            graph, features, risk, query, country, snapshot_year, limit, sector, data_quality,
            product_info,
        )

    return _execute_risk_query(
        graph, features, risk, country, snapshot_year, limit, sector, data_quality, product_info
    )



def _resolve_product(product: object, sector: str, query_type: str) -> tuple[str, Optional[dict]]:
    """Validate a product filter and return the sector it implies."""
    code = normalize_product(product)
    if code is None:
        return sector, None
    if query_type == "fragility":
        raise ValueError(
            "Fragility compares sectors with each other, so it cannot be narrowed to one "
            "product. Drop the product, or use market or risk for it."
        )
    if not product_data_ready():
        product_store.require_store(cache_directory())
    product_sector = sector_for_product(code)
    if sector not in ("all", product_sector):
        raise ValueError(
            f"HS {code} belongs to the {sector_display_label(product_sector)} sector, not "
            f"{sector_display_label(sector)}. Set sector to '{product_sector}' or 'all'."
        )
    return product_sector, product_store.describe_product(cache_directory(), code)



def _scope_label(sector: str, product_info: Optional[dict]) -> str:
    """How a claim names what was analysed: a sector, or one HS product."""
    if product_info:
        return product_store.product_scope_label(product_info)
    return sector_summary_label(sector)



def _scope_evidence(sector: str, product_info: Optional[dict]) -> dict:
    """Sector and product fields every insight's evidence carries."""
    evidence: dict = {"sector": sector}
    if product_info:
        evidence["product"] = product_info["code"]
        evidence["product_label"] = product_info["label"]
    return evidence



def _scope_metadata(product_info: Optional[dict]) -> dict:
    if not product_info:
        return {}
    return {
        "product": product_info["code"],
        "product_level": product_info["level"],
        "product_label": product_info["label"],
        "product_chapter": product_info["chapter_name"],
        "minimum_flow_usd": product_store.MIN_FLOW_THOUSAND_USD * 1000,
    }



def _ranking_floor(graph: nx.DiGraph, sector: str, product_info: Optional[dict]) -> float:
    """Minimum relationship size for network-wide rankings.

    The original sectors keep the fixed $1B floor; narrower sectors and single
    products scale it to their own world trade.
    """
    if not product_info and (sector == "all" or sector in LEGACY_SECTORS):
        return RANKING_TRADE_FLOOR
    world = float(sum(data.get("weight", 0.0) for _, _, data in graph.edges(data=True)))
    return min(RANKING_TRADE_FLOOR, RELATIVE_RANKING_FLOOR * world)



def _execute_risk_query(
    graph: nx.DiGraph,
    features: pd.DataFrame,
    risk: pd.DataFrame,
    country: Optional[str],
    snapshot_year: int,
    limit: int,
    sector: str,
    data_quality: dict | None,
    product_info: Optional[dict] = None,
) -> dict:
    """Rank the network by risk, or profile one country's position in it."""
    merged = risk.merge(features, on="country", how="left")
    sector_label = _scope_label(sector, product_info)

    if country:
        selected = merged[merged["country"] == country]
        if selected.empty:
            raise ValueError(f"Country '{country}' is not present in the {snapshot_year} trade graph.")
        rank = int(merged.index[merged["country"] == country][0]) + 1
        rows = selected
    else:
        rank = None
        rows = merged.head(limit)

    insights: List[dict] = []
    for offset, row in enumerate(rows.itertuples(index=False)):
        confidence = build_confidence_assessment(
            data_quality=data_quality,
            graph=graph,
            country=row.country,
            propagation_steps=1,
        )
        position = rank if rank is not None else offset + 1
        summary = (
            f"{sector_label} in year {snapshot_year}: {row.country} ranks {position} of "
            f"{len(merged)} by risk score {row.risk_score:.3f}. Its top-{len(row.top_partners)} "
            f"partner share is {row.trade_concentration:.2%} across {row.partner_count} partners "
            f"(HHI {row.concentration_index:.3f}), with key partners "
            f"{format_partner_list(row.top_partners)}. {confidence['reason']}"
        )

        insight = build_insight(
            entity_iso3=_iso3(row.country),
            entity_name=row.country,
            claim=summary,
            score=float(row.risk_score),
            confidence=confidence["score"],
            reason=confidence["reason"],
            evidence={
                "rank": position,
                "countries_ranked": len(merged),
                **_scope_evidence(sector, product_info),
                "pagerank_centrality": float(row.pagerank_centrality),
                "betweenness_centrality": float(row.betweenness_centrality),
                "trade_concentration": float(row.trade_concentration),
                "concentration_index": float(row.concentration_index),
                "partner_count": int(row.partner_count),
                "top_partners": list(row.top_partners),
                "total_imports": _safe_float(getattr(row, "total_imports", None)),
                "total_exports": _safe_float(getattr(row, "total_exports", None)),
                "import_dependency_ratio": _safe_float(getattr(row, "import_dependency_ratio", None)),
                "export_dependency_ratio": _safe_float(getattr(row, "export_dependency_ratio", None)),
                "confidence_components": confidence["components"],
            },
        )
        insights.append(insight)

    return format_agent_output(
        insights,
        metadata=build_metadata(
            "risk",
            sector=sector,
            year=snapshot_year,
            country=country,
            method="pagerank + betweenness + partner concentration (HHI)",
            data_quality=data_quality,
            countries_ranked=len(merged),
            **_scope_metadata(product_info),
        ),
    )



def _execute_shock_query(
    graph: nx.DiGraph,
    features: pd.DataFrame,
    risk: pd.DataFrame,
    query: dict,
    country: str,
    snapshot_year: int,
    limit: int,
    sector: str,
    data_quality: dict | None,
    product_info: Optional[dict] = None,
) -> dict:
    """Run a shock simulation and convert it into ranked insights."""
    severity = float(query.get("severity", 0.5))
    steps = max(1, int(query.get("steps", 3)))
    propagation_factor = float(query.get("propagation_factor", 0.7))
    sector_label = _scope_label(sector, product_info)

    impact = simulate_trade_shock(
        graph=graph,
        country=country,
        severity=severity,
        steps=steps,
        propagation_factor=propagation_factor,
    )
    propagation_steps = int(impact.attrs.get("propagation_depth_used", steps))

    merged = (
        impact.merge(features, on="country", how="left")
        .merge(risk[["country", "risk_score"]], on="country", how="left")
        .fillna({"risk_score": 0.0})
    )
    merged = _enrich_with_economics(merged, features, snapshot_year)

    insights: List[dict] = []
    for row in merged.head(limit).itertuples(index=False):
        confidence = build_confidence_assessment(
            data_quality=data_quality,
            graph=graph,
            country=row.country,
            propagation_steps=propagation_steps,
        )
        gdp_exposure = _safe_float(getattr(row, "gdp_exposure", None))
        economic_clause = ""
        if gdp_exposure is not None:
            economic_clause = (
                f" That is roughly {gdp_exposure:.1%} of national output "
                f"({describe_exposure(gdp_exposure)})."
            )

        summary = (
            f"{sector_label} shock from {country} in year {snapshot_year} produces an estimated "
            f"impact score of {row.impact_score:.2%} for {row.country} after {propagation_steps} "
            f"propagation steps.{economic_clause} {confidence['reason']}"
        )

        insight = build_insight(
            entity_iso3=_iso3(row.country),
            entity_name=row.country,
            claim=summary,
            score=float(row.impact_score),
            confidence=confidence["score"],
            reason=confidence["reason"],
            evidence={
                **_scope_evidence(sector, product_info),
                "shock_origin": country,
                "shock_origin_iso3": _iso3(country),
                "severity": severity,
                "impact_score": float(row.impact_score),
                "applied_export_reduction": float(row.applied_export_reduction),
                "risk_score": float(row.risk_score),
                "propagation_steps": propagation_steps,
                "gdp_exposure": gdp_exposure,
                "disrupted_trade_usd": _safe_float(getattr(row, "disrupted_trade_usd", None)),
                "confidence_components": confidence["components"],
            },
        )
        insights.append(insight)

    return format_agent_output(
        insights,
        metadata=build_metadata(
            "shock",
            sector=sector,
            year=snapshot_year,
            country=country,
            method="iterative export-reduction propagation",
            data_quality=data_quality,
            severity=severity,
            propagation_steps=propagation_steps,
            requested_steps=steps,
            propagation_factor=propagation_factor,
            economics_available=_economics_available(),
            **_scope_metadata(product_info),
        ),
    )



def _execute_leverage_query(
    graph: nx.DiGraph,
    snapshot_year: int,
    country: Optional[str],
    limit: int,
    sector: str,
    data_quality: dict | None,
    product_info: Optional[dict] = None,
) -> dict:
    """Rank the most lopsided trade relationships, or profile one country."""
    floor = _ranking_floor(graph, sector, product_info)
    sector_label = _scope_label(sector, product_info)

    if country:
        profile = leverage_profile(graph, country, limit=limit)
        position = profile["position"]
        confidence = build_confidence_assessment(
            data_quality=data_quality, graph=graph, country=country, propagation_steps=1
        )

        dominated = position["partners_dominated"]
        dependent = position["partners_dependent_on"]
        critical = position["most_critical_partner"]
        summary = (
            f"{sector_label} in year {snapshot_year}: {country} holds leverage over {dominated} "
            f"partners and is the more dependent party with {dependent}. Its most critical single "
            f"relationship is {critical}, carrying "
            f"{position['critical_partner_dependence']:.1%} of its total trade. "
            f"Net leverage position {position['net_leverage']:.2f}. {confidence['reason']}"
        )

        insight = build_insight(
            entity_iso3=_iso3(country),
            entity_name=country,
            claim=summary,
            score=float(position["net_leverage"]),
            confidence=confidence["score"],
            reason=confidence["reason"],
            evidence={
                **_scope_evidence(sector, product_info),
                "leverage_held": float(position["leverage_held"]),
                "leverage_exposed": float(position["leverage_exposed"]),
                "net_leverage": float(position["net_leverage"]),
                "partners_dominated": int(dominated),
                "partners_dependent_on": int(dependent),
                "most_critical_partner": critical,
                "most_critical_partner_iso3": _iso3(critical),
                "critical_partner_dependence": float(position["critical_partner_dependence"]),
                "holds_leverage_over": profile["holds_leverage_over"],
                "vulnerable_to": profile["vulnerable_to"],
                "confidence_components": confidence["components"],
            },
        )
        insights = [insight]
        pair_count = None
    else:
        pairs = compute_leverage_pairs(graph, min_bilateral_trade=floor)
        pair_count = len(pairs)
        insights = []
        for row in pairs.head(limit).itertuples(index=False):
            confidence = build_confidence_assessment(
                data_quality=data_quality,
                graph=graph,
                country=row.exposed_country,
                propagation_steps=1,
            )
            summary = (
                f"{sector_label} in year {snapshot_year}: {row.exposed_country} routes "
                f"{row.exposed_dependence:.1%} of its trade through {row.leverage_holder}, which "
                f"routes only {row.holder_dependence:.2%} of its own through {row.exposed_country} "
                f"- a {row.exposure_ratio:.0f}x imbalance. {row.leverage_holder} could absorb a "
                f"rupture that {row.exposed_country} could not. {confidence['reason']}"
            )
            insight = build_insight(
                entity_iso3=_iso3(row.exposed_country),
                entity_name=row.exposed_country,
                claim=summary,
                score=float(row.asymmetry),
                confidence=confidence["score"],
                reason=confidence["reason"],
                evidence={
                    **_scope_evidence(sector, product_info),
                    "leverage_holder": row.leverage_holder,
                    "leverage_holder_iso3": _iso3(row.leverage_holder),
                    "exposed_country": row.exposed_country,
                    "bilateral_trade": float(row.bilateral_trade),
                    "holder_dependence": float(row.holder_dependence),
                    "exposed_dependence": float(row.exposed_dependence),
                    "asymmetry": float(row.asymmetry),
                    "exposure_ratio": float(row.exposure_ratio),
                    "confidence_components": confidence["components"],
                },
            )
            insights.append(insight)

    return format_agent_output(
        insights,
        metadata=build_metadata(
            "leverage",
            sector=sector,
            year=snapshot_year,
            country=country,
            method="bilateral dependence asymmetry",
            data_quality=data_quality,
            pairs_evaluated=pair_count,
            minimum_bilateral_trade=None if country else floor,
            **_scope_metadata(product_info),
        ),
    )



def _execute_blocs_query(
    graph: nx.DiGraph,
    snapshot_year: int,
    country: Optional[str],
    limit: int,
    sector: str,
    data_quality: dict | None,
    product_info: Optional[dict] = None,
) -> dict:
    """Detect trade blocs, or report which bloc one country belongs to."""
    assignment = detect_trade_blocs(graph)
    summary_frame = summarize_blocs(assignment)
    modularity = float(assignment.attrs.get("modularity", 0.0))
    sector_label = _scope_label(sector, product_info)

    world_trade = float(summary_frame["total_trade"].sum()) or 1.0

    if country:
        selected = assignment[assignment["country"] == country]
        if selected.empty:
            raise ValueError(f"Country '{country}' is not present in the {snapshot_year} trade graph.")
        row = selected.iloc[0]
        bloc = summary_frame[summary_frame["bloc_id"] == row["bloc_id"]].iloc[0]
        bloc_world_share = float(bloc["total_trade"]) / world_trade
        confidence = build_confidence_assessment(
            data_quality=data_quality, graph=graph, country=country, propagation_steps=1
        )

        summary = (
            f"{sector_label} in year {snapshot_year}: {country} belongs to the {row['bloc_name']} "
            f"bloc, one of {int(assignment.attrs.get('bloc_count', 0))} detected, with "
            f"{int(row['bloc_size'])} members and {bloc_world_share:.1%} of world trade activity. "
            f"{row['internal_trade_share']:.1%} of {country}'s own trade stays inside that bloc. "
            f"Largest members: {format_partner_list(bloc['members'])}. {confidence['reason']}"
        )
        insight = build_insight(
            entity_iso3=_iso3(country),
            entity_name=country,
            claim=summary,
            score=float(row["internal_trade_share"]),
            confidence=confidence["score"],
            reason=confidence["reason"],
            evidence={
                **_scope_evidence(sector, product_info),
                "bloc_id": int(row["bloc_id"]),
                "bloc_name": str(row["bloc_name"]),
                "bloc_anchor_iso3": _iso3(row["bloc_name"]),
                "bloc_size": int(row["bloc_size"]),
                "internal_trade_share": float(row["internal_trade_share"]),
                "world_trade_share": bloc_world_share,
                "bloc_members": list(bloc["all_members"]),
                "bloc_member_iso3": [code for code in (_iso3(m) for m in bloc["all_members"]) if code],
                "confidence_components": confidence["components"],
            },
        )
        insights = [insight]
    else:
        insights = []
        for row in summary_frame.head(limit).itertuples(index=False):
            confidence = build_confidence_assessment(
                data_quality=data_quality,
                graph=graph,
                country=row.bloc_name,
                propagation_steps=1,
            )
            share = float(row.total_trade) / world_trade
            summary = (
                f"{sector_label} in year {snapshot_year}: the {row.bloc_name} bloc has "
                f"{row.member_count} members and accounts for {share:.1%} of world trade activity. "
                f"On average {row.mean_internal_share:.1%} of a member's trade stays inside the "
                f"bloc. Largest members: {format_partner_list(row.members)}. {confidence['reason']}"
            )
            # A bloc is not a country, so it has no ISO3 of its own. It is
            # named after its largest member, whose code identifies the anchor
            # and lets fusion tie the bloc back to a real entity.
            insight = build_insight(
                entity_iso3=_iso3(row.bloc_name),
                entity_name=f"{row.bloc_name} bloc",
                claim=summary,
                score=share,
                confidence=confidence["score"],
                reason=confidence["reason"],
                evidence={
                    **_scope_evidence(sector, product_info),
                    "entity_kind": "trade_bloc",
                    "bloc_id": int(row.bloc_id),
                    "bloc_name": str(row.bloc_name),
                    "bloc_anchor_iso3": _iso3(row.bloc_name),
                    "member_count": int(row.member_count),
                    "members": list(row.members),
                    "bloc_members": list(row.all_members),
                    "bloc_member_iso3": [code for code in (_iso3(m) for m in row.all_members) if code],
                    "world_trade_share": share,
                    "mean_internal_share": float(row.mean_internal_share),
                    "confidence_components": confidence["components"],
                },
            )
            insights.append(insight)

    flows = inter_bloc_flows(graph, assignment)
    return format_agent_output(
        insights,
        metadata=build_metadata(
            "blocs",
            sector=sector,
            year=snapshot_year,
            country=country,
            method="Louvain community detection on the undirected trade projection",
            data_quality=data_quality,
            bloc_count=int(assignment.attrs.get("bloc_count", 0)),
            modularity=modularity,
            inter_bloc_flows=flows.head(12).to_dict(orient="records"),
            **_scope_metadata(product_info),
        ),
    )



def _execute_fragility_query(
    data_path: str,
    snapshot_year: int,
    country: Optional[str],
    limit: int,
) -> dict:
    """Compare sectors to find where supply is hardest to substitute."""
    graphs: Dict[str, nx.DiGraph] = {}
    sector_quality: Dict[str, dict] = {}
    for sector_name in COMPARABLE_SECTORS:
        sector_data = load_trade_data(data_path, year=snapshot_year, sector=sector_name)
        graphs[sector_name] = build_trade_graph(sector_data, sector=sector_name)
        sector_quality[sector_name] = dict(sector_data.attrs.get("data_quality") or {})

    sector_ranking = rank_sector_fragility(graphs)

    if country:
        profile = fragility_profile(graphs, country)
        insights = []
        for record in profile["sectors"]:
            noun = _sector_noun(record["sector"])
            summary = (
                f"{country} draws {noun} imports from {record['supplier_count']} "
                f"suppliers with concentration {record['supplier_concentration']:.3f}. Its largest "
                f"supplier is {record['top_supplier']} at {record['top_supplier_share']:.1%}, and "
                f"{noun} accounts for {record['sector_reliance']:.1%} of its total imports. "
                f"Fragility score {record['fragility_score']:.3f}."
            )
            insight = build_insight(
                entity_iso3=_iso3(country),
                entity_name=country,
                claim=summary,
                score=float(record["fragility_score"]),
                confidence=_fragility_confidence(record),
                reason=_fragility_reason(record),
                evidence={
                    **{key: value for key, value in record.items() if key != "country"},
                    "sector_label": sector_display_label(record["sector"]),
                    "top_supplier_iso3": _iso3(record.get("top_supplier")),
                },
            )
            insights.append(insight)
    else:
        fragility = compute_sector_fragility(graphs, min_sector_imports=RANKING_TRADE_FLOOR)
        insights = []
        for record in fragility.head(limit).to_dict(orient="records"):
            summary = (
                f"{record['country']} is most exposed in {_sector_noun(record['sector'])}: "
                f"{record['supplier_count']} suppliers, concentration "
                f"{record['supplier_concentration']:.3f}, largest supplier "
                f"{record['top_supplier']} at {record['top_supplier_share']:.1%}. That sector is "
                f"{record['sector_reliance']:.1%} of its total imports. Fragility score "
                f"{record['fragility_score']:.3f}."
            )
            insight = build_insight(
                entity_iso3=_iso3(record["country"]),
                entity_name=str(record["country"]),
                claim=summary,
                score=float(record["fragility_score"]),
                confidence=_fragility_confidence(record),
                reason=_fragility_reason(record),
                evidence={
                    **{key: value for key, value in record.items() if key != "country"},
                    "sector_label": sector_display_label(record["sector"]),
                    "top_supplier_iso3": _iso3(record.get("top_supplier")),
                },
            )
            insights.append(insight)

    return format_agent_output(
        insights,
        metadata=build_metadata(
            "fragility",
            sector="all",
            year=snapshot_year,
            country=country,
            method="supplier concentration weighted with sector reliance",
            data_quality={"by_sector": sector_quality},
            sectors_compared=list(COMPARABLE_SECTORS),
            sector_supply_concentration=sector_ranking.to_dict(orient="records"),
            minimum_sector_imports=None if country else RANKING_TRADE_FLOOR,
        ),
    )



def _execute_forecast_query(
    data_path: str,
    query: dict,
    sector: str,
    product_info: Optional[dict] = None,
) -> dict:
    """Run a multi-year forecast query for imports or exports."""
    country = query.get("country")
    if not country:
        raise ValueError("Forecast queries must include a 'country'.")

    metric = str(query.get("metric", "exports")).strip().lower()
    if metric not in FORECAST_METRICS:
        raise ValueError("Forecast metric must be either 'imports' or 'exports'.")
    forecast_model = str(query.get("forecast_model", query.get("model", "auto"))).strip().lower()

    periods = max(1, int(query.get("periods", 3)))
    product = product_info["code"] if product_info else None
    time_series_payload = load_country_time_series(
        data_path, str(country), sector=sector, product=product
    )
    resolved_country = str(time_series_payload["country"])
    forecast_result = forecast_metric_from_series(
        time_series=time_series_payload["time_series"],
        country=resolved_country,
        metric=metric,
        periods=periods,
        model=forecast_model,
    )

    latest_snapshot_year = _resolve_snapshot_year(data_path, None, product_info)
    latest_snapshot_data = load_trade_data(
        data_path, year=latest_snapshot_year, sector=sector, product=product
    )
    latest_graph = build_trade_graph(latest_snapshot_data, sector=sector)
    heuristic_confidence = build_confidence_assessment(
        data_quality=time_series_payload.get("data_quality"),
        graph=latest_graph,
        country=resolved_country,
        propagation_steps=1,
    )
    confidence = combine_forecast_confidence_assessment(
        heuristic_assessment=heuristic_confidence,
        model_confidence=float(forecast_result.get("model_confidence", forecast_result.get("confidence", 0.0))),
    )

    forecast_values = [
        {
            "year": int(item["year"]),
            "predicted_value": float(item["predicted_value"]),
        }
        for item in forecast_result["forecast"]
    ]
    first_year = forecast_values[0]["year"]
    final_year = forecast_values[-1]["year"]
    history = forecast_result["history"]
    history_values = [
        {
            "year": int(item["year"]),
            "value": float(item[metric]),
        }
        for item in history
    ]
    latest_actual = float(history[-1][metric])
    final_value = float(forecast_values[-1]["predicted_value"])
    projected_change = 0.0 if latest_actual == 0 else (final_value - latest_actual) / latest_actual
    trend_direction = _describe_trend(projected_change)
    horizon_text = f"{first_year}" if first_year == final_year else f"{first_year}-{final_year}"
    sector_label = _scope_label(sector, product_info)

    values_text = ", ".join(
        f"{item['year']}: {format_usd(item['predicted_value'])}" for item in forecast_values
    )
    article = "an" if trend_direction[:1].lower() in "aeiou" else "a"
    summary = (
        f"{sector_label} forecast indicates {article} {trend_direction} trend for {resolved_country} {metric} across "
        f"horizon {horizon_text}. The latest observed {metric} ({history[-1]['year']}) are "
        f"{format_usd(latest_actual)}, and the projected values are {values_text} "
        f"({projected_change:+.1%} overall). Forecast method: {forecast_result['method']}. {confidence['reason']}"
    )

    insight = build_insight(
        entity_iso3=_iso3(resolved_country),
        entity_name=resolved_country,
        claim=summary,
        score=float(projected_change),
        confidence=confidence["score"],
        reason=confidence["reason"],
        evidence={
            "trend": trend_direction,
            "metric": metric,
            "periods": periods,
            "horizon": horizon_text,
            **_scope_evidence(sector, product_info),
            "method": forecast_result["method"],
            "forecast_values": forecast_values,
            "history_values": history_values,
            "latest_actual": latest_actual,
            "forecast_model_scores": forecast_result.get("model_scores", {}),
            "model_confidence": float(
                forecast_result.get("model_confidence", forecast_result.get("confidence", 0.0))
            ),
            "heuristic_confidence": float(heuristic_confidence["score"]),
            "confidence_components": confidence["components"],
        },
    )

    return format_agent_output(
        [insight],
        metadata=build_metadata(
            "forecast",
            sector=sector,
            country=resolved_country,
            method=str(forecast_result["method"]),
            data_quality=time_series_payload.get("data_quality"),
            metric=metric,
            periods=periods,
            horizon=horizon_text,
            history_years=len(history_values),
            model_scores=forecast_result.get("model_scores", {}),
            **_scope_metadata(product_info),
        ),
    )



def _strengths(graph: nx.DiGraph) -> tuple[Dict[str, float], Dict[str, float]]:
    """Exports and imports per country in a trade graph."""
    exports: Dict[str, float] = {node: 0.0 for node in graph.nodes}
    imports: Dict[str, float] = {node: 0.0 for node in graph.nodes}
    for exporter, importer, data in graph.edges(data=True):
        weight = float(data.get("weight", 0.0))
        exports[exporter] += weight
        imports[importer] += weight
    return exports, imports



def _optional_graph(data_path: str, year: int, sector: str, product: Optional[str]) -> Optional[nx.DiGraph]:
    """A comparison year's graph, or None when that year is not available."""
    try:
        frame = load_trade_data(data_path, year=year, sector=sector, product=product)
        return build_trade_graph(frame, sector=sector)
    except (ValueError, FileNotFoundError):
        return None



def _growth(current: float, previous: Optional[float]) -> Optional[float]:
    if previous is None or previous <= 0:
        return None
    return float(current / previous - 1.0)



def _cagr(current: float, past: Optional[float], years: int) -> Optional[float]:
    if past is None or past <= 0 or current <= 0 or years <= 0:
        return None
    return float((current / past) ** (1.0 / years) - 1.0)



def _herfindahl_shares(values: Dict[str, float]) -> float:
    total = float(sum(values.values()))
    if total <= 0:
        return 0.0
    return float(sum((value / total) ** 2 for value in values.values()))



def _top_partners(graph: nx.DiGraph, country: str, role: str, limit: int = 5) -> List[dict]:
    """A country's largest buyers (when exporting) or suppliers (when importing)."""
    edges = graph.out_edges(country, data=True) if role == "exporter" else graph.in_edges(country, data=True)
    flows = {
        (target if role == "exporter" else source): float(data.get("weight", 0.0))
        for source, target, data in edges
    }
    total = float(sum(flows.values()))
    ranked = sorted(flows.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        {
            "country": name,
            "iso3": _iso3(name),
            "value": value,
            "share": value / total if total else 0.0,
        }
        for name, value in ranked
    ]



def _execute_market_query(
    data_path: str,
    graph: nx.DiGraph,
    snapshot_year: int,
    country: Optional[str],
    limit: int,
    sector: str,
    product_info: Optional[dict],
    data_quality: dict | None,
) -> dict:
    """Who supplies and who buys a sector or product, and how concentrated it is."""
    scope_label = _scope_label(sector, product_info)
    product = product_info["code"] if product_info else None
    exports, imports = _strengths(graph)
    world = float(sum(exports.values()))
    if world <= 0:
        raise ValueError(f"No trade is recorded for {scope_label} in {snapshot_year}.")

    previous = _optional_graph(data_path, snapshot_year - 1, sector, product)
    five_back = _optional_graph(data_path, snapshot_year - 5, sector, product)
    prev_exports, prev_imports = _strengths(previous) if previous is not None else ({}, {})
    old_exports, old_imports = _strengths(five_back) if five_back is not None else ({}, {})
    prev_world = float(sum(prev_exports.values())) if previous is not None else None

    exporters = sorted(((c, v) for c, v in exports.items() if v > 0), key=lambda item: item[1], reverse=True)
    importers = sorted(((c, v) for c, v in imports.items() if v > 0), key=lambda item: item[1], reverse=True)
    rank_of = {
        "exporter": {name: index + 1 for index, (name, _) in enumerate(exporters)},
        "importer": {name: index + 1 for index, (name, _) in enumerate(importers)},
    }
    exporter_hhi = _herfindahl_shares(dict(exporters))
    importer_hhi = _herfindahl_shares(dict(importers))
    top3_exporters = float(sum(value for _, value in exporters[:3]) / world)
    top3_importers = float(sum(value for _, value in importers[:3]) / world)

    def build(name: str, role: str) -> dict:
        values, prev_values, old_values = (
            (exports, prev_exports, old_exports) if role == "exporter" else (imports, prev_imports, old_imports)
        )
        value = float(values.get(name, 0.0))
        share = value / world
        rank = rank_of[role].get(name)
        count = len(exporters if role == "exporter" else importers)
        growth_1y = _growth(value, prev_values.get(name)) if previous is not None else None
        cagr_5y = _cagr(value, old_values.get(name), 5) if five_back is not None else None
        partners = _top_partners(graph, name, role)
        confidence = build_confidence_assessment(
            data_quality=data_quality, graph=graph, country=name, propagation_steps=1
        )
        growth_clause = ""
        if growth_1y is not None:
            growth_clause = f", {'up' if growth_1y >= 0 else 'down'} {abs(growth_1y):.1%} on {snapshot_year - 1}"
        partner_text = format_partner_list(
            [f"{p['country']} {p['share']:.0%}" for p in partners[:3]]
        )
        if value <= 0:
            verb = "exports" if role == "exporter" else "imports"
            claim = f"{scope_label} in year {snapshot_year}: {name} recorded no {verb}."
        elif role == "exporter":
            claim = (
                f"{scope_label} in year {snapshot_year}: {name} is exporter #{rank} of {count}, "
                f"shipping {format_usd(value)} ({share:.1%} of world trade){growth_clause}. "
                f"Main buyers: {partner_text}."
            )
        else:
            claim = (
                f"{scope_label} in year {snapshot_year}: {name} is importer #{rank} of {count}, "
                f"buying {format_usd(value)} ({share:.1%} of world trade){growth_clause}. "
                f"Main suppliers: {partner_text}."
            )
        partner_values = {p["country"]: p["value"] for p in _top_partners(graph, name, role, limit=500)}
        return build_insight(
            entity_iso3=_iso3(name),
            entity_name=name,
            claim=f"{claim} {confidence['reason']}",
            score=float(share),
            confidence=confidence["score"],
            reason=confidence["reason"],
            evidence={
                **_scope_evidence(sector, product_info),
                "role": role,
                "rank": rank,
                "ranked": count,
                "value": value,
                "world_share": float(share),
                "previous_value": float(prev_values.get(name, 0.0)) if previous is not None else None,
                "growth_1y": growth_1y,
                "cagr_5y": cagr_5y,
                "partners": partners,
                "partner_count": len(partner_values),
                "partner_concentration": _herfindahl_shares(partner_values),
                "confidence_components": confidence["components"],
            },
        )

    if country:
        if country not in graph:
            raise ValueError(f"{country} has no recorded trade in {scope_label} in {snapshot_year}.")
        insights = [build(country, "exporter"), build(country, "importer")]
    else:
        insights = [build(name, "exporter") for name, _ in exporters[:limit]]
        insights += [build(name, "importer") for name, _ in importers[:limit]]

    if product_info:
        world_series = product_store.product_world_series(cache_directory(), product_info["code"])
    elif cache_ready():
        world_series = baci_cache.world_trade_series(cache_directory(), sector)
    else:
        world_series = []

    return format_agent_output(
        insights,
        metadata=build_metadata(
            "market",
            sector=sector,
            year=snapshot_year,
            country=country,
            method="exporter and importer market shares with Herfindahl concentration",
            data_quality=data_quality,
            world_trade=world,
            world_trade_previous=prev_world,
            world_growth_1y=_growth(world, prev_world),
            exporter_count=len(exporters),
            importer_count=len(importers),
            exporter_concentration=exporter_hhi,
            importer_concentration=importer_hhi,
            top3_exporter_share=top3_exporters,
            top3_importer_share=top3_importers,
            world_trade_series=world_series,
            **_scope_metadata(product_info),
        ),
    )



def _execute_bilateral_query(
    data_path: str,
    query: dict,
    sector: str,
    product_info: Optional[dict],
    snapshot_year: int,
    country: Optional[str],
    partner: Optional[str],
) -> dict:
    """How two countries trade with each other, who needs whom, and where it is heading."""
    if not country or not partner:
        raise ValueError("Bilateral queries need both a 'country' and a 'partner'.")
    if country == partner:
        raise ValueError("Bilateral queries need two different countries.")
    if not cache_ready():
        raise ValueError("Bilateral history needs the parquet cache (scripts/build_cache.py).")

    cache_dir = cache_directory()
    product = product_info["code"] if product_info else None
    scope_label = _scope_label(sector, product_info)
    periods = max(1, int(query.get("periods") or 3))
    model = str(query.get("forecast_model") or "auto").strip().lower()

    snapshot = load_trade_data(data_path, year=snapshot_year, sector=sector, product=product)
    graph = build_trade_graph(snapshot, sector=sector)
    data_quality = snapshot.attrs.get("data_quality")
    exports, imports = _strengths(graph)
    totals = country_totals(graph)

    def flow(source: str, target: str) -> float:
        return float(graph[source][target]["weight"]) if graph.has_edge(source, target) else 0.0

    a_to_b, b_to_a = flow(country, partner), flow(partner, country)
    two_way = a_to_b + b_to_a
    total_a, total_b = float(totals.get(country, 0.0)), float(totals.get(partner, 0.0))
    dependence_a = two_way / total_a if total_a else 0.0
    dependence_b = two_way / total_b if total_b else 0.0

    pair_values = bilateral_totals(graph)

    def partner_rank(subject: str, other: str) -> tuple[Optional[int], int]:
        ranked = sorted(
            ((b if a == subject else a, value) for (a, b), value in pair_values.items() if subject in (a, b)),
            key=lambda item: item[1],
            reverse=True,
        )
        names = [name for name, _ in ranked]
        return (names.index(other) + 1 if other in names else None), len(names)

    rank_a, partners_a = partner_rank(country, partner)
    rank_b, partners_b = partner_rank(partner, country)
    holder, exposed = (country, partner) if dependence_a < dependence_b else (partner, country)

    # History across every year, then growth anchored at the snapshot year.
    if product:
        history = product_store.load_product_pair_series(cache_dir, product, country, partner)
    else:
        history = baci_cache.load_pair_series(cache_dir, country, partner, sector)
    history = history.sort_values("year").reset_index(drop=True)
    history["total"] = history["a_to_b"] + history["b_to_a"]
    by_year = history.set_index("year")

    def past(column: str, years_back: int) -> Optional[float]:
        year = snapshot_year - years_back
        return float(by_year.at[year, column]) if year in by_year.index else None

    growth = {
        "a_to_b_1y": _growth(a_to_b, past("a_to_b", 1)),
        "b_to_a_1y": _growth(b_to_a, past("b_to_a", 1)),
        "total_1y": _growth(two_way, past("total", 1)),
        "a_to_b_cagr_5y": _cagr(a_to_b, past("a_to_b", 5), 5),
        "b_to_a_cagr_5y": _cagr(b_to_a, past("b_to_a", 5), 5),
        "total_cagr_5y": _cagr(two_way, past("total", 5), 5),
        "total_cagr_10y": _cagr(two_way, past("total", 10), 10),
    }

    # Forecast each direction from its full history; the total is their sum,
    # so the three projections always agree with each other.
    series = pd.DataFrame(
        {
            "year": history["year"],
            "exports": history["a_to_b"],
            "imports": history["b_to_a"],
        }
    )
    outward = forecast_metric_from_series(series, country=country, metric="exports", periods=periods, model=model)
    inward = forecast_metric_from_series(series, country=country, metric="imports", periods=periods, model=model)
    forecast_values = [
        {
            "year": int(out["year"]),
            "a_to_b": float(out["predicted_value"]),
            "b_to_a": float(back["predicted_value"]),
            "total": float(out["predicted_value"]) + float(back["predicted_value"]),
        }
        for out, back in zip(outward["forecast"], inward["forecast"])
    ]
    latest_total = float(history["total"].iloc[-1]) if not history.empty else 0.0
    final_total = forecast_values[-1]["total"] if forecast_values else latest_total
    projected_change = (final_total - latest_total) / latest_total if latest_total else 0.0
    weights = (float(history["a_to_b"].iloc[-1]), float(history["b_to_a"].iloc[-1])) if not history.empty else (1.0, 1.0)
    weight_total = sum(weights) or 1.0
    model_confidence = (
        float(outward.get("model_confidence", 0.0)) * weights[0]
        + float(inward.get("model_confidence", 0.0)) * weights[1]
    ) / weight_total

    sectors: List[dict] = []
    if product is None:
        breakdown = baci_cache.load_pair_sectors(cache_dir, snapshot_year, country, partner)
        breakdown = breakdown[breakdown["sector"] != "all"]
        for row in breakdown.itertuples(index=False):
            if row.sector not in SECTOR_DEFINITIONS:
                continue
            sectors.append(
                {
                    "sector": str(row.sector),
                    "label": sector_display_label(row.sector),
                    "a_to_b": float(row.a_to_b),
                    "b_to_a": float(row.b_to_a),
                }
            )
        all_a = sum(item["a_to_b"] for item in sectors) or 1.0
        all_b = sum(item["b_to_a"] for item in sectors) or 1.0
        for item in sectors:
            item["share_a_to_b"] = item["a_to_b"] / all_a
            item["share_b_to_a"] = item["b_to_a"] / all_b
        sectors.sort(key=lambda item: item["a_to_b"] + item["b_to_a"], reverse=True)

    top_products = None
    if product_data_ready():
        try:
            top_products = product_store.top_products_between(
                cache_dir, snapshot_year, country, partner, code=product, sector=sector
            )
        except ValueError:
            top_products = None

    balance = a_to_b - b_to_a
    if two_way <= 0:
        claim_a = (
            f"{scope_label} in year {snapshot_year}: {country} and {partner} recorded no trade "
            f"with each other."
        )
    else:
        position = "surplus" if balance >= 0 else "deficit"
        claim_a = (
            f"{scope_label} in year {snapshot_year}: {country} exported {format_usd(a_to_b)} to "
            f"{partner} and imported {format_usd(b_to_a)} from it, a {position} of "
            f"{format_usd(abs(balance))}. {partner} is {country}'s #{rank_a} trade partner "
            f"({dependence_a:.1%} of its trade); {country} is {partner}'s #{rank_b} "
            f"({dependence_b:.1%}), so {holder} is the less dependent side."
        )
        if growth["total_cagr_5y"] is not None:
            direction = "grew" if growth["total_cagr_5y"] >= 0 else "shrank"
            claim_a += (
                f" Two-way trade {direction} {abs(growth['total_cagr_5y']):.1%} a year over "
                f"{snapshot_year - 5}-{snapshot_year}."
            )
        if forecast_values:
            claim_a += (
                f" It is projected at {format_usd(final_total)} by {forecast_values[-1]['year']} "
                f"({projected_change:+.1%} on {int(history['year'].iloc[-1])})."
            )

    claim_b = (
        f"{scope_label} in year {snapshot_year}: {partner} exported {format_usd(b_to_a)} to "
        f"{country} and imported {format_usd(a_to_b)} from it. {country} is {partner}'s "
        f"#{rank_b} trade partner at {dependence_b:.1%} of its trade."
        if two_way > 0
        else claim_a
    )

    confidence_a = build_confidence_assessment(data_quality=data_quality, graph=graph, country=country, propagation_steps=1) \
        if country in graph else {"score": 0.3, "reason": f"{country} has no trade in this scope.", "components": {}}
    confidence_b = build_confidence_assessment(data_quality=data_quality, graph=graph, country=partner, propagation_steps=1) \
        if partner in graph else {"score": 0.3, "reason": f"{partner} has no trade in this scope.", "components": {}}

    shared = {
        **_scope_evidence(sector, product_info),
        "pair": [_iso3(country) or country, _iso3(partner) or partner],
        "leverage_holder": holder,
        "leverage_holder_iso3": _iso3(holder),
        "exposed_country": exposed,
        "asymmetry": float(abs(dependence_a - dependence_b)),
        "bilateral_trade": two_way,
    }
    insight_a = build_insight(
        entity_iso3=_iso3(country),
        entity_name=country,
        claim=f"{claim_a} {confidence_a['reason']}",
        score=float(dependence_a),
        confidence=confidence_a["score"],
        reason=confidence_a["reason"],
        evidence={
            **shared,
            "partner": partner,
            "partner_iso3": _iso3(partner),
            "exports_to_partner": a_to_b,
            "imports_from_partner": b_to_a,
            "trade_balance": balance,
            "dependence_on_partner": float(dependence_a),
            "partner_dependence": float(dependence_b),
            "share_of_exports": a_to_b / exports.get(country, 0.0) if exports.get(country) else 0.0,
            "share_of_imports": b_to_a / imports.get(country, 0.0) if imports.get(country) else 0.0,
            "partner_share_of_exports": b_to_a / exports.get(partner, 0.0) if exports.get(partner) else 0.0,
            "partner_share_of_imports": a_to_b / imports.get(partner, 0.0) if imports.get(partner) else 0.0,
            "partner_rank": rank_a,
            "partner_count": partners_a,
            "rank_with_partner": rank_b,
            "partner_partner_count": partners_b,
            "growth": growth,
            "history": [
                {"year": int(row.year), "a_to_b": float(row.a_to_b), "b_to_a": float(row.b_to_a)}
                for row in history.itertuples(index=False)
            ],
            "forecast": {
                "periods": periods,
                "method_a_to_b": outward["method"],
                "method_b_to_a": inward["method"],
                "model_confidence": float(model_confidence),
                "projected_change": float(projected_change),
                "values": forecast_values,
            },
            "sectors": sectors,
            "top_products": top_products,
            "confidence_components": confidence_a["components"],
        },
    )
    insight_b = build_insight(
        entity_iso3=_iso3(partner),
        entity_name=partner,
        claim=f"{claim_b} {confidence_b['reason']}",
        score=float(dependence_b),
        confidence=confidence_b["score"],
        reason=confidence_b["reason"],
        evidence={
            **shared,
            "partner": country,
            "partner_iso3": _iso3(country),
            "exports_to_partner": b_to_a,
            "imports_from_partner": a_to_b,
            "trade_balance": -balance,
            "dependence_on_partner": float(dependence_b),
            "partner_dependence": float(dependence_a),
            "partner_rank": rank_b,
            "partner_count": partners_b,
            "confidence_components": confidence_b["components"],
        },
    )

    return format_agent_output(
        [insight_a, insight_b],
        metadata=build_metadata(
            "bilateral",
            sector=sector,
            year=snapshot_year,
            country=country,
            method="bilateral flows, dependence asymmetry, and a per-direction forecast",
            data_quality=data_quality,
            partner=partner,
            forecast_method=f"{outward['method']} / {inward['method']}",
            periods=periods,
            history_years=int(len(history)),
            **_scope_metadata(product_info),
        ),
    )



def _resolve_snapshot_year(data_path: str, year: object, product_info: Optional[dict] = None) -> int:
    """Resolve the requested year or fall back to the latest available year."""
    if year is not None:
        return int(year)
    if product_info:
        return max(product_store.product_years(cache_directory()))
    return latest_year(data_path)



def _resolve_country_name(data_path: str, country: object) -> Optional[str]:
    """Turn a name, ISO code, or numeric code into the canonical country name.

    Returns None when no country was supplied, which the ranked query paths
    treat as "score the whole network".
    """
    if not country:
        return None
    if not can_resolve_countries(data_path):
        return str(country)
    _, resolved = resolve_baci_country(data_path, str(country))
    return resolved



def _iso3(name: object) -> Optional[str]:
    """Resolve an entity name to the ISO3 code the four agents join on.

    Returns None rather than guessing when the name is not a country the
    crosswalk knows, so the fusion layer skips the row instead of joining it
    against the wrong entity.
    """
    if not name or not cache_ready():
        return None
    return baci_cache.iso3_for(cache_directory(), str(name))



def _precomputed_centrality(year: int, sector: str):
    """Fetch precomputed centrality when the cache has it, else None.

    Returning None is not an error: the risk analyzer falls back to computing
    centrality live, which is what happens on a cache-free deployment.
    """
    if not cache_ready():
        return None
    return baci_cache.load_centrality(cache_directory(), year=year, sector=sector)



def _economics_available() -> bool:
    """Return True when GDP and population enrichment can be applied."""
    return cache_ready() and metadata_available(cache_directory())



def _enrich_with_economics(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """Add GDP-relative exposure when country metadata has been fetched."""
    if not _economics_available():
        return frame

    try:
        cache_dir = cache_directory()
        return attach_economic_exposure(
            impact=frame,
            features=features,
            metadata=load_metadata(cache_dir),
            country_codes=baci_cache.load_countries(cache_dir),
            year=year,
        )
    except (ValueError, KeyError):
        # Enrichment is a bonus, never a reason to fail a query.
        return frame



def _fragility_reason(record: dict) -> str:
    """Name the factor limiting confidence in a fragility score."""
    supplier_count = int(record.get("supplier_count", 0))
    if supplier_count <= 3:
        return (
            "Confidence is most sensitive to the very small number of suppliers this "
            "score is computed from."
        )
    if supplier_count < 20:
        return "Confidence is most sensitive to the limited supplier base observed for this sector."
    return "Confidence is supported by a broad observed supplier base for this sector."



def _fragility_confidence(record: dict) -> float:
    """Confidence in a fragility score, driven by how much evidence supports it.

    A score computed from three supplier relationships is a weaker claim than
    one computed from eighty, so supplier count is the dominant term.
    """
    supplier_count = int(record.get("supplier_count", 0))
    coverage = min(1.0, supplier_count / 20.0)
    global_pool = int(record.get("global_supplier_pool", 0))
    breadth = min(1.0, global_pool / 100.0) if global_pool else 0.5
    return float(max(0.1, min(0.95, 0.35 + (0.45 * coverage) + (0.2 * breadth))))



def _safe_float(value: object) -> Optional[float]:
    """Convert a value to float, returning None for missing or unusable input."""
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(converted) else converted



def format_partner_list(partners: object) -> str:
    """Render a partner list for prose.

    Several BACI country names contain commas ("China, Hong Kong SAR"), so a
    comma-joined list is ambiguous to read. Semicolons cannot occur in the
    names and keep the boundaries unmistakable.
    """
    if partners is None:
        return "no major partners"
    items = [str(partner).strip() for partner in partners if str(partner).strip()]
    if not items:
        return "no major partners"
    return "; ".join(items)



def _describe_trend(projected_change: float) -> str:
    """Convert a projected change score into a simple trend label."""
    if projected_change > 0.01:
        return "increasing"
    if projected_change < -0.01:
        return "decreasing"
    return "stable"



def _sector_noun(sector: str) -> str:
    """A sector as it reads inside a sentence: "energy", "base metals"."""
    if sector in LEGACY_SECTORS:
        return sector
    return sector_display_label(sector).lower()



def format_usd(thousands: object) -> str:
    """Render a BACI value (thousand USD) as "$1.48B"."""
    try:
        value = float(thousands) * 1000.0
    except (TypeError, ValueError):
        return "n/a"
    if value != value:
        return "n/a"
    sign = "-" if value < 0 else ""
    value = abs(value)
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= threshold:
            return f"{sign}${value / threshold:.2f}{suffix}"
    return f"{sign}${value:.0f}"
