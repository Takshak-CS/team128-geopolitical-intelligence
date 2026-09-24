import json
import os
from collections import Counter, defaultdict
from typing import Any

MPL_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'outputs', '.mplconfig')
os.makedirs(MPL_CONFIG_DIR, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', MPL_CONFIG_DIR)

import matplotlib
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.paths import ensure_directories, output_file


def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _top_country_codes(graph: nx.Graph, limit: int = 80) -> list[int]:
    ranked = sorted(graph.nodes(data=True), key=lambda item: (item[1].get("degree_centrality", 0.0), item[1].get("total_conflicts", 0)), reverse=True)
    return [node for node, _ in ranked[:limit]]


def _country_feature_matrix(graph: nx.Graph, master_df: pd.DataFrame, votes_df: pd.DataFrame) -> tuple[list[int], list[str], np.ndarray]:
    node_ids = sorted(graph.nodes())
    node_names = [graph.nodes[node]["name"] for node in node_ids]
    issue_counter: dict[int, Counter] = defaultdict(Counter)
    for _, row in master_df.iterrows():
        for code_column in ["country_a_code", "country_b_code"]:
            code = row.get(code_column)
            if code is None or (isinstance(code, float) and pd.isna(code)):
                continue
            for issue in [item.strip() for item in str(row.get("issue", "")).split(",") if item.strip()]:
                try:
                    issue_counter[int(code)][issue] += 1
                except (ValueError, TypeError):
                    continue

    all_issues = sorted({issue for counter in issue_counter.values() for issue in counter.keys()})
    issue_index = {issue: idx for idx, issue in enumerate(all_issues)}
    issue_matrix = np.zeros((len(node_ids), len(all_issues)), dtype=float)
    for row_index, node_id in enumerate(node_ids):
        for issue, count in issue_counter.get(node_id, {}).items():
            issue_matrix[row_index, issue_index[issue]] = count

    metrics = []
    for node_id in node_ids:
        attrs = graph.nodes[node_id]
        agreement_sum = sum(graph.edges[edge].get("agreements", 0) for edge in graph.edges(node_id))
        metrics.append([attrs.get("total_conflicts", 0), attrs.get("total_deaths", 0.0), agreement_sum, attrs.get("degree_centrality", 0.0), attrs.get("pagerank", 0.0)])
    metrics_matrix = np.array(metrics, dtype=float)
    if metrics_matrix.size:
        maximums = metrics_matrix.max(axis=0)
        maximums[maximums == 0] = 1.0
        metrics_matrix = metrics_matrix / maximums

    vote_matrix = np.zeros((len(node_ids), 0), dtype=float)
    if not votes_df.empty:
        pivot = votes_df.pivot_table(index="country_code", columns="resolution", values="vote_numeric", aggfunc="last", fill_value=0.0)
        if not pivot.empty:
            vote_matrix = pivot.reindex(node_ids).fillna(0.0).to_numpy(dtype=float)

    full_matrix = np.hstack([issue_matrix, metrics_matrix, vote_matrix]) if len(node_ids) else np.zeros((0, 0))
    return node_ids, node_names, full_matrix


def _cosine_similarity(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return np.zeros((0, 0))
    normalized = _normalize_matrix(matrix)
    return normalized @ normalized.T


def _tokenize(text: str) -> list[str]:
    tokens = []
    for raw in str(text).lower().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if len(cleaned) >= 3:
            tokens.append(cleaned)
    return tokens


def _tfidf_matrix(texts: list[str], vocab_limit: int = 300) -> tuple[np.ndarray, list[str]]:
    tokenized = [_tokenize(text) for text in texts]
    frequency = Counter(token for doc in tokenized for token in set(doc))
    vocab = [token for token, _count in frequency.most_common(vocab_limit)]
    vocab_index = {token: idx for idx, token in enumerate(vocab)}
    matrix = np.zeros((len(texts), len(vocab)), dtype=float)
    for row_index, doc in enumerate(tokenized):
        counts = Counter(doc)
        for token, count in counts.items():
            if token in vocab_index:
                matrix[row_index, vocab_index[token]] = count
    df = np.count_nonzero(matrix > 0, axis=0)
    idf = np.log((1 + len(texts)) / (1 + df)) + 1
    matrix = matrix * idf
    return _normalize_matrix(matrix), vocab


def _kmeans(matrix: np.ndarray, k: int, iterations: int = 25) -> np.ndarray:
    if len(matrix) == 0:
        return np.array([], dtype=int)
    rng = np.random.default_rng(42)
    if len(matrix) < k:
        k = max(1, len(matrix))
    centers = matrix[rng.choice(len(matrix), size=k, replace=False)]
    labels = np.zeros(len(matrix), dtype=int)
    for _ in range(iterations):
        distances = np.linalg.norm(matrix[:, None, :] - centers[None, :, :], axis=2)
        labels = distances.argmin(axis=1)
        updated = []
        for cluster_id in range(k):
            members = matrix[labels == cluster_id]
            updated.append(members.mean(axis=0) if len(members) else centers[cluster_id])
        centers = np.vstack(updated)
    return labels


def _pca(matrix: np.ndarray, dimensions: int) -> np.ndarray:
    if matrix.size == 0:
        return np.zeros((len(matrix), dimensions))
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    try:
        u, s, _vt = np.linalg.svd(centered, full_matrices=False)
        embedding = u[:, :dimensions] * s[:dimensions]
    except Exception:
        embedding = centered[:, :dimensions]
    if embedding.shape[1] < dimensions:
        padding = np.zeros((embedding.shape[0], dimensions - embedding.shape[1]))
        embedding = np.hstack([embedding, padding])
    return embedding


def _random_walk_embeddings(graph: nx.Graph, dimensions: int = 16, walks_per_node: int = 8, walk_length: int = 12) -> np.ndarray:
    if graph.number_of_nodes() == 0:
        return np.zeros((0, dimensions))
    rng = np.random.default_rng(42)
    nodes = list(graph.nodes())
    index = {node: idx for idx, node in enumerate(nodes)}
    co_occurrence = np.zeros((len(nodes), len(nodes)), dtype=float)
    neighbors_cache = {candidate: list(graph.neighbors(candidate)) for candidate in nodes}

    for node in nodes:
        for _ in range(walks_per_node):
            walk = [node]
            current = node
            for _ in range(walk_length - 1):
                neighbors = neighbors_cache.get(current) or []
                if not neighbors:
                    break
                current = neighbors[rng.integers(0, len(neighbors))]
                walk.append(current)
            for position, source in enumerate(walk):
                source_index = index[source]
                for target in walk[max(0, position - 2): position + 3]:
                    target_index = index[target]
                    co_occurrence[source_index, target_index] += 1.0

    return _pca(co_occurrence, dimensions)


def _graph_attention_embeddings(graph: nx.Graph, votes_df: pd.DataFrame) -> tuple[dict[str, list[float]], dict[str, list[float]], str]:
    node_ids = sorted(graph.nodes())
    node_names = [graph.nodes[node]["name"] for node in node_ids]
    if not node_ids:
        return {}, {}, "empty"

    vote_matrix = np.zeros((len(node_ids), 0), dtype=float)
    if not votes_df.empty:
        pivot = votes_df.pivot_table(index="country_code", columns="resolution", values="vote_numeric", aggfunc="last", fill_value=0.0)
        vote_matrix = pivot.reindex(node_ids).fillna(0.0).to_numpy(dtype=float)
    vote_pca = _pca(vote_matrix, 20) if vote_matrix.size else np.zeros((len(node_ids), 20))

    feature_rows = []
    for node_id in node_ids:
        attrs = graph.nodes[node_id]
        feature_rows.append([attrs.get("degree_centrality", 0.0), attrs.get("betweenness_centrality", 0.0), attrs.get("total_deaths", 0.0)])
    base_features = np.array(feature_rows, dtype=float)
    if base_features.size:
        max_values = np.max(base_features, axis=0)
        max_values[max_values == 0] = 1.0
        base_features = base_features / max_values
    combined_features = np.hstack([base_features, vote_pca])

    try:
        import torch
        from torch import nn

        from torch_geometric.data import Data
        from torch_geometric.nn import GATConv

        node_index = {node: idx for idx, node in enumerate(node_ids)}
        edge_pairs = []
        for source, target in graph.edges():
            left = node_index[source]
            right = node_index[target]
            edge_pairs.append([left, right])
            edge_pairs.append([right, left])
        edge_index = torch.tensor(edge_pairs, dtype=torch.long).t().contiguous() if edge_pairs else torch.zeros((2, 0), dtype=torch.long)
        x = torch.tensor(combined_features, dtype=torch.float32)
        data = Data(x=x, edge_index=edge_index)

        class GATEncoder(nn.Module):
            def __init__(self, in_channels: int, hidden_channels: int = 16):
                super().__init__()
                self.conv1 = GATConv(in_channels, hidden_channels, heads=2, concat=True)
                self.conv2 = GATConv(hidden_channels * 2, 3, heads=1, concat=False)

            def forward(self, inputs):
                hidden = self.conv1(inputs.x, inputs.edge_index).relu()
                return self.conv2(hidden, inputs.edge_index)

        model = GATEncoder(x.shape[1])
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
        adjacency = torch.zeros((len(node_ids), len(node_ids)), dtype=torch.float32)
        for left, right in graph.edges():
            i = node_index[left]
            j = node_index[right]
            adjacency[i, j] = 1.0
            adjacency[j, i] = 1.0
        for _ in range(100):
            optimizer.zero_grad()
            encoded = model(data)
            reconstruction = encoded @ encoded.t()
            loss = ((reconstruction - adjacency) ** 2).mean()
            loss.backward()
            optimizer.step()
        embedding3 = model(data).detach().cpu().numpy()
        embedding2 = embedding3[:, :2]
        method = "torch_geometric_gat"
    except Exception:
        fallback = _random_walk_embeddings(graph, dimensions=16)
        if fallback.size == 0:
            fallback = combined_features
        embedding3 = _pca(fallback, 3)
        embedding2 = _pca(fallback, 2)
        method = "random_walk_fallback"

    embedding2_json = {name: [round(float(value), 6) for value in coords] for name, coords in zip(node_names, embedding2)}
    embedding3_json = {name: [round(float(value), 6) for value in coords] for name, coords in zip(node_names, embedding3)}
    return embedding2_json, embedding3_json, method


def _country_similarity(graph: nx.Graph, master_df: pd.DataFrame, votes_df: pd.DataFrame) -> dict[str, Any]:
    node_ids, node_names, matrix = _country_feature_matrix(graph, master_df, votes_df)
    similarity = _cosine_similarity(matrix)
    payload = {"countries": node_names, "codes": node_ids, "matrix": [[round(float(value), 6) for value in row] for row in similarity.tolist()]}
    with open(output_file("country_similarity.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return payload


def _issue_clusters(master_df: pd.DataFrame) -> dict[str, Any]:
    texts = []
    for _, row in master_df.iterrows():
        text = row.get("conflict_name") or row.get("issue")
        if text:
            texts.append(str(text))
    texts = sorted(dict.fromkeys(texts))
    tfidf, vocab = _tfidf_matrix(texts)
    labels = _kmeans(tfidf, 6)
    clusters: dict[int, list[str]] = defaultdict(list)
    for text, label in zip(texts, labels):
        clusters[int(label)].append(text)
    payload = {"clusters": [{"cluster": cluster_id, "items": sorted(items), "count": len(items)} for cluster_id, items in sorted(clusters.items())], "vocab": vocab[:40]}
    with open(output_file("issue_clusters.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return payload


def _temporal_agreement(graph: nx.Graph, temporal_vote_stats: dict[tuple[int, int], dict[int, dict[str, float]]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for (left, right), years in temporal_vote_stats.items():
        if len(years) < 2 or left not in graph.nodes or right not in graph.nodes:
            continue
        pair_name = f"{graph.nodes[left]['name']}-{graph.nodes[right]['name']}"
        payload[pair_name] = {str(year): round(stats["same"] / stats["total"], 4) for year, stats in sorted(years.items()) if stats["total"]}
    with open(output_file("temporal_agreement.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return payload


def _voting_gat_embeddings(votes_df: pd.DataFrame, country_names: list[str], dims: int = 8) -> dict[str, np.ndarray] | None:
    """
    Build a voting-similarity graph and run a Graph Attention Network on it.

    Unlike the conflict-graph GAT (which connects adversaries), this graph
    connects countries that vote alike at the UN — the correct structural
    signal for geopolitical alignment.

    Nodes:  sovereign countries present in both votes_df and country_names
    Edges:  pairs with UN vote agreement rate ≥ 0.55 (weighted by agreement)
    Features: PCA-20 of each country's vote vector across all resolutions
    Loss:   reconstruct the vote-agreement adjacency (not conflict adjacency)
    """
    if votes_df is None or votes_df.empty:
        return None
    try:
        vote_map = {'yes': 1, 'Y': 1, 'no': -1, 'N': -1, 'abstain': 0, 'A': 0}
        vdf = votes_df.copy()
        vdf['vote_num'] = vdf['vote'].map(vote_map).fillna(0)
        pivot = vdf.pivot_table(index='country_name', columns='resolution', values='vote_num', aggfunc='mean').fillna(0)
        pivot = pivot[pivot.index.isin(country_names)]
        if len(pivot) < 10:
            return None

        names = list(pivot.index)
        X = pivot.values.astype(float)
        # Normalise each country's vote vector
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        X_norm = X / norms
        # Node features: PCA-20 of vote vectors
        feat = _pca(X_norm, 20)

        # Build weighted vote-agreement adjacency
        agreement = X_norm @ X_norm.T          # cosine similarity matrix
        THRESHOLD = 0.55
        adj = np.where(agreement >= THRESHOLD, agreement, 0.0)
        np.fill_diagonal(adj, 0.0)

        try:
            import torch
            from torch import nn
            from torch_geometric.data import Data
            from torch_geometric.nn import GATConv

            n = len(names)
            rows, cols = np.where(adj > 0)
            edge_weights = adj[rows, cols]
            edge_index = torch.tensor(np.vstack([rows, cols]), dtype=torch.long)
            edge_attr = torch.tensor(edge_weights, dtype=torch.float32)
            x = torch.tensor(feat, dtype=torch.float32)
            data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
            adj_t = torch.tensor(adj, dtype=torch.float32)

            class VotingGAT(nn.Module):
                def __init__(self, in_ch: int, hidden: int = 32, out: int = 8):
                    super().__init__()
                    self.conv1 = GATConv(in_ch, hidden, heads=4, concat=True, dropout=0.1)
                    self.conv2 = GATConv(hidden * 4, out, heads=1, concat=False, dropout=0.1)
                    self.bn = nn.BatchNorm1d(hidden * 4)

                def forward(self, d):
                    h = self.conv1(d.x, d.edge_index).relu()
                    h = self.bn(h)
                    return self.conv2(h, d.edge_index)

            model = VotingGAT(feat.shape[1], hidden=32, out=dims)
            opt = torch.optim.Adam(model.parameters(), lr=0.005, weight_decay=1e-4)
            for epoch in range(200):
                model.train(); opt.zero_grad()
                emb = model(data)
                recon = torch.sigmoid(emb @ emb.t())
                loss = ((recon - adj_t) ** 2).mean()
                loss.backward(); opt.step()

            model.eval()
            with torch.no_grad():
                embeddings = model(data).numpy()
            return {name: embeddings[i] for i, name in enumerate(names)}

        except Exception:
            # PyG not available — fall back to spectral embedding on voting graph
            from scipy.sparse.linalg import eigsh
            from scipy.sparse import csr_matrix
            degree = adj.sum(axis=1)
            D_inv_sqrt = np.diag(1.0 / np.sqrt(np.where(degree > 0, degree, 1.0)))
            L_norm = np.eye(len(names)) - D_inv_sqrt @ adj @ D_inv_sqrt
            vals, vecs = np.linalg.eigh(L_norm)
            # Take the dims eigenvectors with SMALLEST eigenvalues (skip 0th trivial)
            emb = vecs[:, 1:dims + 1]
            return {name: emb[i] for i, name in enumerate(names)}
    except Exception:
        return None


def _alliance_blocs(graph: nx.Graph, votes_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """
    Derive alliance blocs from UN General Assembly voting patterns using
    anchor-similarity scoring — not raw K-Means clustering which conflates
    anti-Western votes with pro-China alignment.

    Method:
    1. Build a country × resolution vote matrix (1=yes, 0=abstain, -1=no)
    2. For each bloc, compute an average vote vector from its anchor countries
    3. Assign each country to the bloc whose anchor vector it is most similar to
       (cosine similarity)
    4. Fall back to geopolitical community rules for countries with no vote data
    """

    # Representative anchors per bloc — chosen for unambiguous geopolitical identity
    BLOC_ANCHORS: dict[str, list[str]] = {
        "Western Bloc":        ["USA", "UK", "France", "Germany", "Japan", "Australia", "Canada", "Netherlands"],
        "Russia+Allies":       ["Russia", "Belarus", "North Korea", "Syria"],
        "China-Centered Bloc": ["China", "Cambodia", "Laos"],
        "Non-Aligned":         ["India", "Brazil", "South Africa", "Indonesia", "Nigeria", "Egypt"],
    }

    country_to_bloc: dict[str, str] = {}

    # ── GAT on voting-similarity graph ───────────────────────────────────────
    graph_names = [attrs.get('name', '') for _, attrs in graph.nodes(data=True) if attrs.get('name')]
    gat_embeddings = _voting_gat_embeddings(votes_df, graph_names, dims=8)

    if gat_embeddings:
        # Build anchor embedding centroids in GAT space
        anchor_centroids: dict[str, np.ndarray] = {}
        for bloc, anchors in BLOC_ANCHORS.items():
            vecs = [gat_embeddings[a] for a in anchors if a in gat_embeddings]
            if vecs:
                anchor_centroids[bloc] = np.mean(vecs, axis=0)

        if len(anchor_centroids) >= 2:
            def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
                d = np.linalg.norm(a) * np.linalg.norm(b)
                return float(np.dot(a, b) / d) if d > 0 else 0.0

            for country, emb in gat_embeddings.items():
                scores = {bloc: cosine_sim(emb, cv) for bloc, cv in anchor_centroids.items()}
                country_to_bloc[country] = max(scores, key=scores.get)

    # ── Fallback for countries absent from UN vote data ───────────────────────
    # Use explicit geopolitical rules (treaties, alliances, UN groupings)
    FALLBACK_RULES: dict[str, str] = {
        # Western / NATO / EU / close US allies
        **{c: "Western Bloc" for c in [
            "USA", "UK", "France", "Germany", "Italy", "Spain", "Portugal", "Canada",
            "Australia", "New Zealand", "Japan", "South Korea", "Israel", "Netherlands",
            "Belgium", "Denmark", "Norway", "Sweden", "Finland", "Iceland", "Ireland",
            "Austria", "Switzerland", "Greece", "Poland", "Czech Republic", "Slovakia",
            "Hungary", "Romania", "Bulgaria", "Croatia", "Slovenia", "Estonia", "Latvia",
            "Lithuania", "Albania", "Montenegro", "North Macedonia", "Kosovo", "Malta", "Cyprus",
            "Luxembourg", "Turkey",
        ]},
        # Russia-led bloc (CSTO, close partners)
        **{c: "Russia+Allies" for c in [
            "Russia", "Belarus", "Syria", "Iran", "North Korea", "Cuba", "Nicaragua",
            "Venezuela", "Eritrea", "Mali", "Burkina Faso", "Central African Republic",
        ]},
        # China orbit (BRI partners, SCO, close economic ties)
        **{c: "China-Centered Bloc" for c in [
            "China", "Pakistan", "Cambodia", "Laos", "Myanmar", "Mongolia",
            "Uzbekistan", "Kazakhstan", "Tajikistan", "Kyrgyzstan", "Turkmenistan",
        ]},
    }
    all_graph_names = {attrs.get('name', '') for _, attrs in graph.nodes(data=True)}
    for name in all_graph_names:
        if name and name not in country_to_bloc:
            country_to_bloc[name] = FALLBACK_RULES.get(name, "Non-Aligned")

    from collections import defaultdict as _dd
    bloc_members: dict[str, list[str]] = _dd(list)
    for name, bloc in country_to_bloc.items():
        if name:
            bloc_members[bloc].append(name)
    blocs = [{"label": lbl, "members": sorted(mems)} for lbl, mems in bloc_members.items()]

    payload = {"country_to_bloc": country_to_bloc, "blocs": blocs}
    with open(output_file("alliance_blocs.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return payload


def _heatmaps(graph: nx.Graph, master_df: pd.DataFrame, votes_df: pd.DataFrame, similarity: dict[str, Any]) -> None:
    sns.set_theme(style="whitegrid")
    conflict_codes = _top_country_codes(graph, limit=40)

    if conflict_codes and not master_df.empty:
        intensity_rows = []
        for _, row in master_df.iterrows():
            for column in ["country_a_code", "country_b_code"]:
                code = row.get(column)
                if code in conflict_codes:
                    intensity_rows.append({"country": graph.nodes[int(code)]["name"], "year": int(row["year"]), "intensity": float(row.get("intensity") or 0.0)})
        conflict_df = pd.DataFrame(intensity_rows)
        if not conflict_df.empty:
            pivot = conflict_df.pivot_table(index="country", columns="year", values="intensity", aggfunc="sum", fill_value=0.0)
            plt.figure(figsize=(16, 9))
            sns.heatmap(pivot, cmap="YlOrRd")
            plt.title("Conflict Intensity by Country and Year")
            plt.tight_layout()
            plt.savefig(output_file("heatmap_conflict_intensity.png"), dpi=180)
            plt.close()

    if not votes_df.empty:
        top_resolutions = votes_df["resolution"].value_counts().head(50).index.tolist()
        vote_subset = votes_df[votes_df["resolution"].isin(top_resolutions)]
        pivot = vote_subset.pivot_table(index="country_name", columns="resolution", values="vote_numeric", aggfunc="last", fill_value=0.0).head(50)
        if not pivot.empty:
            plt.figure(figsize=(18, 10))
            sns.heatmap(pivot, cmap="coolwarm", center=0)
            plt.title("UN Voting Heatmap")
            plt.tight_layout()
            plt.savefig(output_file("heatmap_un_voting.png"), dpi=180)
            plt.close()

    similarity_matrix = np.array(similarity.get("matrix", []), dtype=float)
    similarity_countries = similarity.get("countries", [])
    if similarity_matrix.size:
        limit = min(50, len(similarity_countries))
        plt.figure(figsize=(14, 12))
        sns.heatmap(similarity_matrix[:limit, :limit], cmap="crest", xticklabels=similarity_countries[:limit], yticklabels=similarity_countries[:limit])
        plt.title("Country Similarity")
        plt.tight_layout()
        plt.savefig(output_file("heatmap_country_similarity.png"), dpi=180)
        plt.close()


def _chord_data(graph: nx.Graph) -> dict[str, Any]:
    links = []
    for source, target, attrs in graph.edges(data=True):
        weight = attrs.get("conflict_count", 0) or attrs.get("avg_intensity", 0.0)
        if weight <= 0:
            continue
        links.append({"source": graph.nodes[source]["name"], "target": graph.nodes[target]["name"], "value": round(float(weight), 4), "total_deaths": round(float(attrs.get("total_deaths", 0.0)), 2), "relationship_type": attrs.get("relationship_type", "neutral")})
    payload = {"links": links}
    with open(output_file("chord_data.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return payload


def run_ml_analysis(graph: nx.Graph, master_df: pd.DataFrame, votes_df: pd.DataFrame, temporal_vote_stats: dict[tuple[int, int], dict[int, dict[str, float]]]) -> dict[str, Any]:
    ensure_directories()
    similarity = _country_similarity(graph, master_df, votes_df)
    issue_clusters = _issue_clusters(master_df)
    temporal_agreement = _temporal_agreement(graph, temporal_vote_stats)
    embeddings_2d, embeddings_3d, embedding_method = _graph_attention_embeddings(graph, votes_df)
    with open(output_file("gat_embeddings_2d.json"), "w", encoding="utf-8") as handle:
        json.dump(embeddings_2d, handle, indent=2, ensure_ascii=False)
    with open(output_file("gat_embeddings_3d.json"), "w", encoding="utf-8") as handle:
        json.dump(embeddings_3d, handle, indent=2, ensure_ascii=False)
    alliance_blocs = _alliance_blocs(graph, votes_df)
    _heatmaps(graph, master_df, votes_df, similarity)
    chord_data = _chord_data(graph)
    return {
        "country_similarity": similarity,
        "issue_clusters": issue_clusters,
        "temporal_agreement": temporal_agreement,
        "embeddings_2d": embeddings_2d,
        "embeddings_3d": embeddings_3d,
        "embedding_method": embedding_method,
        "alliance_blocs": alliance_blocs,
        "chord_data": chord_data,
    }
