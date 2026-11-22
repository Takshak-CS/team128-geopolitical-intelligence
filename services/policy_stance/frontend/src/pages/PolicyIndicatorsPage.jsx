import { useEffect, useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  PolarAngleAxis, PolarGrid, Radar, RadarChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

import { getIndicators, getIndicatorTrend } from '../api';
import Panel from '../components/Panel';

const COLORS = ['#ff8c42', '#62d2a2', '#e3a008', '#7fb7be', '#c77dff', '#f26b38', '#2a9d8f', '#457b9d', '#e76f51', '#a8dadc'];
const ALL_INDICATORS = [
  'Human Rights', 'Democracy Score', 'Corruption Index', 'Internet Users',
  'Trade Openness', 'CO2 per Capita', 'Mil. Spending', 'GDP per Capita',
  'Nuclear Warheads', 'Regime Type',
];
const RADAR_INDICATORS = ['Human Rights', 'Democracy Score', 'Corruption Index', 'Internet Users', 'Trade Openness'];
const DEFAULT_COUNTRIES = ['India', 'China', 'USA', 'Russia', 'Germany', 'Brazil'];

function ChipSelector({ label, allItems, selected, onToggle }) {
  const [query, setQuery] = useState('');
  const filtered = allItems.filter((i) => !query || i.toLowerCase().includes(query.toLowerCase()));
  return (
    <div style={{ marginBottom: '0.75rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
        <span className="control-label">{label}</span>
        <span className="chip-count">{selected.length} selected</span>
        <input
          placeholder="filter..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ background: 'var(--surface-2)', border: '1px solid rgba(138,165,191,0.2)', color: 'var(--ink)', borderRadius: 6, padding: '2px 8px', fontSize: '0.75rem', width: 120 }}
        />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', maxHeight: 80, overflowY: 'auto' }}>
        {filtered.map((item) => (
          <button key={item} type="button" className={selected.includes(item) ? 'chip active' : 'chip'}
            onClick={() => onToggle(item)} style={{ fontSize: '0.72rem', padding: '2px 8px' }}>
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function PolicyIndicatorsPage({ countries: countriesProp }) {
  const allCountryNames = useMemo(() => (countriesProp || []).map((c) => c.name).sort(), [countriesProp]);
  const [selected, setSelected] = useState(DEFAULT_COUNTRIES);
  const [trendIndicator, setTrendIndicator] = useState('Human Rights');
  const [indicators, setIndicators] = useState({});
  const [trend, setTrend] = useState(null);
  const [loadingInd, setLoadingInd] = useState(false);
  const [loadingTrend, setLoadingTrend] = useState(false);

  useEffect(() => {
    if (allCountryNames.length && !selected.some((c) => allCountryNames.includes(c))) {
      const defaults = DEFAULT_COUNTRIES.filter((c) => allCountryNames.includes(c));
      if (defaults.length >= 2) setSelected(defaults);
    }
  }, [allCountryNames]);

  useEffect(() => {
    if (!selected.length) return;
    setLoadingInd(true);
    getIndicators(selected).then((d) => { setIndicators(d); setLoadingInd(false); }).catch(() => setLoadingInd(false));
  }, [selected]);

  useEffect(() => {
    if (!selected.length) return;
    setLoadingTrend(true);
    getIndicatorTrend(selected, trendIndicator).then((d) => { setTrend(d); setLoadingTrend(false); }).catch(() => setLoadingTrend(false));
  }, [selected, trendIndicator]);

  const toggleCountry = (name) => setSelected((curr) =>
    curr.includes(name) ? curr.filter((c) => c !== name) : curr.length < 12 ? [...curr, name] : curr
  );

  const radarData = useMemo(() =>
    RADAR_INDICATORS.map((ind) => {
      const point = { indicator: ind };
      selected.forEach((c) => { point[c] = indicators[c]?.[ind]?.normalized ?? null; });
      return point;
    }), [indicators, selected]);

  const barData = useMemo(() =>
    selected.map((c) => {
      const v = indicators[c]?.[trendIndicator];
      return v ? { country: c.length > 12 ? c.slice(0, 10) + '..' : c, fullName: c, value: v.raw, year: v.year, unit: v.unit } : null;
    }).filter(Boolean).sort((a, b) => b.value - a.value),
    [indicators, selected, trendIndicator]);

  const trendData = useMemo(() => {
    if (!trend?.series) return [];
    const years = new Set();
    Object.values(trend.series).forEach((pts) => pts.forEach((p) => years.add(p.year)));
    return [...years].sort().map((yr) => {
      const row = { year: yr };
      Object.entries(trend.series).forEach(([c, pts]) => {
        const pt = pts.find((p) => p.year === yr);
        if (pt) row[c] = pt.value;
      });
      return row;
    });
  }, [trend]);

  const hasRadar = radarData.some((r) => selected.some((c) => r[c] != null));
  const activeIndicators = ALL_INDICATORS.filter((ind) => selected.some((c) => indicators[c]?.[ind]));

  return (
    <div className="page-grid wide">
      <Panel title="Policy Indicators" subtitle="Multi-dimensional policy stance: democracy, human rights, military, trade, climate and more. Sources: OWID, V-Dem, SIPRI, TI.">
        <ChipSelector label="Countries" allItems={allCountryNames.length ? allCountryNames : DEFAULT_COUNTRIES} selected={selected} onToggle={toggleCountry} />
        <div>
          <span className="control-label" style={{ marginRight: '0.5rem' }}>Indicator focus</span>
          <select value={trendIndicator} onChange={(e) => setTrendIndicator(e.target.value)}
            style={{ background: 'var(--surface-2)', color: 'var(--ink)', border: '1px solid rgba(138,165,191,0.2)', borderRadius: 6, padding: '4px 8px', fontSize: '0.82rem' }}>
            {ALL_INDICATORS.map((ind) => <option key={ind} value={ind}>{ind}</option>)}
          </select>
        </div>
        {loadingInd && <div className="loading-inline" style={{ marginTop: 8 }}>Fetching indicators...</div>}
      </Panel>

      {hasRadar && (
        <Panel title="Policy Profile Radar" subtitle="Normalized 0-100. Democracy, human rights, corruption control, internet access, trade openness. Outer = better.">
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={380}>
              <RadarChart data={radarData} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
                <PolarGrid stroke="rgba(138,165,191,0.15)" />
                <PolarAngleAxis dataKey="indicator" tick={{ fill: '#8aa5bf', fontSize: 11 }} />
                {selected.map((c, i) => (
                  <Radar key={c} name={c} dataKey={c} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.08} strokeWidth={2} dot={false} />
                ))}
                <Legend />
                <Tooltip formatter={(v) => [v != null ? v.toFixed(1) : 'N/A']} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      )}

      <Panel title={`${trendIndicator} — Trend Over Time`} subtitle={trend?.unit ? `Unit: ${trend.unit}` : 'Select indicator above.'}>
        {loadingTrend
          ? <div className="loading-inline">Loading...</div>
          : trendData.length === 0
            ? <p className="empty-hint">No trend data for this selection.</p>
            : (
              <div className="chart-box">
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={trendData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(138,165,191,0.08)" />
                    <XAxis dataKey="year" tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} />
                    <YAxis tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} width={55} />
                    <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid rgba(138,165,191,0.2)', borderRadius: 8, fontSize: '0.8rem' }} />
                    <Legend />
                    {selected.map((c, i) => trend?.series?.[c] ? (
                      <Line key={c} type="monotone" dataKey={c} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} connectNulls />
                    ) : null)}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
      </Panel>

      {barData.length > 0 && (
        <Panel title={`${trendIndicator} — Country Comparison`} subtitle={`Latest available year. ${barData[0]?.unit || ''}`}>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={barData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(138,165,191,0.08)" />
                <XAxis dataKey="country" tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} />
                <YAxis tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} width={55} />
                <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid rgba(138,165,191,0.2)', borderRadius: 8, fontSize: '0.8rem' }}
                  formatter={(v, _n, props) => [typeof v === 'number' ? v.toFixed(2) : v, `${props?.payload?.fullName || ''} (${props?.payload?.year || ''})`]} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {barData.map((entry, index) => (
                    <Cell key={index} fill={COLORS[selected.indexOf(entry.fullName) % COLORS.length] || COLORS[0]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      )}

      {activeIndicators.length > 0 && (
        <Panel title="Indicator Snapshot" subtitle="Latest values per country across all policy dimensions.">
          <div className="table-wrap compact-table">
            <table>
              <thead>
                <tr>
                  <th>Country</th>
                  {activeIndicators.map((ind) => <th key={ind} title={ind}>{ind.length > 12 ? ind.slice(0, 10) + '..' : ind}</th>)}
                </tr>
              </thead>
              <tbody>
                {selected.map((c) => {
                  const row = indicators[c] || {};
                  return (
                    <tr key={c}>
                      <td style={{ fontWeight: 600 }}>{c}</td>
                      {activeIndicators.map((ind) => {
                        const v = row[ind];
                        return (
                          <td key={ind} title={v ? `${v.raw} (${v.year})` : 'N/A'}
                            style={{ background: v ? `rgba(255,140,66,${Math.min(0.45, v.normalized / 220)})` : undefined }}>
                            {v ? v.raw.toFixed(1) : '—'}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}