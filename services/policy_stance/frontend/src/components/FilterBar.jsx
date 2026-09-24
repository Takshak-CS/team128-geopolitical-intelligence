import SectionCard from './SectionCard';

export default function FilterBar({ metadata, filters, onChange }) {
  const [minYear, maxYear] = metadata?.year_range || [null, null];
  const countries = metadata?.countries || [];
  const issues = metadata?.issues || [];

  return (
    <SectionCard title="Analytical Controls" kicker="Cross-Source Lens">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <label className="space-y-2 text-sm">
          <span className="text-steel">Country</span>
          <select className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3" value={filters.country || ''} onChange={(event) => onChange('country', event.target.value || null)}>
            <option value="">Global</option>
            {countries.map((country) => <option key={country} value={country}>{country}</option>)}
          </select>
        </label>
        <label className="space-y-2 text-sm">
          <span className="text-steel">Issue</span>
          <select className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3" value={filters.issue || ''} onChange={(event) => onChange('issue', event.target.value || null)}>
            <option value="">All issues</option>
            {issues.map((issue) => <option key={issue} value={issue}>{issue}</option>)}
          </select>
        </label>
        <label className="space-y-2 text-sm">
          <span className="text-steel">Similarity Metric</span>
          <select className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3" value={filters.metric} onChange={(event) => onChange('metric', event.target.value)}>
            <option value="combined">Combined</option>
            <option value="cosine">Cosine</option>
            <option value="dtw">Dynamic Time Warping</option>
          </select>
        </label>
        <label className="space-y-2 text-sm">
          <span className="text-steel">Start Year</span>
          <input className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3" type="number" min={minYear || undefined} max={maxYear || undefined} value={filters.startYear ?? minYear ?? ''} onChange={(event) => onChange('startYear', event.target.value ? Number(event.target.value) : null)} />
        </label>
        <label className="space-y-2 text-sm">
          <span className="text-steel">End Year</span>
          <input className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3" type="number" min={minYear || undefined} max={maxYear || undefined} value={filters.endYear ?? maxYear ?? ''} onChange={(event) => onChange('endYear', event.target.value ? Number(event.target.value) : null)} />
        </label>
      </div>
    </SectionCard>
  );
}
