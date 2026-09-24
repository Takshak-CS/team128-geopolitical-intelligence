import { useEffect, useMemo, useRef, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { getForecast, getGraph, getTimeline } from '../api';
import ForcePreview from '../components/ForcePreview';
import Panel from '../components/Panel';

const COLORS = ['#f26b38', '#0f7b8c', '#e3a008', '#7fb7be', '#f7d08a'];

function CountryPicker({ all, selected, onToggle }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [dropPos, setDropPos] = useState({ top: 0, left: 0, width: 280 });
  const btnRef = useRef(null);
  const dropRef = useRef(null);

  const filtered = useMemo(() => all.filter((n) => !query || n.toLowerCase().includes(query.toLowerCase())), [all, query]);

  const openDrop = () => {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setDropPos({ top: r.bottom + 4, left: r.left, width: Math.max(280, r.width) });
    }
    setQuery('');
    setOpen(true);
  };

  useEffect(() => {
    const h = (e) => { if (!dropRef.current?.contains(e.target) && !btnRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
      {selected.map((n, i) => (
        <button key={n} type="button" className="chip active" style={{ borderColor: COLORS[i % COLORS.length] }} onClick={() => onToggle(n)}>
          {n} ✕
        </button>
      ))}
      <button ref={btnRef} type="button" className="chip" onClick={openDrop} style={{ borderStyle: 'dashed' }}>+ Add country</button>
      {open && (
        <div ref={dropRef} style={{ position: 'fixed', top: dropPos.top, left: dropPos.left, width: dropPos.width, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.16)', zIndex: 9999 }}>
          <input autoFocus placeholder="Search country…" value={query} onChange={(e) => setQuery(e.target.value)}
            style={{ width: '100%', border: 'none', borderBottom: '1px solid var(--border)', padding: '8px 12px', fontSize: '0.85rem', outline: 'none', background: 'var(--surface)' }} />
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {filtered.map((n) => (
              <div key={n} onClick={() => { onToggle(n); }}
                style={{ padding: '7px 14px', cursor: 'pointer', fontWeight: selected.includes(n) ? 700 : 400, background: selected.includes(n) ? 'rgba(242,107,56,0.08)' : undefined, fontSize: '0.85rem' }}
                onMouseEnter={(e) => e.currentTarget.style.background = selected.includes(n) ? 'rgba(242,107,56,0.08)' : 'rgba(0,0,0,0.04)'}
                onMouseLeave={(e) => e.currentTarget.style.background = selected.includes(n) ? 'rgba(242,107,56,0.08)' : ''}>
                {selected.includes(n) ? '✓ ' : ''}{n}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TemporalPage({ countries, status, blocMap }) {
  const [selectedCountries, setSelectedCountries] = useState([]);
  const [metric, setMetric] = useState('conflicts');
  const [year, setYear] = useState(2020);
  const [playing, setPlaying] = useState(false);
  const [timeline, setTimeline] = useState({ series: [], global_deaths: [], new_conflicts: [] });
  const [forecast, setForecast] = useState({ forecasts: [], metric: 'conflicts' });
  const [graph, setGraph] = useState({ nodes: [], edges: [] });

  const allNames = useMemo(() => countries.map((c) => c.name).sort(), [countries]);

  useEffect(() => {
    if (!countries.length || selectedCountries.length) return;
    const defaults = ['India', 'USA', 'Russia', 'China', 'Pakistan'];
    const names = countries.map((c) => c.name);
    const initial = defaults.filter((n) => names.includes(n));
    setSelectedCountries(initial.length >= 2 ? initial : names.slice(0, 3));
  }, [countries]);

  useEffect(() => {
    if (!selectedCountries.length) return;
    getTimeline(selectedCountries, metric).then(setTimeline).catch(() => setTimeline({ series: [], global_deaths: [], new_conflicts: [] }));
    getForecast(selectedCountries, metric).then(setForecast).catch(() => setForecast({ forecasts: [], metric }));
  }, [selectedCountries, metric]);

  useEffect(() => {
    if (!status.ready) return;
    getGraph(year).then(setGraph).catch(() => {});
  }, [status.ready, year]);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setYear((y) => y >= 2025 ? 1989 : y + 1), 1200);
    return () => clearInterval(t);
  }, [playing]);

  const toggleCountry = (name) => {
    setSelectedCountries((cur) => {
      if (cur.includes(name)) return cur.filter((n) => n !== name);
      if (cur.length >= 6) return cur; // max 6 lines
      return [...cur, name];
    });
  };

  const lineData = useMemo(() => {
    const map = new Map();
    timeline.series.forEach((s) => s.values.forEach((item) => {
      const row = map.get(item.year) || { year: item.year };
      row[s.country] = item.value;
      map.set(item.year, row);
    }));
    return [...map.values()].sort((a, b) => a.year - b.year);
  }, [timeline]);

  const forecastCharts = useMemo(() => forecast.forecasts.map((f, i) => ({
    ...f, color: COLORS[i % COLORS.length],
    allPoints: [
      ...f.history.map((h) => ({ year: h.year, actual: h.actual })),
      ...f.forecast.map((p) => ({ year: p.year, forecast: p.forecast })),
    ],
  })), [forecast]);

  return (
    <div className="page-grid wide">
      <Panel title="Temporal Analysis" subtitle="Track how conflict intensity, death toll, and alignment evolve over time. Select up to 6 countries.">
        <div className="control-row wrap" style={{ gap: 12 }}>
          <select value={metric} onChange={(e) => setMetric(e.target.value)}>
            <option value="conflicts">Conflict Count (events/year)</option>
            <option value="intensity">Avg. Lethality (deaths per conflict)</option>
            <option value="deaths">Total Deaths</option>
          </select>
          <CountryPicker all={allNames} selected={selectedCountries} onToggle={toggleCountry} />
        </div>
        {lineData.length > 0 ? (
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={lineData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="year" />
                <YAxis />
                <Tooltip />
                <Legend />
                {timeline.series.map((s, i) => (
                  <Line key={s.country} type="monotone" dataKey={s.country} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={2.5} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : <p className="empty-hint">Select countries above to plot their conflict timeline.</p>}
      </Panel>

      <Panel title="Global Conflict Deaths" subtitle="Aggregate battle-related deaths per year across all conflicts.">
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={timeline.global_deaths}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" />
              <YAxis />
              <Tooltip />
              <Area type="monotone" dataKey="deaths" stroke="#f26b38" fill="#f26b38" fillOpacity={0.35} name="Deaths" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="New Conflicts Started" subtitle="Unique conflict events first observed in each year.">
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={timeline.new_conflicts}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#0f7b8c" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      {forecastCharts.length > 0 && (
        <Panel title={`Conflict Forecast 2026–2030 (${metric})`} subtitle="Linear trend from last 15 years. Solid = historical, dashed = projected.">
          <div className="forecast-grid">
            {forecastCharts.map((f) => (
              <div key={f.country} className="forecast-card">
                <div className="forecast-header">
                  <strong>{f.country}</strong>
                  <span className={`trend-badge trend-${f.trend}`}>{f.trend === 'rising' ? '↑ Rising' : f.trend === 'falling' ? '↓ Falling' : '→ Stable'}</span>
                </div>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={f.allPoints}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="year" />
                    <YAxis />
                    <Tooltip />
                    <ReferenceLine x={2025} stroke="#aaa" strokeDasharray="4 4" label={{ value: 'Now', position: 'top', fontSize: 11 }} />
                    <Line type="monotone" dataKey="actual" stroke={f.color} strokeWidth={2} dot={false} name="Historical" connectNulls />
                    <Line type="monotone" dataKey="forecast" stroke={f.color} strokeWidth={2} strokeDasharray="6 3" dot={{ r: 4 }} name="Forecast" connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="Animated Year Graph" subtitle="Watch the conflict network evolve. Hit Play or drag the slider.">
        <div className="control-row wrap">
          <button type="button" className="action-link" onClick={() => setPlaying((p) => !p)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
          <strong style={{ minWidth: 44 }}>{year}</strong>
          <input type="range" min="1989" max="2025" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ flex: 1 }} />
        </div>
        <ForcePreview graph={graph} height={360} blocMap={blocMap} minNodes={40} />
      </Panel>
    </div>
  );
}
