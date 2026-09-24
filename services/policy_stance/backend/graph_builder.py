import json
import os
from collections import defaultdict
from itertools import combinations
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from backend.paths import TEMPORAL_OUTPUTS_DIR, ensure_directories, output_file


def _safe_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _serialize_value(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _graph_to_json(graph: nx.Graph) -> dict[str, Any]:
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        payload = {"id": node_id}
        payload.update({key: _serialize_value(value) for key, value in attrs.items()})
        nodes.append(payload)
    edges = []
    for source, target, attrs in graph.edges(data=True):
        payload = {"source": source, "target": target}
        payload.update({key: _serialize_value(value) for key, value in attrs.items()})
        edges.append(payload)
    return {"nodes": nodes, "edges": edges}


def _community_assignments(graph: nx.Graph) -> dict[Any, int]:
    try:
        import community as community_louvain  # type: ignore

        return community_louvain.best_partition(graph)
    except Exception:
        communities = list(nx.algorithms.community.greedy_modularity_communities(graph))
        assignments = {}
        for index, members in enumerate(communities):
            for node in members:
                assignments[node] = index
        return assignments


def _vote_pair_stats(votes_df: pd.DataFrame) -> tuple[dict[tuple[int, int], dict[str, float]], dict[tuple[int, int], dict[int, dict[str, float]]]]:
    pair_stats: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"same": 0.0, "total": 0.0})
    temporal_stats: dict[tuple[int, int], dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"same": 0.0, "total": 0.0}))
    if votes_df.empty:
        return pair_stats, temporal_stats

    grouped = votes_df.dropna(subset=["country_code", "year", "resolution"]).groupby(["year", "resolution"])
    for (year, _resolution), group in grouped:
        try:
            year_int = int(year)
        except (ValueError, TypeError):
            continue
        records = group[["country_code", "vote"]].dropna().drop_duplicates(subset=["country_code"], keep="last")
        values = records.to_dict(orient="records")
        for left, right in combinations(values, 2):
            try:
                pair = tuple(sorted((int(left["country_code"]), int(right["country_code"]))))
            except (ValueError, TypeError):
                continue
            pair_stats[pair]["total"] += 1.0
            temporal_stats[pair][year_int]["total"] += 1.0
            if left["vote"] == right["vote"]:
                pair_stats[pair]["same"] += 1.0
                temporal_stats[pair][year_int]["same"] += 1.0
    return pair_stats, temporal_stats


def _attach_graph_metrics(graph: nx.Graph) -> dict[str, Any]:
    if graph.number_of_nodes() == 0:
        return {"connected_components": [], "communities": {}}

    degree = nx.degree_centrality(graph)
    betweenness = nx.betweenness_centrality(graph)
    try:
        eigenvector = nx.eigenvector_centrality_numpy(graph)
    except Exception:
        eigenvector = {node: 0.0 for node in graph.nodes}
    try:
        pagerank = nx.pagerank(graph)
    except Exception:
        pagerank = {node: degree.get(node, 0.0) for node in graph.nodes}
    communities = _community_assignments(graph)
    components = [sorted(component) for component in nx.connected_components(graph)]

    for node in graph.nodes:
        graph.nodes[node]["degree_centrality"] = round(degree.get(node, 0.0), 6)
        graph.nodes[node]["betweenness_centrality"] = round(betweenness.get(node, 0.0), 6)
        graph.nodes[node]["eigenvector_centrality"] = round(eigenvector.get(node, 0.0), 6)
        graph.nodes[node]["pagerank"] = round(pagerank.get(node, 0.0), 6)
        graph.nodes[node]["community"] = communities.get(node, -1)

    return {
        "connected_components": components,
        "communities": communities,
    }


def _export_gexf(graph: nx.Graph) -> None:
    export_graph = nx.Graph()
    for node_id, attrs in graph.nodes(data=True):
        cleaned = {key: ", ".join(map(str, value)) if isinstance(value, list) else value for key, value in attrs.items()}
        export_graph.add_node(node_id, **cleaned)
    for source, target, attrs in graph.edges(data=True):
        cleaned = {key: ", ".join(map(str, value)) if isinstance(value, list) else value for key, value in attrs.items()}
        export_graph.add_edge(source, target, **cleaned)
    nx.write_gexf(export_graph, output_file("graph.gexf"))


def build_graphs(master_df: pd.DataFrame, votes_df: pd.DataFrame) -> dict[str, Any]:
    ensure_directories()
    # Defensive prefilter: ensure key columns have no NaN before any int() conversion
    if not master_df.empty:
        master_df = master_df.dropna(subset=['year']).copy()
        master_df['year'] = master_df['year'].astype(int)
    if not votes_df.empty:
        votes_df = votes_df.dropna(subset=['country_code', 'year', 'resolution']).copy()
        votes_df['year'] = votes_df['year'].astype(int)
    graph = nx.Graph()
    pair_vote_stats, temporal_vote_stats = _vote_pair_stats(votes_df)

    if not votes_df.empty:
        grouped_votes = votes_df.dropna(subset=['country_code', 'country_name']).groupby(['country_code', 'country_name'])['year'].agg(lambda values: sorted(set(int(value) for value in values if pd.notna(value))))
        for (country_code, country_name), years in grouped_votes.items():
            graph.add_node(int(country_code), name=str(country_name), gw_code=int(country_code), total_conflicts=0, total_deaths=0.0, active_years=set(years))

    if not master_df.empty:
        for _, row in master_df.iterrows():
            year = int(row["year"])
            for role in ["a", "b"]:
                country_code = row.get(f"country_{role}_code")
                country_name = row.get(f"country_{role}")
                if not country_code or not country_name or (isinstance(country_code, float) and pd.isna(country_code)):
                    continue
                graph.add_node(int(country_code), name=str(country_name), gw_code=int(country_code), total_conflicts=0, total_deaths=0.0, active_years=set())
                graph.nodes[int(country_code)]["active_years"].add(year)
                if row.get("relationship_type") == "conflict":
                    graph.nodes[int(country_code)]["total_conflicts"] += 1
                    graph.nodes[int(country_code)]["total_deaths"] += _safe_float(row.get("deaths"))

            left = row.get("country_a_code")
            right = row.get("country_b_code")
            if not left or not right:
                continue
            if isinstance(left, float) and pd.isna(left):
                continue
            if isinstance(right, float) and pd.isna(right):
                continue
            if int(left) == int(right):
                continue
            pair = tuple(sorted((int(left), int(right))))
            if not graph.has_edge(*pair):
                graph.add_edge(*pair, datasets=set(), years=set(), conflict_count=0, avg_intensity=0.0, total_deaths=0.0, agreements=0, un_agree_rate=0.0, issues=set(), relationship_type="neutral", _intensity_values=[])
            edge = graph.edges[pair]
            edge["datasets"].add(str(row.get("dataset")))
            edge["years"].add(year)
            if row.get("issue"):
                edge["issues"].update([item.strip() for item in str(row.get("issue")).split(",") if item.strip()])
            deaths = _safe_float(row.get("deaths"))
            intensity = _safe_float(row.get("intensity"))
            edge["total_deaths"] += deaths
            if intensity:
                edge["_intensity_values"].append(intensity)
            if row.get("relationship_type") == "conflict":
                edge["conflict_count"] += 1
                edge["relationship_type"] = "conflict"
            elif row.get("relationship_type") == "peace_partner":
                edge["agreements"] += 1
                if edge["relationship_type"] != "conflict":
                    edge["relationship_type"] = "peace_partner"

    for pair, stats in pair_vote_stats.items():
        rate = stats["same"] / stats["total"] if stats["total"] else 0.0
        if graph.has_edge(*pair):
            graph.edges[pair]["un_agree_rate"] = round(rate, 6)
            if graph.edges[pair]["relationship_type"] == "neutral":
                graph.edges[pair]["relationship_type"] = "ally" if rate >= 0.66 else "neutral"
        elif stats["total"] >= 5:
            years = sorted(temporal_vote_stats.get(pair, {}).keys())
            graph.add_edge(*pair, datasets=['un_votes_clean'], years=years, conflict_count=0, avg_intensity=0.0, total_deaths=0.0, agreements=0, un_agree_rate=round(rate, 6), issues=[], relationship_type='ally' if rate >= 0.66 else 'neutral', _intensity_values=[])

    for _, _, attrs in graph.edges(data=True):
        values = attrs.pop("_intensity_values", [])
        attrs["avg_intensity"] = round(float(np.mean(values)) if values else 0.0, 6)
        attrs["datasets"] = sorted(list(attrs["datasets"])) if isinstance(attrs["datasets"], set) else list(attrs["datasets"])
        attrs["years"] = sorted(list(attrs["years"])) if isinstance(attrs["years"], set) else list(attrs["years"])
        attrs["issues"] = sorted(list(attrs["issues"])) if isinstance(attrs["issues"], set) else list(attrs["issues"])

    for _, attrs in graph.nodes(data=True):
        attrs["active_years"] = sorted(list(attrs["active_years"]))
        attrs["total_deaths"] = round(attrs["total_deaths"], 2)

    metrics = _attach_graph_metrics(graph)

    temporal_graphs: dict[int, dict[str, Any]] = {}
    for year in range(1989, 2026):
        year_graph = nx.Graph()
        for node_id, attrs in graph.nodes(data=True):
            if year in attrs.get("active_years", []):
                year_graph.add_node(node_id, **attrs)
        for source, target, attrs in graph.edges(data=True):
            if year in attrs.get("years", []):
                year_graph.add_node(source, **graph.nodes[source])
                year_graph.add_node(target, **graph.nodes[target])
                year_graph.add_edge(source, target, **attrs)
        _attach_graph_metrics(year_graph)
        temporal_json = _graph_to_json(year_graph)
        temporal_graphs[year] = temporal_json
        with open(os.path.join(TEMPORAL_OUTPUTS_DIR, f"{year}.json"), "w", encoding="utf-8") as handle:
            json.dump(temporal_json, handle, indent=2, ensure_ascii=False)

    graph_json = _graph_to_json(graph)
    graph_json["metrics"] = {"connected_components": metrics["connected_components"], "communities": {str(node): community for node, community in metrics["communities"].items()}}

    with open(output_file("graph_data.json"), "w", encoding="utf-8") as handle:
        json.dump(graph_json, handle, indent=2, ensure_ascii=False)

    _export_gexf(graph)

    return {"graph": graph, "graph_json": graph_json, "temporal_graphs": temporal_graphs, "vote_pair_stats": pair_vote_stats, "temporal_vote_stats": temporal_vote_stats}
