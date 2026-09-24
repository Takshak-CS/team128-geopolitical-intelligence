import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CartesianGrid, Legend, Line, LineChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis,
  Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

import { getCompare, getCompareInsight } from '../api';
import Panel from '../components/Panel';

const DEFAULT_PAIRS = [
  ['India', 'Pakistan'], ['USA', 'Russia'], ['Israel', 'Syria'],
  ['China', 'India'], ['USA', 'China'], ['Saudi Arabia', 'Iran'],
];

const BLOC_COLOR = {
  'Western Bloc': '#f26b38',
  'Russia+Allies': '#0f7b8c',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#7fb7be',
};

function SearchSelect({ label, value, onChange, options }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [dropPos, setDropPos] = useState({ top: 0, left: 0, width: 260 });
  const inputRef = useRef(null);
  const dropRef = useRef(null);

  const filtered = useMemo(() =>
    options.filter((n) => !query || n.toLowerCase().includes(query.toLowerCase())),
    [options, query]);

  const openDrop = () => {
    if (inputRef.current) {
      const r = inputRef.current.getBoundingClientRect();
      setDropPos({ top: r.bottom + 4, left: r.left, width: Math.max(260, r.width) });
    }
    setQuery('');
    setOpen(true);
  };

  useEffect(() => {
    const handler = (e) => {
      if (dropRef.current?.contains(e.target) || inputRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="country-search-box">
      <label>{label}</label>
      <div
        ref={inputRef}
        className="search-select-trigger"
        onClick={openDrop}
        style={{ cursor: 'pointer', padding: '6px 12px', border: '1.5px solid var(--border)', borderRadius: 8, background: 'var(--surface)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', minWidth: 180 }}
      >
        <span style={{ fontWeight: 600 }}>{value || 'Select…'}</span>
        <span style={{ opacity: 0.5, fontSize: '0.75rem' }}>▼</span>
      </div>
      {open && (
        <div ref={dropRef} style={{ position: 'fixed', top: dropPos.top, left: dropPos.left, width: dropPos.width, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.16)', zIndex: 9999, overflow: 'hidden' }}>
          <input
            autoFocus
            placeholder="Search country…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: '100%', border: 'none', borderBottom: '1px solid var(--border)', padding: '8px 12px', fontSize: '0.85rem', outline: 'none', background: 'var(--surface)' }}
          />
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {filtered.map((n) => (
              <div
                key={n}
                onClick={() => { onChange(n); setOpen(false); }}
                style={{ padding: '7px 14px', cursor: 'pointer', fontWeight: n === value ? 700 : 400, background: n === value ? 'rgba(242,107,56,0.08)' : undefined, fontSize: '0.85rem' }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(0,0,0,0.04)'}
                onMouseLeave={(e) => e.currentTarget.style.background = n === value ? 'rgba(242,107,56,0.08)' : ''}
              >
                {n === value ? '✓ ' : ''}{n}
              </div>
            ))}
            {filtered.length === 0 && <div style={{ padding: '10px 14px', color: 'var(--muted)', fontSize: '0.8rem' }}>No matches</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function InsightPanel({ insight, loading }) {
  if (loading) return <div className="loading-inline">Generating insight…</div>;
  if (!insight) return null;
  const { bullets, metrics } = insight;
  return (
    <div className="insight-panel">
      <div className="insight-header">
        <span className="insight-badge">AI Analysis</span>
        <span className="insight-sim" style={{ color: metrics.same_bloc ? '#2a9d8f' : '#f26b38' }}>
          {metrics.same_bloc ? 'Same Bloc' : 'Opposing Blocs'}
        </span>
      </div>
      <ul className="insight-bullets">
        {bullets.map((b, i) => <li key={i}>{b}</li>)}
      </ul>
      <div className="insight-metrics">
        {metrics.shared_conflicts > 0 && <span className="im-chip conflict">{metrics.shared_conflicts} shared conflicts</span>}
        {metrics.vote_match_rate != null && <span className="im-chip">{metrics.vote_match_rate}% vote match</span>}
        {metrics.bloc_a && <span className="im-chip" style={{ borderColor: BLOC_COLOR[metrics.bloc_a] }}>{metrics.bloc_a}</span>}
        {metrics.bloc_b && metrics.bloc_b !== metrics.bloc_a && <span className="im-chip" style={{ borderColor: BLOC_COLOR[metrics.bloc_b] }}>{metrics.bloc_b}</span>}
        {metrics.vote_drift != null && (
          <span className={`im-chip ${metrics.vote_drift > 0 ? 'converge' : 'diverge'}`}>
            {metrics.vote_drift > 0 ? `↑ converging ${metrics.vote_drift.toFixed(1)}pp` : `↓ diverging ${Math.abs(metrics.vote_drift).toFixed(1)}pp`}
          </span>
        )}
      </div>
    </div>
  );
}

export default function ComparePage({ countries }) {
  const [countryA, setCountryA] = useState('');
  const [countryB, setCountryB] = useState('');
  const [comparison, setComparison] = useState(null);
  const [insight, setInsight] = useState(null);
  const [loading, setLoading] = useState(false);
  const [insightLoading, setInsightLoading] = useState(false);

  const countryNames = useMemo(() => countries.map((c) => c.name).sort(), [countries]);

  useEffect(() => {
    if (!countries.length || countryA) return;
    for (const [a, b] of DEFAULT_PAIRS) {
      if (countryNames.includes(a) && countryNames.includes(b)) {
        setCountryA(a); setCountryB(b); return;
      }
    }
    setCountryA(countryNames[0] || '');
    setCountryB(countryNames[1] || '');
  }, [countries]);

  useEffect(() => {
    if (!countryA || !countryB || countryA === countryB) return;
    setLoading(true);
    setInsightLoading(true);
    setInsight(null);
    Promise.all([
      getCompare(countryA, countryB),
      getCompareInsight(countryA, countryB),
    ]).then(([cmp, ins]) => {
      setComparison(cmp);
      setInsight(ins);
      setLoading(false);
      setInsightLoading(false);
    }).catch(() => {
      setLoading(false);
      setInsightLoading(false);
    });
  }, [countryA, countryB]);

  const agreementSeries = useMemo(() =>
    Object.entries(comparison?.temporal_agreement || {})
      .map(([year, val]) => ({
        year: Number(year),
        agreement: typeof val === 'object' ? (val.total > 0 ? val.same / val.total : 0) : Number(val),
      }))
      .sort((a, b) => a.year - b.year),
    [comparison]);

  const radarData = useMemo(() => {
    if (!comparison) return [];
    const a = comparison.country_a?.centrality || {};
    const b = comparison.country_b?.centrality || {};
    return [
      { metric: 'Degree', A: +(a.degree * 100).toFixed(2), B: +(b.degree * 100).toFixed(2) },
      { metric: 'Betweenness', A: +(a.betweenness * 500).toFixed(2), B: +(b.betweenness * 500).toFixed(2) },
      { metric: 'PageRank', A: +(a.pagerank * 5000).toFixed(2), B: +(b.pagerank * 5000).toFixed(2) },
      { metric: 'Conflicts', A: comparison.country_a?.total_conflicts || 0, B: comparison.country_b?.total_conflicts || 0 },
      { metric: 'Deaths (K)', A: +((comparison.country_a?.total_deaths || 0) / 1000).toFixed(1), B: +((comparison.country_b?.total_deaths || 0) / 1000).toFixed(1) },
    ];
  }, [comparison]);

  const simColor = comparison
    ? (comparison.similarity > 0.7 ? '#2a9d8f' : comparison.similarity > 0.4 ? '#e3a008' : '#f26b38')
    : '#aaa';

  return (
    <div className="page-grid wide">

      {/* Selector + quick stats */}
      <Panel title="Country Comparison" subtitle="Compare conflict exposure, network centrality, bloc alignment, and UN voting patterns.">
        <div className="compare-selector-row">
          <SearchSelect label="Country A" value={countryA} onChange={setCountryA} options={countryNames} />
          <div className="vs-badge" style={{ color: simColor }}>
            <div className="vs-label">vs</div>
            {comparison && <div className="similarity-score">Similarity {Number(comparison.similarity).toFixed(3)}</div>}
          </div>
          <SearchSelect label="Country B" value={countryB} onChange={setCountryB} options={countryNames} />
        </div>
        {loading && <div className="loading-inline">Loading…</div>}
        {comparison && !loading && (
          <div className="dual-column" style={{ marginTop: 14 }}>
            <div className="mini-card">
              <h3>{comparison.country_a?.name}</h3>
              <p><strong>{comparison.country_a?.total_conflicts || 0}</strong> conflict events</p>
              <p><strong>{Math.round(comparison.country_a?.total_deaths || 0).toLocaleString()}</strong> deaths</p>
            </div>
            <div className="mini-card">
              <h3>{comparison.country_b?.name}</h3>
              <p><strong>{comparison.country_b?.total_conflicts || 0}</strong> conflict events</p>
              <p><strong>{Math.round(comparison.country_b?.total_deaths || 0).toLocaleString()}</strong> deaths</p>
            </div>
          </div>
        )}
      </Panel>

      {/* AI Insight */}
      <Panel title="Intelligence Summary" subtitle="Data-derived analysis of the geopolitical relationship between the two countries.">
        <InsightPanel insight={insight} loading={insightLoading} />
      </Panel>

      {/* UN Voting Agreement */}
      <Panel title="UN Voting Agreement Over Time" subtitle="Fraction of UNGA resolutions where both countries voted the same way, per year.">
        {agreementSeries.length > 0 ? (
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={agreementSeries}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="year" />
                <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                <Tooltip formatter={(v) => `${(v * 100).toFixed(1)}%`} labelFormatter={(l) => `Year ${l}`} />
                <Line type="monotone" dataKey="agreement" stroke="#f26b38" strokeWidth={2.5} dot={false} name="Agreement rate" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : <p className="empty-hint">No shared UN voting record for this pair — they may vote in different resolutions or one has limited data.</p>}
      </Panel>

      {/* Centrality Radar */}
      <Panel title="Network Position (Centrality Radar)" subtitle="Relative influence in the global conflict network. Betweenness and PageRank scaled for visibility.">
        {radarData.length > 0 ? (
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={320}>
              <RadarChart data={radarData} outerRadius="75%">
                <PolarGrid />
                <PolarAngleAxis dataKey="metric" />
                <PolarRadiusAxis tick={{ fontSize: 10 }} />
                <Radar dataKey="A" name={countryA} stroke="#f26b38" fill="#f26b38" fillOpacity={0.35} />
                <Radar dataKey="B" name={countryB} stroke="#0f7b8c" fill="#0f7b8c" fillOpacity={0.28} />
                <Legend />
                <Tooltip />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        ) : <p className="empty-hint">Select two countries to compare centrality.</p>}
      </Panel>

      {/* Shared Conflicts */}
      <Panel title="Shared Conflict Events" subtitle="Events where both countries appear in the same conflict row.">
        <div className="table-wrap compact-table">
          <table>
            <thead><tr><th>Year</th><th>Conflict</th><th>Issue</th><th>Intensity</th><th>Dataset</th></tr></thead>
            <tbody>
              {!(comparison?.shared_conflicts?.length)
                ? <tr><td colSpan={5} className="empty-hint">No direct shared conflict rows — these countries may conflict indirectly or via proxies.</td></tr>
                : (comparison.shared_conflicts || []).map((item, i) => (
                  <tr key={i}>
                    <td>{item.year}</td>
                    <td>{item.conflict_name || '—'}</td>
                    <td>{item.issue || '—'}</td>
                    <td style={{ color: item.intensity > 100 ? '#f26b38' : undefined }}>{item.intensity}</td>
                    <td>{item.dataset}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Shared UN Votes */}
      <Panel title="Shared UN Votes" subtitle="Recent General Assembly resolutions where both countries voted.">
        <div className="table-wrap compact-table">
          <table>
            <thead><tr><th>Year</th><th>Resolution</th><th>{countryA}</th><th>{countryB}</th><th>Match?</th></tr></thead>
            <tbody>
              {!(comparison?.shared_votes?.length)
                ? <tr><td colSpan={5} className="empty-hint">No overlapping votes found.</td></tr>
                : (comparison.shared_votes || []).slice(0, 60).map((item, i) => (
                  <tr key={i} style={{ background: item.match ? 'rgba(42,157,143,0.06)' : 'rgba(242,107,56,0.06)' }}>
                    <td>{item.year}</td>
                    <td title={item.resolution}>{item.resolution}</td>
                    <td>{item.vote_a}</td>
                    <td>{item.vote_b}</td>
                    <td style={{ color: item.match ? '#2a9d8f' : '#f26b38' }}>{item.match ? '✓' : '✗'}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Panel>

    </div>
  );
}
