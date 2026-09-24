import { useRef, useState } from 'react';

import SectionCard from './SectionCard';

export default function UploadPanel({ onUpload, loading, previews }) {
  const [files, setFiles] = useState([]);
  const inputRef = useRef(null);

  const handleFiles = (incoming) => {
    setFiles(Array.from(incoming || []));
  };

  return (
    <SectionCard
      title="Multi-Dataset Ingestion"
      kicker="Source Intake"
      actions={
        <button
          className="rounded-full bg-ember px-5 py-2 text-sm font-semibold text-ink transition hover:bg-orange-300 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!files.length || loading}
          onClick={() => onUpload(files)}
        >
          {loading ? 'Parsing...' : 'Upload & Analyze'}
        </button>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <button
          className="rounded-3xl border border-dashed border-white/20 bg-white/[0.03] p-6 text-left transition hover:border-mint/60 hover:bg-white/[0.06]"
          onClick={() => inputRef.current?.click()}
        >
          <p className="font-display text-2xl text-white">Drop CSV, XLSX, ZIP, and PDF codebooks</p>
          <p className="mt-3 max-w-xl text-sm text-steel">
            The pipeline auto-expands archives, pairs datasets with codebooks, infers schema roles, and normalizes everything into a policy stance graph.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {files.length ? files.map((file) => <span key={file.name} className="metric-chip">{file.name}</span>) : <span className="metric-chip">No files selected</span>}
          </div>
          <input ref={inputRef} className="hidden" type="file" multiple onChange={(event) => handleFiles(event.target.files)} />
        </button>
        <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-steel">Parsed Previews</p>
          <div className="mt-3 space-y-3 max-h-64 overflow-auto pr-1">
            {(previews || []).slice(0, 4).map((preview) => (
              <div key={preview.dataset} className="rounded-2xl border border-white/10 bg-black/10 p-3">
                <p className="font-medium text-white">{preview.dataset}</p>
                <p className="mt-1 text-xs text-steel">{Object.entries(preview.schema?.semantic_map || {}).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'Schema inferred dynamically'}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
