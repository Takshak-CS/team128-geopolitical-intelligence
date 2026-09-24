import SectionCard from './SectionCard';

export default function PreviewPanel({ previews }) {
  return (
    <SectionCard title="Parsed Dataset Preview" kicker="Human-Readable Normalization">
      <div className="space-y-5 max-h-[520px] overflow-auto pr-2">
        {(previews || []).slice(0, 6).map((preview) => (
          <div key={preview.dataset} className="rounded-3xl border border-white/10 bg-black/10 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-display text-lg text-white">{preview.dataset}</h3>
              <span className="metric-chip">{Object.keys(preview.schema?.semantic_map || {}).length} semantic matches</span>
            </div>
            <div className="mt-4 overflow-auto">
              <table className="min-w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-steel">
                    {Object.keys(preview.preview?.[0] || {}).slice(0, 8).map((column) => <th key={column} className="px-3 py-2 font-medium">{column}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(preview.preview || []).slice(0, 4).map((row, rowIndex) => (
                    <tr key={rowIndex} className="border-b border-white/5 align-top">
                      {Object.keys(preview.preview?.[0] || {}).slice(0, 8).map((column) => <td key={column} className="px-3 py-2 text-slate-200">{String(row[column] ?? '')}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
