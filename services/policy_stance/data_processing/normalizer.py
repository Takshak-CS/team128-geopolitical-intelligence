from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd
import pycountry

from data_processing.schema_mapper import SchemaInference, SchemaMapper
from data_processing.types import DatasetArtifact


COUNTRY_ALIASES = {
    'usa': 'United States',
    'uk': 'United Kingdom',
    'uae': 'United Arab Emirates',
    'russia': 'Russian Federation',
    'turkiye': 'Turkey',
}


class DataNormalizer:
    def __init__(self) -> None:
        self.schema_mapper = SchemaMapper()

    def normalize_dataset(
        self,
        artifact: DatasetArtifact,
        merged_mappings: dict[str, dict[str, str]],
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        frame = artifact.frame.copy()
        inference = self.schema_mapper.infer(frame)
        artifact.schema = {
            'semantic_map': inference.semantic_map,
            'wide_country_columns': inference.wide_country_columns,
            'diagnostics': inference.diagnostics,
        }

        if inference.wide_country_columns:
            frame = self._wide_to_long(frame, inference)
            inference = self.schema_mapper.infer(frame)

        normalized = self._build_normalized_frame(frame, artifact.name, inference, merged_mappings)
        preview = normalized.head(8).fillna('').to_dict(orient='records')
        summary = {
            'dataset': artifact.name,
            'rows': int(len(frame)),
            'normalized_rows': int(len(normalized)),
            'semantic_map': inference.semantic_map,
        }
        return normalized, {'summary': summary, 'preview': preview, 'schema': artifact.schema}

    def _wide_to_long(self, frame: pd.DataFrame, inference: SchemaInference) -> pd.DataFrame:
        melted = frame.melt(id_vars=inference.metadata_columns, value_vars=inference.wide_country_columns, var_name='country_1', value_name='stance_value')
        return melted.dropna(subset=['stance_value'])

    def _build_normalized_frame(
        self,
        frame: pd.DataFrame,
        dataset_name: str,
        inference: SchemaInference,
        mappings: dict[str, dict[str, str]],
    ) -> pd.DataFrame:
        semantic = inference.semantic_map
        records: list[dict[str, Any]] = []
        issue_columns = self._detect_binary_issue_columns(frame, semantic)

        for row_index, (_, row) in enumerate(frame.iterrows()):
            year = self._coerce_year(row.get(semantic.get('year'))) if semantic.get('year') else None
            country_1 = self._resolve_country(row.get(semantic.get('country_1')), row.get(semantic.get('country_1_code')), mappings)
            country_2 = self._resolve_country(row.get(semantic.get('country_2')), row.get(semantic.get('country_2_code')), mappings)
            issue_type = self._resolve_issue(row, semantic, issue_columns)
            stance_value = self._resolve_stance_value(row, semantic, issue_columns)
            intensity = self._resolve_intensity(row, semantic)
            relation_score = self._relation_score(dataset_name, stance_value, intensity)

            if not country_1 and not country_2:
                continue

            records.append(
                {
                    'source_dataset': dataset_name,
                    'source_row_id': row_index,
                    'country_1': country_1,
                    'country_2': country_2,
                    'year': year,
                    'issue_type': issue_type,
                    'stance_value': stance_value,
                    'intensity': intensity,
                    'relation_score': relation_score,
                    'interaction_type': self._interaction_type(dataset_name, semantic, issue_columns),
                    'event_date': self._extract_date(row, semantic),
                    'extra_features': self._collect_extra_features(row, semantic, issue_columns),
                }
            )

        normalized = pd.DataFrame.from_records(records)
        if normalized.empty:
            normalized = pd.DataFrame(columns=['source_dataset', 'source_row_id', 'country_1', 'country_2', 'year', 'issue_type', 'stance_value', 'intensity', 'relation_score', 'interaction_type', 'event_date', 'extra_features'])
        normalized['country_1'] = normalized['country_1'].fillna('Unknown')
        normalized['issue_type'] = normalized['issue_type'].fillna('general')
        normalized['interaction_type'] = normalized['interaction_type'].fillna('general')
        return normalized

    def _detect_binary_issue_columns(self, frame: pd.DataFrame, semantic: dict[str, str]) -> list[str]:
        reserved = set(semantic.values())
        issue_columns: list[str] = []
        for column in frame.columns:
            if column in reserved:
                continue
            series = pd.to_numeric(frame[column], errors='coerce')
            valid = series.dropna()
            if valid.empty:
                continue
            unique = set(valid.unique().tolist())
            if unique.issubset({0, 1}) and len(unique) > 1:
                issue_columns.append(column)
        return issue_columns[:80]

    def _resolve_country(self, country_value, code_value, mappings: dict[str, dict[str, str]]) -> str | None:
        for value in (country_value, code_value):
            resolved = self._map_country_value(value, mappings)
            if resolved:
                return resolved
        return None

    def _map_country_value(self, value, mappings: dict[str, dict[str, str]]) -> str | None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        text = str(value).strip()
        if not text or text.lower() in {'nan', 'na', 'none', 'null', '""'}:
            return None
        canonical = self._canonical_code(text)
        normalized = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
        if normalized in COUNTRY_ALIASES:
            return COUNTRY_ALIASES[normalized]
        lookup_candidates = [candidate for candidate in [text, canonical] if candidate]
        for field_name in ('country', 'country_code', 'country_id', 'gwno', 'global'):
            for candidate in lookup_candidates:
                mapped = mappings.get(field_name, {}).get(candidate)
                if mapped:
                    return mapped
        try:
            country = pycountry.countries.lookup(text)
            return country.name
        except LookupError:
            return text

    def _resolve_issue(self, row: pd.Series, semantic: dict[str, str], issue_columns: list[str]) -> str:
        issue_column = semantic.get('issue_type')
        if issue_column and pd.notna(row.get(issue_column)):
            return str(row.get(issue_column)).strip()
        active_issues = [column for column in issue_columns if pd.to_numeric(row.get(column), errors='coerce') == 1]
        if active_issues:
            return '|'.join(active_issues[:3])
        dataset_hint = semantic.get('stance_value', 'general')
        if dataset_hint and 'vote' in dataset_hint.lower():
            return 'vote'
        return 'general'

    def _resolve_stance_value(self, row: pd.Series, semantic: dict[str, str], issue_columns: list[str]) -> float:
        stance_column = semantic.get('stance_value')
        if stance_column:
            value = row.get(stance_column)
            numeric = pd.to_numeric(value, errors='coerce')
            if pd.notna(numeric):
                return float(numeric)
            return float(self._categorical_to_score(str(value)))
        if issue_columns:
            return float(sum(pd.to_numeric(row.get(column), errors='coerce') == 1 for column in issue_columns))
        return 0.0

    def _resolve_intensity(self, row: pd.Series, semantic: dict[str, str]) -> float:
        intensity_column = semantic.get('intensity')
        if not intensity_column:
            return 0.0
        value = pd.to_numeric(row.get(intensity_column), errors='coerce')
        if pd.notna(value):
            return float(value)
        return float(self._categorical_to_score(str(row.get(intensity_column))))

    def _extract_date(self, row: pd.Series, semantic: dict[str, str]) -> str | None:
        date_column = semantic.get('date')
        if date_column and pd.notna(row.get(date_column)):
            return str(row.get(date_column))
        return None

    def _collect_extra_features(self, row: pd.Series, semantic: dict[str, str], issue_columns: list[str]) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        reserved = set(semantic.values()) | set(issue_columns)
        for column in row.index:
            if column in reserved:
                continue
            value = row.get(column)
            if pd.isna(value):
                continue
            if isinstance(value, str) and len(value) > 200:
                continue
            extra[column] = value
            if len(extra) >= 10:
                break
        return extra

    def _interaction_type(self, dataset_name: str, semantic: dict[str, str], issue_columns: list[str]) -> str:
        lowered = dataset_name.lower()
        if 'vote' in lowered:
            return 'voting'
        if 'peace' in lowered or 'agreement' in lowered or 'alliance' in lowered:
            return 'cooperation'
        if 'conflict' in lowered or 'dyadic' in lowered or 'violence' in lowered:
            return 'conflict'
        if issue_columns:
            return 'issue-stance'
        if semantic.get('country_2'):
            return 'dyadic'
        return 'country-profile'

    def _relation_score(self, dataset_name: str, stance_value: float, intensity: float) -> float:
        lowered = dataset_name.lower()
        if any(token in lowered for token in ('conflict', 'dyadic', 'violence', 'battle')):
            return -(abs(intensity) if intensity else max(abs(stance_value), 1.0))
        if any(token in lowered for token in ('peace', 'agreement', 'alliance')):
            return abs(stance_value) + abs(intensity)
        return stance_value if stance_value else intensity

    def _categorical_to_score(self, text: str) -> int:
        normalized = re.sub(r'[^a-z]+', ' ', str(text).lower()).strip()
        if not normalized:
            return 0
        positive_terms = {'yes', 'support', 'approve', 'ally', 'major', 'government'}
        negative_terms = {'no', 'oppose', 'against', 'conflict', 'minor', 'rebel'}
        neutral_terms = {'abstain', 'neutral', 'unknown'}
        if any(term in normalized for term in positive_terms):
            return 1
        if any(term in normalized for term in negative_terms):
            return -1
        if any(term in normalized for term in neutral_terms):
            return 0
        return 0

    def _coerce_year(self, value) -> int | None:
        numeric = pd.to_numeric(value, errors='coerce')
        if pd.isna(numeric):
            if isinstance(value, str):
                match = re.search(r'(19|20)\d{2}', value)
                if match:
                    return int(match.group(0))
            return None
        year = int(numeric)
        if 1800 <= year <= 2100:
            return year
        return None

    def _canonical_code(self, value: str) -> str | None:
        numeric = pd.to_numeric(value, errors='coerce')
        if pd.notna(numeric):
            if float(numeric).is_integer():
                return str(int(numeric))
            return str(float(numeric))
        return value
