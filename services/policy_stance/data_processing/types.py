from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class FileResource:
    name: str
    original_name: str
    extension: str
    content: bytes
    content_type: str | None = None
    parent_archive: str | None = None

    @property
    def stem(self) -> str:
        return self.name.rsplit('.', 1)[0]


@dataclass
class DatasetArtifact:
    name: str
    source_name: str
    frame: pd.DataFrame
    sheet_name: str | None = None
    mappings: dict[str, dict[str, str]] = field(default_factory=dict)
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodebookArtifact:
    name: str
    source_name: str
    mappings: dict[str, dict[str, str]]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessedSession:
    session_id: str
    normalized_df: pd.DataFrame
    dataset_summaries: list[dict[str, Any]]
    pairings: list[dict[str, Any]]
    preview_payload: list[dict[str, Any]]
    countries: list[str]
    issue_types: list[str]
    year_range: list[int | None]
    codebooks: list[dict[str, Any]]
