from __future__ import annotations

import io
import re
from collections import defaultdict
from typing import Iterable

import pandas as pd

from data_processing.file_loader import FileLoader
from data_processing.types import CodebookArtifact, FileResource


class CodebookParser:
    variable_header_pattern = re.compile(r'^[A-Za-z][A-Za-z0-9_\-\s/]{1,50}$')
    mapping_pattern = re.compile(r'^(?P<code>[A-Za-z0-9\.\-]{1,12})[\s:\-\u2013]+(?P<label>[A-Za-z][A-Za-z0-9 ,\(\)/&\'\-]{2,})$')

    def __init__(self) -> None:
        self.loader = FileLoader()

    def parse(self, resource: FileResource) -> CodebookArtifact:
        if resource.extension == '.pdf':
            mappings, diagnostics = self._parse_pdf(resource.content)
        elif resource.extension in {'.csv', '.xlsx', '.xls'}:
            mappings, diagnostics = self._parse_tabular(resource)
        else:
            mappings, diagnostics = {}, {'warning': 'unsupported codebook type'}
        return CodebookArtifact(name=resource.stem, source_name=resource.original_name, mappings=mappings, diagnostics=diagnostics)

    def merge(self, codebooks: Iterable[CodebookArtifact]) -> dict[str, dict[str, str]]:
        merged: dict[str, dict[str, str]] = defaultdict(dict)
        for codebook in codebooks:
            for field, field_map in codebook.mappings.items():
                merged[field].update(field_map)
        return dict(merged)

    def _parse_tabular(self, resource: FileResource) -> tuple[dict[str, dict[str, str]], dict]:
        mappings: dict[str, dict[str, str]] = defaultdict(dict)
        diagnostics = {'tables': 0, 'rows': 0}
        artifacts = self.loader.load_dataset_frames(resource)
        for artifact in artifacts:
            diagnostics['tables'] += 1
            diagnostics['rows'] += len(artifact.frame)
            frame_mappings = self._extract_mappings_from_frame(artifact.frame)
            for field, values in frame_mappings.items():
                mappings[field].update(values)
        return dict(mappings), diagnostics

    def _parse_pdf(self, content: bytes) -> tuple[dict[str, dict[str, str]], dict]:
        diagnostics: dict[str, int] = {'pages': 0, 'tables': 0, 'line_hits': 0}
        mappings: dict[str, dict[str, str]] = defaultdict(dict)
        extracted_text_chunks: list[str] = []

        try:
            import fitz

            with fitz.open(stream=content, filetype='pdf') as document:
                diagnostics['pages'] = document.page_count
                for page in document:
                    extracted_text_chunks.append(page.get_text('text'))
        except Exception:
            pass

        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                diagnostics['pages'] = max(diagnostics['pages'], len(pdf.pages))
                for page in pdf.pages:
                    for table in page.extract_tables() or []:
                        diagnostics['tables'] += 1
                        table_frame = pd.DataFrame(table)
                        if not table_frame.empty:
                            frame_mappings = self._extract_mappings_from_frame(table_frame.fillna(''))
                            for field, values in frame_mappings.items():
                                mappings[field].update(values)
                    extracted_text = page.extract_text() or ''
                    if extracted_text:
                        extracted_text_chunks.append(extracted_text)
        except Exception:
            pass

        line_mappings, line_hits = self._extract_mappings_from_text('\n'.join(extracted_text_chunks))
        diagnostics['line_hits'] = line_hits
        for field, values in line_mappings.items():
            mappings[field].update(values)

        return dict(mappings), diagnostics

    def _extract_mappings_from_frame(self, frame: pd.DataFrame) -> dict[str, dict[str, str]]:
        mappings: dict[str, dict[str, str]] = defaultdict(dict)
        frame = frame.copy()
        frame.columns = [str(col).strip() if str(col).strip() else f'column_{idx}' for idx, col in enumerate(frame.columns)]
        header_candidates = [str(col).strip().lower() for col in frame.columns]

        if len(frame.columns) >= 2:
            code_idx, label_idx = self._detect_code_label_columns(header_candidates)
            if code_idx is not None and label_idx is not None:
                field = self._derive_field_name(header_candidates, code_idx, label_idx)
                for _, row in frame.iterrows():
                    code = self._normalize_code(row.iloc[code_idx])
                    label = self._normalize_label(row.iloc[label_idx])
                    if code and label:
                        mappings[field][code] = label
                if mappings[field]:
                    return dict(mappings)

        for _, row in frame.iterrows():
            row_values = [str(value).strip() for value in row.tolist() if str(value).strip()]
            if len(row_values) < 2:
                continue
            maybe_code = self._normalize_code(row_values[0])
            maybe_label = self._normalize_label(row_values[1])
            if maybe_code and maybe_label:
                mappings['global'][maybe_code] = maybe_label

        return dict(mappings)

    def _extract_mappings_from_text(self, text: str) -> tuple[dict[str, dict[str, str]], int]:
        mappings: dict[str, dict[str, str]] = defaultdict(dict)
        current_field = 'global'
        line_hits = 0
        for raw_line in text.splitlines():
            line = re.sub(r'\s+', ' ', raw_line).strip(' -:\t')
            if not line:
                continue
            if self.variable_header_pattern.match(line) and len(line.split()) <= 5 and not any(ch.isdigit() for ch in line):
                current_field = self._canonical_field_name(line)
                continue
            match = self.mapping_pattern.match(line)
            if not match:
                continue
            code = self._normalize_code(match.group('code'))
            label = self._normalize_label(match.group('label'))
            if code and label:
                mappings[current_field][code] = label
                line_hits += 1
        return dict(mappings), line_hits

    def _detect_code_label_columns(self, headers: list[str]) -> tuple[int | None, int | None]:
        code_terms = ('code', 'id', 'value', 'category', 'num')
        label_terms = ('label', 'name', 'description', 'meaning', 'category', 'text')
        code_idx = next((idx for idx, value in enumerate(headers) if any(term in value for term in code_terms)), None)
        label_idx = next((idx for idx, value in enumerate(headers) if any(term in value for term in label_terms)), None)
        if code_idx is None and len(headers) >= 2:
            code_idx = 0
        if label_idx is None and len(headers) >= 2:
            label_idx = 1
        if code_idx == label_idx:
            label_idx = 1 if code_idx == 0 and len(headers) > 1 else None
        return code_idx, label_idx

    def _derive_field_name(self, headers: list[str], code_idx: int, label_idx: int) -> str:
        possible = headers[code_idx].replace('_code', '').replace('_id', '').strip('_')
        if possible and possible not in {'code', 'value', 'id'}:
            return self._canonical_field_name(possible)
        label_header = headers[label_idx].replace('_name', '').replace('_label', '').strip('_')
        if label_header and label_header not in {'label', 'name', 'description'}:
            return self._canonical_field_name(label_header)
        return 'global'

    def _canonical_field_name(self, value: str) -> str:
        return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_') or 'global'

    def _normalize_code(self, value) -> str | None:
        if pd.isna(value):
            return None
        text = str(value).strip().strip('"').strip("'")
        if not text or text.lower() == 'nan':
            return None
        numeric = pd.to_numeric(text, errors='coerce')
        if pd.notna(numeric):
            if float(numeric).is_integer():
                return str(int(numeric))
            return str(float(numeric))
        return text

    def _normalize_label(self, value) -> str | None:
        if pd.isna(value):
            return None
        text = str(value).strip().strip('"').strip("'")
        if not text or text.lower() == 'nan':
            return None
        if len(text) == 1 and text.isdigit():
            return None
        return text
