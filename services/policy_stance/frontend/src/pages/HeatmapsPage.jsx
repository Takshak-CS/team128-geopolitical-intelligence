import { useEffect, useMemo, useState } from 'react';
import { Cell, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';

import { getAllianceBlocs, getEmbeddings2d, getSimilarity, getVotingAgreementMatrix } from '../api';
import Panel from '../components/Panel';

const TABS = [
  { id: 'similarity', label: 'Country Similarity' },
  { id: 'temporal', label: 'UN Voting Agreement' },
  { id: 'positioning', label: 'Geopolitical Positioning' },
];

const BLOC_COLORS = {
  'Western Bloc': '#ff8c42',
  'Russia+Allies': '#62d2a2',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#8aa5bf',
};
const ALL_BLOCS = Object.keys(BLOC_COLORS);

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
                    {c.length > 12 ? c.slice(0, 11) + '\u2026' : c}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {countries.map((row, ri) => (
              <tr key={ri}>
                <td style={{ fontSize: fs, fontWeight: 500, paddingRight: 6, whiteSpace: 'nowrap', textAlign: 'right', maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {row.length > 10 ? row.slice(0, 9) + '\u2026' : row}
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
                      title={`${row} x ${countries[ci]}: ${fmt(val)}`}
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
          {countries[hovered[0]]} x {countries[hovered[1]]}: {fmt(matrix[hovered[0]][hovered[1]])}
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

function PositioningScatter({ embeddings }) {
  const [search, setSearch] = useState('');
  const [blocFilter, setBlocFilter] = useState(null);

  const { byBloc, usedBlocs } = useMemo(() => {
    const grouped = {};
    ALL_BLOCS.forEach((b) => (grouped[b] = []));
    Object.entries(embeddings.coords || {}).forEach(([name, coords]) => {
      const bloc = embeddings.blocs?.[name] || 'Non-Aligned';
      (grouped[bloc] = grouped[bloc] || []).push({ name, x: coords[0], y: coords[1] });
    });
    return { byBloc: grouped, usedBlocs: ALL_BLOCS.filter((b) => grouped[b]?.length > 0) };
  }, [embeddings]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    const result = {};
    usedBlocs.forEach((b) => {
      if (blocFilter && b !== blocFilter) { result[b] = []; return; }
      result[b] = (byBloc[b] || []).filter((p) => !q || p.name.toLowerCase().includes(q));
    });
    return result;
  }, [byBloc, usedBlocs, search, blocFilter]);

  const total = Object.values(byBloc).reduce((s, arr) => s + arr.length, 0);
  if (!total) return <p className="empty-hint">Embedding data not available.</p>;

  return (
    <div>
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          placeholder="Search country..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ background: 'var(--surface-2)', border: '1px solid rgba(138,165,191,0.2)', color: 'var(--ink)', borderRadius: 6, padding: '4px 10px', fontSize: '0.82rem', width: 160 }}
        />
        {usedBlocs.map((b) => (
          <button
            key={b}
            type="button"
            onClick={() => setBlocFilter(blocFilter === b ? null : b)}
            style={{
              background: blocFilter === b ? BLOC_COLORS[b] : 'var(--surface-2)',
              color: blocFilter === b ? '#07131f' : 'var(--ink)',
              border: `1px solid ${BLOC_COLORS[b]}`,
              borderRadius: 20, padding: '3px 10px', fontSize: '0.75rem', cursor: 'pointer', fontWeight: 600,
            }}
          >
            {b}
          </button>
        ))}
      </div>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height={420}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 40, left: 20 }}>
            <XAxis
              dataKey="x"
              name="Dim 1"
              type="number"
              tick={false}
              axisLine={{ stroke: 'rgba(138,165,191,0.15)' }}
              tickLine={false}
              label={{ value: 'Embedding dimension 1', position: 'insideBottom', offset: -10, fill: '#8aa5bf', fontSize: 11 }}
            />
            <YAxis
              dataKey="y"
              name="Dim 2"
              type="number"
              tick={false}
              axisLine={{ stroke: 'rgba(138,165,191,0.15)' }}
              tickLine={false}
              label={{ value: 'Embedding dimension 2', angle: -90, position: 'insideLeft', offset: 15, fill: '#8aa5bf', fontSize: 11 }}
            />
            <ZAxis range={[55, 55]} />
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              content={({ payload }) => {
                const d = payload?.[0]?.payload;
                if (!d) return null;
                const bloc = embeddings.blocs?.[d.name] || 'Non-Aligned';
                return (
                  <div className="custom-tooltip">
                    <strong>{d.name}</strong>
                    <br />
                    <span style={{ color: BLOC_COLORS[bloc] || '#8aa5bf', fontSize: '0.75rem' }}>{bloc}</span>
                  </div>
                );
              }}
            />
            <Legend />
            {usedBlocs.map((bloc) => (
              <Scatter key={bloc} name={bloc} data={filtered[bloc] || []} fill={BLOC_COLORS[bloc]} opacity={0.85}>
                {(filtered[bloc] || []).map((_, index) => (
                  <Cell key={index} fill={BLOC_COLORS[bloc]} />
                ))}
              </Scatter>
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 6 }}>
        {total} countries plotted. Proximity = similar geopolitical profile. Colors = detected bloc.
      </p>
    </div>
  );
}

export default function HeatmapsPage() {
  const [tab, setTab] = useState('similarity');
  const [simData, setSimData] = useState(null);
  const [tempData, setTempData] = useState(null);
  const [embedData, setEmbedData] = useState(null);
  const [blocsData, setBlocsData] = useState({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (tab === 'similarity' && !simData) {
      setLoading(true);
      getSimilarity().then((d) => { setSimData(d); setLoading(false); }).catch(() => setLoading(false));
    }
    if (tab === 'temporal' && !tempData) {
      setLoading(true);
      getVotingAgreementMatrix().then((d) => { setTempData(d); setLoading(false); }).catch(() => setLoading(false));
    }
    if (tab === 'positioning' && !embedData) {
      setLoading(true);
      Promise.all([
        getEmbeddings2d().catch(() => ({})),
        getAllianceBlocs().catch(() => ({ country_to_bloc: {} })),
      ]).then(([coords, blocs]) => {
        setEmbedData({ coords, blocs: blocs.country_to_bloc || {} });
        setLoading(false);
      });
    }
  }, [tab]);

  const simReady = useMemo(() => {
    if (!simData?.countries?.length) return null;
    return { countries: simData.countries, matrix: simData.matrix };
  }, [simData]);

  const tempReady = useMemo(() => {
    if (!tempData?.countries?.length) return null;
    return tempData;
  }, [tempData]);

  const renderContent = () => {
    if (loading) return <div className="loading-inline">Loading data...</div>;

    if (tab === 'similarity') {
      if (!simReady) return <p className="empty-hint">Similarity data not available.</p>;
      return <MatrixHeatmap countries={simReady.countries} matrix={simReady.matrix} fmt={(v) => v.toFixed(3)} />;
    }

    if (tab === 'temporal') {
      if (!tempReady) return <p className="empty-hint">Temporal voting agreement data not available.</p>;
      return <MatrixHeatmap countries={tempReady.countries} matrix={tempReady.matrix} fmt={(v) => `${(v * 100).toFixed(0)}%`} />;
    }

    if (tab === 'positioning') {
      if (!embedData) return <p className="empty-hint">Embedding data not available.</p>;
      return <PositioningScatter embeddings={embedData} />;
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
        {tab === 'temporal' && <p className="panel-hint" style={{ marginBottom: 12 }}>Average UN General Assembly vote agreement (1989-2023). <strong>Orange = votes together often</strong>. Blocs cluster visibly.</p>}
        {tab === 'positioning' && <p className="panel-hint" style={{ marginBottom: 12 }}>2D PCA of conflict-network embeddings. Countries close together share similar geopolitical positioning. Filter by bloc or search a country.</p>}
        {renderContent()}
      </Panel>
    </div>
  );
}