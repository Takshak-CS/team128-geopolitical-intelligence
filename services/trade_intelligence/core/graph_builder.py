"""Graph construction utilities for trade data."""

from __future__ import annotations

import networkx as nx
import pandas as pd

from core.sector_mapper import filter_trade_frame_by_sector, normalize_sector



def build_trade_graph(data: pd.DataFrame, sector: str = "all") -> nx.DiGraph:
    """Build a directed weighted graph from trade records."""
    if data.empty:
        raise ValueError("Cannot build a graph from an empty trade dataset.")

    selected_sector = normalize_sector(sector)
    working = filter_trade_frame_by_sector(data, selected_sector) if "sector" in data.columns else data.copy()
    if working.empty:
        raise ValueError(f"Cannot build a graph for sector '{selected_sector}' from an empty trade dataset.")

    grouped = (
        working.groupby(["exporter", "importer"], as_index=False)["trade_value"]
        .sum()
        .sort_values(["exporter", "importer"])
    )

    graph = nx.DiGraph()
    for row in grouped.itertuples(index=False):
        graph.add_edge(row.exporter, row.importer, weight=float(row.trade_value))
    return graph



def build_graph_payload(graph: nx.DiGraph, max_edges: int = 150, focus=None) -> dict:
    """Convert a trade graph into a lightweight JSON payload for visualization.

    Without ``focus`` the payload is the strongest flows in the whole network.
    With it, only flows that touch a focus country compete for the edge budget,
    and every focus country is included even when it has no flow to show. A
    shock on a small exporter needs this: its flows never rank among the
    world's strongest, so a whole-network snapshot would not contain them.
    """
    if graph.number_of_nodes() == 0:
        return {"nodes": [], "edges": []}

    focus_nodes = {node for node in (focus or []) if node in graph}
    candidate_edges = graph.edges(data=True)
    if focus_nodes:
        candidate_edges = [
            edge for edge in candidate_edges if edge[0] in focus_nodes or edge[1] in focus_nodes
        ]

    capped_edges = max(1, int(max_edges))
    sorted_edges = sorted(
        candidate_edges,
        key=lambda edge: float(edge[2].get("weight", 0.0)),
        reverse=True,
    )[:capped_edges]

    node_totals = {
        node: float(
            sum(edge_data.get("weight", 0.0) for _, _, edge_data in graph.in_edges(node, data=True))
            + sum(edge_data.get("weight", 0.0) for _, _, edge_data in graph.out_edges(node, data=True))
        )
        for node in graph.nodes
    }

    visible_nodes = set(focus_nodes)
    edges = []
    for source, target, edge_data in sorted_edges:
        weight = float(edge_data.get("weight", 0.0))
        visible_nodes.add(source)
        visible_nodes.add(target)
        edges.append({"source": source, "target": target, "weight": weight})

    nodes = [
        {"id": node, "total_trade": node_totals.get(node, 0.0)}
        for node in sorted(visible_nodes, key=lambda item: node_totals.get(item, 0.0), reverse=True)
    ]

    return {"nodes": nodes, "edges": edges}
