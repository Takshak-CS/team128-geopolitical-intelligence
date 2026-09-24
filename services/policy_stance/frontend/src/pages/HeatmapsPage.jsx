import { useEffect, useMemo, useState } from 'react';
import { Cell, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';

import { getEmbeddings2d, getSimilarity, getVotingAgreementMatrix } from '../api';
import Panel from '../components/Panel';

const TABS = [
  { id: 'similarity', label: 'Country Similarity' },
  { id: 'temporal', label: 'UN Voting Agreement' },
  { id: 'positioning', label: 'Geopolitical Positioning' },
];

const BLOC_COLORS = {
  'Western Bloc': '#f26b38',
  'Russia+Allies': '#0f7b8c',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#7fb7be',
};

function heatColor(t) {
  t = Math.max(0, Math.min(1, t));
  if (t < 0.5) {
    const s = t * 2;
    return `rgb(${Math.round(220 - s * 60)},${Math.round(233 - s * 100)},${Math.round(247 - s * 90)})`;
  }
  const s = (t - 0.5) * 2;
  return `rgb(${Math.round(160 + s * 82)},${Math.round(133 - s * 66)},${Math.round(157 - s * 101)})`;
}

function MatrixHeatmap({ countries, matrix, fmt = (v) => v.toFixed(2) }) {
  const [hovered, setHovered] = useState(null);
  const N = countries.length;
  const cs = Math.max(14, Math.min(32, Math.floor(660 / N)));
  const fs = Math.max(7, Math.min(10, cs * 0.38));

  if (!N) return <p className="empty-hint">No data available.</p>;

  return (
    <div className="heatmap-wrap">
      <div className="heatmap-scroll">
        <table className="heatmap-table" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ width: 80 }} />
              {countries.map((c, i) => (
                <th key={i} style={{ width: cs, height: 80, verticalAlign: 'bottom', fontSize: fs, fontWeight: 500, padding: 0 }}>
                  <div style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', whiteSpace: 'nowrap', maxHeight: 76, overflow: 'hidden', paddingBottom: 3 }}>
                    {c.length > 12 ? c.slice(0, 11) + '…' : c}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {countries.map((row, ri) => (
              <tr key={ri}>
                <td style={{ fontSize: fs, fontWeight: 500, paddingRight: 6, whiteSpace: 'nowrap', textAlign: 'right', maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {row.length > 10 ? row.slice(0, 9) + '…' : row}
                </td>
                {(matrix[ri] || []).map((val, ci) => {
                  const isHov = hovered && (hovered[0] === ri || hovered[1] === ci);
                  return (
                    <td
                      key={ci}
                      style={{
                        width: cs, height: cs,
                        background: heatColor(val),
                        opacity: hovered ? (isHov ? 1 : 0.35) : 1,
                        cursor: 'crosshair',
                        transition: 'opacity 0.1s',
                      }}
                      onMouseEnter={() => setHovered([ri, ci])}
                      onMouseLeave={() => setHovered(null)}
                      title={`${row} × ${countries[ci]}: ${fmt(val)}`}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hovered && matrix[hovered[0]] && (
        <div style={{ marginTop: 8, fontSize: '0.82rem', color: 'var(--ink)', fontWeight: 600 }}>
          {countries[hovered[0]]} × {countries[hovered[1]]}: {fmt(matrix[hovered[0]][hovered[1]])}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: '0.75rem' }}>
        <span>Low</span>
        <div style={{ height: 10, width: 160, background: 'linear-gradient(to right, rgb(220,233,247), rgb(247,208,138), rgb(242,107,56))', borderRadius: 4 }} />
        <span>High</span>
      </div>
    </div>
  );
}

export default function HeatmapsPage() {
  const [tab, setTab] = useState('similarity');
  const [simData, setSimData] = useState(null);
  const [tempData, setTempData] = useState(null);
  const [embData, setEmbData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  // Lazy-load per tab to avoid OOM
  useEffect(() => {
    if (tab === 'similarity' && !simData) {
      setLoading(true);
      getSimilarity().then((d) => { setSimData(d); setLoading(false); }).catch(() => setLoading(false));
    }
    if (tab === 'temporal' && !tempData) {
      setLoading(true);
      getVotingAgreementMatrix().then((d) => { setTempData(d); setLoading(false); }).catch(() => setLoading(false));
    }
    if (tab === 'positioning' && !embData) {
      setLoading(true);
      getEmbeddings2d().then((d) => { setEmbData(d); setLoading(false); }).catch(() => setLoading(false));
    }
  }, [tab]);

  // Similarity: API returns {countries: [...], matrix: [[...]]}
  const simReady = useMemo(() => {
    if (!simData?.countries?.length) return null;
    return { countries: simData.countries, matrix: simData.matrix };
  }, [simData]);

  // Temporal: API now returns {countries, matrix} pre-built on backend
  const tempReady = useMemo(() => {
    if (!tempData?.countries?.length) return null;
    return tempData;
  }, [tempData]);

  // Embeddings: API returns {countryName: [x, y]}
  const embPoints = useMemo(() => {
    if (!embData) return [];
    return Object.entries(embData)
      .map(([country, coords]) => ({ country, x: coords[0], y: coords[1] }))
      .filter((p) => !search || p.country.toLowerCase().includes(search.toLowerCase()));
  }, [embData, search]);

  const renderContent = () => {
    if (loading) return <div className="loading-inline">Loading data…</div>;

    if (tab === 'similarity') {
      if (!simReady) return <p className="empty-hint">Similarity data not available.</p>;
      return <MatrixHeatmap countries={simReady.countries} matrix={simReady.matrix} fmt={(v) => v.toFixed(3)} />;
    }

    if (tab === 'temporal') {
      if (!tempReady) return <p className="empty-hint">Temporal voting agreement data not available.</p>;
      return <MatrixHeatmap countries={tempReady.countries} matrix={tempReady.matrix} fmt={(v) => `${(v * 100).toFixed(0)}%`} />;
    }

    if (tab === 'positioning') {
      if (!embPoints.length) return <p className="empty-hint">Embedding data not available.</p>;
      return (
        <div>
          <input
            placeholder="Filter countries…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ marginBottom: '0.8rem', padding: '6px 12px', borderRadius: 8, border: '1.5px solid var(--border)', width: '100%', maxWidth: 260, fontSize: '0.85rem' }}
          />
          <ResponsiveContainer width="100%" height={520}>
            <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
              <XAxis dataKey="x" name="Dim 1" hide />
              <YAxis dataKey="y" name="Dim 2" hide />
              <ZAxis range={[45, 45]} />
              <Tooltip content={({ payload }) => payload?.[0] ? <div className="custom-tooltip">{payload[0].payload.country}</div> : null} />
              <Scatter data={embPoints} name="Countries">
                {embPoints.map((p, i) => (
                  <Cell key={i} fill={heatColor(((p.x || 0) + 3) / 6)} />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      );
    }
  };

  return (
    <div className="page-grid wide">
      <Panel title="Geopolitical Heatmaps" subtitle="Interactive similarity, UN voting alignment, and embedding visualizations across 144 countries.">
        <div className="chip-row" style={{ marginBottom: '1rem' }}>
          {TABS.map((t) => (
            <button key={t.id} type="button" className={tab === t.id ? 'chip active' : 'chip'} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
        {tab === 'similarity' && <p className="panel-hint" style={{ marginBottom: 12 }}>Cosine similarity of conflict profiles. <strong>Orange = highly similar</strong>, blue = dissimilar. Hover a cell for exact score.</p>}
        {tab === 'temporal' && <p className="panel-hint" style={{ marginBottom: 12 }}>Average UN General Assembly vote agreement (1989–2023). <strong>Orange = votes together often</strong>. Blocs cluster visibly.</p>}
        {tab === 'positioning' && <p className="panel-hint" style={{ marginBottom: 12 }}>2D PCA of conflict network embeddings. Countries close together share similar geopolitical positioning.</p>}
        {renderContent()}
      </Panel>
    </div>
  );
}
