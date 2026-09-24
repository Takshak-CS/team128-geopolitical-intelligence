from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd


CANONICAL_PATTERNS = {
    'year': [r'\byear\b', r'active_year', r'date_start', r'start_date'],
    'country_1': [r'country$', r'location$', r'state', r'country_1', r'side_a', r'country_name'],
    'country_2': [r'country_2', r'side_b', r'opponent', r'partner', r'ally', r'target'],
    'country_1_code': [r'gwno_a', r'country_id$', r'ccode', r'iso3', r'cow', r'side_a_id'],
    'country_2_code': [r'gwno_b', r'partner_id', r'target_id', r'side_b_id'],
    'issue_type': [r'issue', r'incompatibility', r'type_of_conflict', r'agenda', r'topic', r'policy'],
    'stance_value': [r'vote', r'position', r'stance', r'support', r'score', r'value'],
    'intensity': [r'intensity', r'fatalit', r'deaths', r'severity', r'best_est', r'high_est'],
    'date': [r'date', r'month', r'day', r'timestamp'],
}


@dataclass
class SchemaInference:
    semantic_map: dict[str, str]
    wide_country_columns: list[str]
    metadata_columns: list[str]
    diagnostics: dict[str, Any]


class SchemaMapper:
    def infer(self, frame: pd.DataFrame) -> SchemaInference:
        normalized = {col: self._normalize(col) for col in frame.columns}
        semantic_map: dict[str, str] = {}

        for canonical, patterns in CANONICAL_PATTERNS.items():
            for column, simplified in normalized.items():
                if any(re.search(pattern, simplified) for pattern in patterns):
                    semantic_map.setdefault(canonical, column)

        if 'year' not in semantic_map:
            semantic_map['year'] = self._detect_year_column(frame)

        wide_country_columns = self._detect_wide_country_columns(frame)
        metadata_columns = [col for col in frame.columns if col not in wide_country_columns]

        diagnostics = {
            'row_count': int(len(frame)),
            'column_count': int(len(frame.columns)),
            'wide_country_column_count': len(wide_country_columns),
        }
        return SchemaInference(
            semantic_map={key: value for key, value in semantic_map.items() if value},
            wide_country_columns=wide_country_columns,
            metadata_columns=metadata_columns,
            diagnostics=diagnostics,
        )

    def _detect_year_column(self, frame: pd.DataFrame) -> str | None:
        for column in frame.columns:
            series = pd.to_numeric(frame[column], errors='coerce')
            valid = series.dropna()
            if valid.empty:
                continue
            if valid.between(1800, 2100).mean() > 0.85:
                return column
        return None

    def _detect_wide_country_columns(self, frame: pd.DataFrame) -> list[str]:
        candidates: list[str] = []
        for column in frame.columns:
            normalized = self._normalize(column)
            if normalized in {'year', 'date', 'resolution', 'issue', 'topic'}:
                continue
            if re.fullmatch(r'[a-z]{3}', normalized):
                candidates.append(column)
                continue
            if len(normalized.split('_')) <= 3 and self._looks_like_country_name(normalized):
                candidates.append(column)
        if len(candidates) < 8:
            return []
        return candidates

    def _looks_like_country_name(self, normalized: str) -> bool:
        country_terms = {
            'afghanistan', 'argentina', 'australia', 'brazil', 'canada', 'china', 'egypt', 'france',
            'germany', 'india', 'indonesia', 'iran', 'iraq', 'israel', 'italy', 'japan', 'kenya',
            'mexico', 'pakistan', 'russia', 'saudi_arabia', 'south_africa', 'turkiye', 'ukraine',
            'united_kingdom', 'united_states', 'usa', 'uk', 'uae',
        }
        return normalized in country_terms

    def _normalize(self, value: str) -> str:
        return re.sub(r'[^a-z0-9]+', '_', str(value).lower()).strip('_')
