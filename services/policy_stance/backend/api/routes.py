from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.services.session_manager import session_store
from data_processing.pipeline import GeopoliticalPipeline
from models.analytics import PolicyAnalyticsEngine
from models.gat_model import train_gat_embeddings
from models.graph_builder import CountryGraphBuilder
from visualization.serializers import VisualizationSerializer

router = APIRouter()
pipeline = GeopoliticalPipeline()
analytics = PolicyAnalyticsEngine()
graph_builder = CountryGraphBuilder()
serializer = VisualizationSerializer()


def get_session_or_404(session_id: str):
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f'Unknown session_id: {session_id}')
    return session


@router.post('/upload')
async def upload(files: list[UploadFile] = File(...), train_gnn: bool = False) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail='No files supplied')

    processed = await pipeline.process_uploads(files)
    session_store.set(processed.session_id, processed)

    response = {
        'session_id': processed.session_id,
        'datasets': processed.dataset_summaries,
        'pairings': processed.pairings,
        'preview': processed.preview_payload,
        'countries': processed.countries,
        'issues': processed.issue_types,
        'year_range': processed.year_range,
        'insights': analytics.generate_insight_summary(processed.normalized_df),
    }

    if train_gnn:
        try:
            graph_payload = graph_builder.build_graph_payload(processed.normalized_df)
            response['gnn'] = train_gat_embeddings(processed.normalized_df, graph_payload['raw_graph'])
        except Exception as exc:
            response['gnn_error'] = str(exc)

    return response


@router.get('/countries')
def countries(session_id: str) -> dict:
    session = get_session_or_404(session_id)
    return {
        'countries': session.countries,
        'issues': session.issue_types,
        'year_range': session.year_range,
        'sources': sorted(session.normalized_df['source_dataset'].dropna().astype(str).unique().tolist()) if 'source_dataset' in session.normalized_df else [],
    }


@router.get('/similarity')
def similarity(
    session_id: str,
    metric: str = Query(default='combined'),
    country: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    issue: Optional[str] = None,
) -> dict:
    session = get_session_or_404(session_id)
    filtered = analytics.filter_frame(session.normalized_df, start_year, end_year, issue)
    similarity_bundle = analytics.compute_similarity_bundle(filtered, metric=metric, focal_country=country)
    return serializer.serialize_similarity(similarity_bundle)


@router.get('/graph')
def graph(
    session_id: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    issue: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 120,
) -> dict:
    session = get_session_or_404(session_id)
    filtered = analytics.filter_frame(session.normalized_df, start_year, end_year, issue)
    payload = graph_builder.build_graph_payload(filtered, focal_country=country, max_edges=limit)
    return serializer.serialize_graph(payload)


@router.get('/clusters')
def clusters(
    session_id: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    issue: Optional[str] = None,
    method: str = Query(default='spectral'),
    k: int = Query(default=6, ge=2, le=15),
) -> dict:
    session = get_session_or_404(session_id)
    filtered = analytics.filter_frame(session.normalized_df, start_year, end_year, issue)
    cluster_bundle = analytics.cluster_countries(filtered, method=method, n_clusters=k)
    return serializer.serialize_clusters(cluster_bundle)


@router.get('/timeline')
def timeline(
    session_id: str,
    country: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    issue: Optional[str] = None,
) -> dict:
    session = get_session_or_404(session_id)
    filtered = analytics.filter_frame(session.normalized_df, start_year, end_year, issue)
    series = analytics.country_timeline(filtered, country)
    return serializer.serialize_timeline(country, series)


@router.get('/insights')
def insights(
    session_id: str,
    country: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    issue: Optional[str] = None,
) -> dict:
    session = get_session_or_404(session_id)
    filtered = analytics.filter_frame(session.normalized_df, start_year, end_year, issue)
    return analytics.generate_insight_summary(filtered, country=country)


@router.get('/gnn')
def gnn(
    session_id: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    issue: Optional[str] = None,
    epochs: int = Query(default=120, ge=20, le=500),
) -> dict:
    session = get_session_or_404(session_id)
    filtered = analytics.filter_frame(session.normalized_df, start_year, end_year, issue)
    graph_payload = graph_builder.build_graph_payload(filtered)
    return train_gat_embeddings(filtered, graph_payload['raw_graph'], epochs=epochs)
