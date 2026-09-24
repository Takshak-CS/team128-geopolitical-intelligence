from __future__ import annotations

from models.analytics import SimilarityBundle


class VisualizationSerializer:
    def serialize_similarity(self, bundle: SimilarityBundle) -> dict:
        matrix = bundle.matrix.fillna(0)
        return {
            'metric': bundle.metric,
            'focal_country': bundle.focal_country,
            'countries': matrix.index.tolist(),
            'matrix': matrix.round(4).values.tolist(),
            'allies': bundle.allies,
            'opponents': bundle.opponents,
            'temporal_similarity': bundle.temporal_similarity,
        }

    def serialize_graph(self, payload: dict) -> dict:
        nodes = [
            {
                'id': node,
                'label': node,
                **attrs,
            }
            for node, attrs in payload['nodes']
        ]
        edges = [
            {
                'source': left,
                'target': right,
                **attrs,
            }
            for left, right, attrs in payload['edges']
        ]
        return {
            'nodes': nodes,
            'edges': edges,
            'allies': payload.get('allies', []),
            'opponents': payload.get('opponents', []),
        }

    def serialize_clusters(self, payload: dict) -> dict:
        return payload

    def serialize_timeline(self, country: str, series: list[dict]) -> dict:
        return {'country': country, 'series': series}
