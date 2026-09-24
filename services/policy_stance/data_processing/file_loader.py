from __future__ import annotations

import csv
import io
import os
import zipfile
from typing import Iterable

import pandas as pd
from fastapi import UploadFile

from data_processing.types import DatasetArtifact, FileResource


DATA_EXTENSIONS = {'.csv', '.xlsx', '.xls', '.zip'}
CODEBOOK_EXTENSIONS = {'.pdf', '.csv', '.xlsx', '.xls'}


class FileLoader:
    def expand_uploads(self, uploads: Iterable[tuple[str, bytes, str | None]]) -> list[FileResource]:
        resources: list[FileResource] = []
        for name, content, content_type in uploads:
            extension = os.path.splitext(name)[1].lower()
            if extension == '.zip':
                resources.extend(self._expand_zip(name, content, content_type))
            else:
                resources.append(
                    FileResource(
                        name=name,
                        original_name=name,
                        extension=extension,
                        content=content,
                        content_type=content_type,
                    )
                )
        return resources

    async def upload_to_resources(self, files: list[UploadFile]) -> list[FileResource]:
        uploads = []
        for upload in files:
            uploads.append((upload.filename or 'unnamed', await upload.read(), upload.content_type))
        return self.expand_uploads(uploads)

    def datasets(self, resources: list[FileResource]) -> list[FileResource]:
        return [resource for resource in resources if resource.extension in DATA_EXTENSIONS and not self.looks_like_codebook(resource.name)]

    def codebooks(self, resources: list[FileResource]) -> list[FileResource]:
        return [resource for resource in resources if self.looks_like_codebook(resource.name)]

    def looks_like_codebook(self, name: str) -> bool:
        lowered = name.lower()
        return any(token in lowered for token in ('codebook', 'dictionary', 'metadata')) or lowered.endswith('.pdf')

    def load_dataset_frames(self, resource: FileResource) -> list[DatasetArtifact]:
        if resource.extension == '.csv':
            frame = self._read_csv(resource.content)
            return [DatasetArtifact(name=resource.stem, source_name=resource.original_name, frame=frame)]
        if resource.extension in {'.xlsx', '.xls'}:
            workbook = pd.ExcelFile(io.BytesIO(resource.content))
            artifacts: list[DatasetArtifact] = []
            for sheet_name in workbook.sheet_names:
                frame = workbook.parse(sheet_name=sheet_name)
                if frame.empty:
                    continue
                dataset_name = f'{resource.stem}::{sheet_name}'
                artifacts.append(
                    DatasetArtifact(
                        name=dataset_name,
                        source_name=resource.original_name,
                        sheet_name=sheet_name,
                        frame=self._clean_frame(frame),
                    )
                )
            return artifacts
        raise ValueError(f'Unsupported dataset type: {resource.name}')

    def _expand_zip(self, archive_name: str, content: bytes, content_type: str | None) -> list[FileResource]:
        resources: list[FileResource] = []
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                inner_name = member.filename.replace('\\', '/').split('/')[-1]
                extension = os.path.splitext(inner_name)[1].lower()
                if extension not in DATA_EXTENSIONS | CODEBOOK_EXTENSIONS:
                    continue
                resources.append(
                    FileResource(
                        name=inner_name,
                        original_name=inner_name,
                        extension=extension,
                        content=archive.read(member),
                        content_type=content_type,
                        parent_archive=archive_name,
                    )
                )
        return resources

    def _read_csv(self, content: bytes) -> pd.DataFrame:
        encoding_candidates = ('utf-8', 'utf-8-sig', 'latin-1')
        text = None
        for encoding in encoding_candidates:
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = content.decode('latin-1', errors='ignore')

        sample = text[:5000]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;|\t')
            sep = dialect.delimiter
        except csv.Error:
            sep = ',' if sample.count(',') >= sample.count(';') else ';'

        frame = pd.read_csv(io.StringIO(text), sep=sep, low_memory=False)
        return self._clean_frame(frame)

    def _clean_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame.columns = [str(col).strip() for col in frame.columns]
        frame = frame.loc[:, ~frame.columns.duplicated()]
        return frame
