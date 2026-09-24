from __future__ import annotations

import re
import uuid
from collections import defaultdict

import pandas as pd
from fastapi import UploadFile

from data_processing.codebook_parser import CodebookParser
from data_processing.file_loader import FileLoader
from data_processing.normalizer import DataNormalizer
from data_processing.types import CodebookArtifact, DatasetArtifact, ProcessedSession


class GeopoliticalPipeline:
    def __init__(self) -> None:
        self.loader = FileLoader()
        self.codebook_parser = CodebookParser()
        self.normalizer = DataNormalizer()

    async def process_uploads(self, files: list[UploadFile]) -> ProcessedSession:
        resources = await self.loader.upload_to_resources(files)
        dataset_resources = self.loader.datasets(resources)
        codebook_resources = self.loader.codebooks(resources)

        dataset_artifacts: list[DatasetArtifact] = []
        for resource in dataset_resources:
            if resource.extension == '.zip':
                continue
            dataset_artifacts.extend(self.loader.load_dataset_frames(resource))

        codebooks: list[CodebookArtifact] = [self.codebook_parser.parse(resource) for resource in codebook_resources]
        pairings = self._pair_datasets_and_codebooks(dataset_artifacts, codebooks)

        merged_global_mappings = self.codebook_parser.merge(codebooks)
        normalized_frames: list[pd.DataFrame] = []
        dataset_summaries: list[dict] = []
        preview_payload: list[dict] = []

        codebooks_by_name = {codebook.name: codebook for codebook in codebooks}
        for artifact in dataset_artifacts:
            paired_maps = {key: dict(value) for key, value in merged_global_mappings.items()}
            for matched_name in pairings.get(artifact.name, []):
                for field, values in codebooks_by_name[matched_name].mappings.items():
                    paired_maps.setdefault(field, {}).update(values)

            normalized, diagnostics = self.normalizer.normalize_dataset(artifact, paired_maps)
            normalized_frames.append(normalized)
            dataset_summaries.append(diagnostics['summary'])
            preview_payload.append(
                {
                    'dataset': artifact.name,
                    'schema': diagnostics['schema'],
                    'preview': diagnostics['preview'],
                }
            )

        normalized_df = pd.concat(normalized_frames, ignore_index=True) if normalized_frames else pd.DataFrame()
        countries = self._sorted_unique(normalized_df, 'country_1')
        countries = sorted(set(countries + self._sorted_unique(normalized_df, 'country_2')))
        issue_types = self._sorted_unique(normalized_df, 'issue_type')

        year_range: list[int | None] = [None, None]
        if not normalized_df.empty and normalized_df['year'].notna().any():
            year_range = [
                int(normalized_df['year'].dropna().min()),
                int(normalized_df['year'].dropna().max()),
            ]

        return ProcessedSession(
            session_id=str(uuid.uuid4()),
            normalized_df=normalized_df,
            dataset_summaries=dataset_summaries,
            pairings=[
                {'dataset': dataset_name, 'codebooks': codebook_names}
                for dataset_name, codebook_names in pairings.items()
            ],
            preview_payload=preview_payload,
            countries=countries,
            issue_types=issue_types,
            year_range=year_range,
            codebooks=[
                {
                    'name': codebook.name,
                    'source_name': codebook.source_name,
                    'mapping_fields': sorted(codebook.mappings.keys()),
                    'diagnostics': codebook.diagnostics,
                }
                for codebook in codebooks
            ],
        )

    def _pair_datasets_and_codebooks(
        self,
        datasets: list[DatasetArtifact],
        codebooks: list[CodebookArtifact],
    ) -> dict[str, list[str]]:
        pairings: dict[str, list[str]] = defaultdict(list)
        for dataset in datasets:
            dataset_tokens = self._name_tokens(dataset.name)
            ranked = []
            for codebook in codebooks:
                score = len(dataset_tokens & self._name_tokens(codebook.name))
                if score > 0:
                    ranked.append((score, codebook.name))
            ranked.sort(reverse=True)
            pairings[dataset.name] = [name for _, name in ranked[:3]]
        return dict(pairings)

    def _name_tokens(self, value: str) -> set[str]:
        cleaned = (
            value.lower()
            .replace('codebook', '')
            .replace('dataset', '')
            .replace('csv', '')
            .replace('xlsx', '')
            .replace('pdf', '')
        )
        return {token for token in re.split(r'[^a-z0-9]+', cleaned) if token}

    def _sorted_unique(self, frame: pd.DataFrame, column: str) -> list[str]:
        if frame.empty or column not in frame:
            return []
        return sorted(frame[column].dropna().astype(str).unique().tolist())
