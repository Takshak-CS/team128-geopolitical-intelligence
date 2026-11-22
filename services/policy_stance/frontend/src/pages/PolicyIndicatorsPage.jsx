import { useEffect, useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  PolarAngleAxis, PolarGrid, Radar, RadarChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';

import {
  getGovernanceScatter, getGovernanceTrajectory,
  getIndicatorCorrelation, getIndicators, getIndicatorTrend, getRiskScore,
} from '../api';
import Panel from '../components/Panel';

const COLORS = ['#ff8c42', '#62d2a2', '#e3a008', '#7fb7be', '#c77dff', '#f26b38', '#2a9d8f', '#457b9d', '#e76f51', '#a8dadc'];
const BLOC_COLORS = { 'Western Bloc': '#ff8c42', 'Russia+Allies': '#62d2a2', 'China-Centered Bloc': '#e3a008', 'Non-Aligned': '#8aa5bf' };
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
        <input placeholder="filter..." value={query} onChange={(e) => setQuery(e.target.value)}
          style={{ background: 'var(--surface-2)', border: '1px solid rgba(138,165,191,0.2)', color: 'var(--ink)', borderRadius: 6, padding: '2px 8px', fontSize: '0.75rem', width: 120 }} />
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

function RiskGauge({ score }) {
  const color = score > 70 ? '#f26b38' : score > 45 ? '#e3a008' : '#62d2a2';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${score}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.4s' }} />
      </div>
      <span style={{ fontSize: '0.82rem', fontWeight: 700, color, minWidth: 36 }}>{score}</span>
    </div>
  );
}

export default function PolicyIndicatorsPage({ countries: countriesProp }) {
  const allCountryNames = useMemo(() => (countriesProp || []).map((c) => c.name).sort(), [countriesProp]);
  const [selected, setSelected] = useState(DEFAULT_COUNTRIES);
  const [trendIndicator, setTrendIndicator] = useState('Human Rights');
  const [indicators, setIndicators] = useState({});
  const [trend, setTrend] = useState(null);
  const [riskData, setRiskData] = useState(null);
  const [scatterData, setScatterData] = useState(null);
  const [trajectory, setTrajectory] = useState(null);
  const [correlation, setCorrelation] = useState(null);
  const [activeTab, setActiveTab] = useState('profile');

  useEffect(() => {
    if (allCountryNames.length && !selected.some((c) => allCountryNames.includes(c))) {
      const defaults = DEFAULT_COUNTRIES.filter((c) => allCountryNames.includes(c));
      if (defaults.length >= 2) setSelected(defaults);
    }
  }, [allCountryNames]);

  useEffect(() => {
    if (!selected.length) return;
    getIndicators(selected).then(setIndicators).catch(() => {});
  }, [selected]);

  useEffect(() => {
    if (!selected.length) return;
    getIndicatorTrend(selected, trendIndicator).then(setTrend).catch(() => {});
  }, [selected, trendIndicator]);

  useEffect(() => {
    const load = (fn, setter, retries = 4) => {
      fn().then(setter).catch(() => {
        if (retries > 0) setTimeout(() => load(fn, setter, retries - 1), 4000);
      });
    };
    load(getRiskScore, setRiskData);
    load(getGovernanceScatter, setScatterData);
    load(getIndicatorCorrelation, setCorrelation);
  }, []);

  useEffect(() => {
    if (!selected.length) return;
    getGovernanceTrajectory(selected, 10).then(setTrajectory).catch(() => {});
  }, [selected]);

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
    }).filter(Boolean).sort((a, b) => b.value - a.value), [indicators, selected, trendIndicator]);

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

  // Risk score: show top 20 riskiest + selected countries
  const riskRows = useMemo(() => {
    if (!riskData?.scores) return [];
    return riskData.scores.slice(0, 25);
  }, [riskData]);

  // Scatter: only show countries with conflict data and democracy data
  const scatterPoints = useMemo(() => {
    if (!scatterData?.points) return {};
    const grouped = {};
    scatterData.points
      .filter((p) => p.democracy > 0 || p.conflicts_per_year > 0)
      .forEach((p) => {
        const bloc = p.bloc || 'Non-Aligned';
        (grouped[bloc] = grouped[bloc] || []).push(p);
      });
    return grouped;
  }, [scatterData]);

  // Trajectory: sparkline-like change data
  const trajectoryRows = useMemo(() => {
    if (!trajectory) return [];
    return selected.map((c) => {
      const data = trajectory[c] || {};
      return { country: c, ...data };
    });
  }, [trajectory, selected]);

  const hasRadar = radarData.some((r) => selected.some((c) => r[c] != null));
  const activeIndicators = ALL_INDICATORS.filter((ind) => selected.some((c) => indicators[c]?.[ind]));
  const TABS = [
    { id: 'profile', label: 'Country Profile' },
    { id: 'risk', label: 'Risk Score' },
    { id: 'nexus', label: 'Democracy-Conflict Nexus' },
    { id: 'trajectory', label: 'Governance Trajectory' },
    { id: 'correlation', label: 'Indicator Correlations' },
  ];

  return (
    <div className="page-grid wide">
      <Panel title="Policy Indicators" subtitle="Multi-dimensional policy stance: democracy, human rights, military, trade, climate and more. Sources: OWID, V-Dem, SIPRI, TI.">
        <ChipSelector label="Countries" allItems={allCountryNames.length ? allCountryNames : DEFAULT_COUNTRIES} selected={selected} onToggle={toggleCountry} />
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
          {TABS.map((t) => (
            <button key={t.id} type="button" onClick={() => setActiveTab(t.id)}
              style={{ padding: '5px 14px', borderRadius: 20, fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer', border: `1px solid ${activeTab === t.id ? '#ff8c42' : 'rgba(138,165,191,0.3)'}`, background: activeTab === t.id ? 'rgba(255,140,66,0.12)' : 'var(--surface-2)', color: activeTab === t.id ? '#ff8c42' : 'var(--ink)' }}>
              {t.label}
            </button>
          ))}
        </div>
      </Panel>

      {activeTab === 'profile' && (
        <>
          {hasRadar && (
            <Panel title="Policy Profile Radar" subtitle="Normalized 0-100 across democracy, human rights, corruption control, internet, trade. Outer = better governance.">
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
          <Panel title="Trend Over Time" subtitle="Select an indicator to track it over time for chosen countries.">
            <div style={{ marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <span className="control-label" style={{ marginRight: '0.25rem' }}>Indicator</span>
              <select value={trendIndicator} onChange={(e) => setTrendIndicator(e.target.value)}
                style={{ background: 'var(--surface-2)', color: 'var(--ink)', border: '1px solid rgba(138,165,191,0.2)', borderRadius: 6, padding: '4px 8px', fontSize: '0.82rem' }}>
                {ALL_INDICATORS.map((ind) => <option key={ind} value={ind}>{ind}</option>)}
              </select>
              {trend?.unit && (
                <span style={{ fontSize: '0.78rem', color: '#ff8c42', background: 'rgba(255,140,66,0.1)', borderRadius: 6, padding: '2px 8px' }}>
                  Unit: {trend.unit}
                </span>
              )}
              {trend?.higher_better != null && (
                <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                  {trend.higher_better ? '↑ higher = better' : '↓ lower = better'}
                </span>
              )}
            </div>
            {trendIndicator === 'Corruption Index' && (
              <div style={{ fontSize: '0.75rem', color: '#e3a008', background: 'rgba(227,160,8,0.08)', borderRadius: 6, padding: '5px 10px', marginBottom: '0.5rem' }}>
                CPI (Corruption Perceptions Index): 100 = very clean/transparent, 0 = highly corrupt. Germany ~80 = low corruption. India ~40 = higher corruption. This is correct.
              </div>
            )}
            {trendIndicator === 'Internet Users' && (
              <div style={{ fontSize: '0.75rem', color: '#62d2a2', background: 'rgba(98,210,162,0.08)', borderRadius: 6, padding: '5px 10px', marginBottom: '0.5rem' }}>
                % of total population with internet access. Germany ~91 = 91% of Germans use internet. India ~55 = 55% of India's population. Not an absolute count.
              </div>
            )}
            {trendIndicator === 'Democracy Score' && (
              <div style={{ fontSize: '0.75rem', color: '#7fb7be', background: 'rgba(127,183,190,0.08)', borderRadius: 6, padding: '5px 10px', marginBottom: '0.5rem' }}>
                V-Dem electoral democracy index: 0–3 scale (0 = closed autocracy, 3 = liberal democracy).
              </div>
            )}
            {trendData.length === 0
              ? <p className="empty-hint">No trend data for this selection.</p>
              : (
                <div className="chart-box">
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart data={trendData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(138,165,191,0.08)" />
                      <XAxis dataKey="year" tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} />
                      <YAxis tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} width={55}
                        label={trend?.unit ? { value: trend.unit, angle: -90, position: 'insideLeft', offset: 15, fill: '#8aa5bf', fontSize: 9 } : undefined} />
                      <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid rgba(138,165,191,0.2)', borderRadius: 8, fontSize: '0.8rem' }}
                        formatter={(v, name) => [typeof v === 'number' ? `${v.toFixed(2)} ${trend?.unit || ''}` : v, name]} />
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
            <Panel title={`${trendIndicator} - Country Comparison`} subtitle={`Latest available year. ${barData[0]?.unit || ''}`}>
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
                                {v ? v.raw.toFixed(1) : '-'}
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
        </>
      )}

      {activeTab === 'risk' && (
        <Panel title="Composite Conflict Risk Score" subtitle="Weighted composite 0-100. Inputs: conflict frequency (30%), deaths (20%), democracy inverse (20%), human rights inverse (20%), corruption inverse (10%). Higher = riskier.">
          {!riskRows.length
            ? <p className="empty-hint">Loading risk scores...</p>
            : (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '0.75rem' }}>
                  {riskRows.map((r) => {
                    const isSelected = selected.includes(r.country);
                    return (
                      <div key={r.country} style={{ background: isSelected ? 'rgba(255,140,66,0.08)' : 'var(--surface-2)', borderRadius: 8, padding: '8px 12px', border: isSelected ? '1px solid rgba(255,140,66,0.3)' : '1px solid transparent' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: '0.82rem', fontWeight: isSelected ? 700 : 400 }}>{r.country}</span>
                          <span style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>#{riskRows.indexOf(r) + 1}</span>
                        </div>
                        <RiskGauge score={r.score} />
                        <div style={{ display: 'flex', gap: 6, marginTop: 5, flexWrap: 'wrap' }}>
                          {Object.entries(r.components || {}).map(([k, v]) => (
                            <span key={k} style={{ fontSize: '0.65rem', color: 'var(--muted)', background: 'var(--surface)', borderRadius: 4, padding: '1px 5px' }}>{k.replace(/_inv/, ' inv').replace(/_/g, ' ')}: {v}</span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>Showing top 20 highest-risk countries + selected. Score components shown as normalized 0-100.</p>
              </div>
            )}
        </Panel>
      )}

      {activeTab === 'nexus' && (
        <Panel title="Democracy-Conflict Nexus" subtitle="Bubble chart: X = democracy score (higher=more democratic), Y = avg conflict events/year, bubble size = GDP per capita. Color = geopolitical bloc. Shows structural link between governance and conflict.">
          {!scatterData
            ? <p className="empty-hint">Loading scatter data...</p>
            : (
              <div className="chart-box">
                <ResponsiveContainer width="100%" height={440}>
                  <ScatterChart margin={{ top: 10, right: 30, bottom: 30, left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(138,165,191,0.08)" />
                    <XAxis dataKey="democracy" name="Democracy Score" type="number" tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false}
                      label={{ value: 'Democracy Score (0-3)', position: 'insideBottom', offset: -15, fill: '#8aa5bf', fontSize: 11 }} />
                    <YAxis dataKey="conflicts_per_year" name="Conflicts/yr" type="number" tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false} width={55}
                      label={{ value: 'Avg conflicts/yr', angle: -90, position: 'insideLeft', offset: 15, fill: '#8aa5bf', fontSize: 11 }} />
                    <ZAxis dataKey="gdp" range={[20, 400]} name="GDP/capita" />
                    <Tooltip cursor={{ strokeDasharray: '3 3' }}
                      content={({ payload }) => {
                        const d = payload?.[0]?.payload;
                        if (!d) return null;
                        return (
                          <div className="custom-tooltip">
                            <strong>{d.country}</strong>
                            <div style={{ fontSize: '0.75rem', color: '#8aa5bf' }}>{d.bloc}</div>
                            <div style={{ fontSize: '0.75rem' }}>Democracy: {d.democracy?.toFixed(2)}</div>
                            <div style={{ fontSize: '0.75rem' }}>Conflicts/yr: {d.conflicts_per_year?.toFixed(1)}</div>
                            <div style={{ fontSize: '0.75rem' }}>GDP/cap: ${d.gdp?.toLocaleString()}</div>
                          </div>
                        );
                      }} />
                    <Legend />
                    {Object.entries(scatterPoints).map(([bloc, pts]) => (
                      <Scatter key={bloc} name={bloc} data={pts} fill={BLOC_COLORS[bloc] || '#8aa5bf'} opacity={0.75} />
                    ))}
                  </ScatterChart>
                </ResponsiveContainer>
                <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 6 }}>
                  Bubble size = GDP per capita. Hover for details. Trend: countries with lower democracy scores tend to have higher conflict rates.
                </p>
              </div>
            )}
        </Panel>
      )}

      {activeTab === 'trajectory' && (
        <Panel title="Governance Trajectory (10-year change)" subtitle="How selected countries changed on key governance indicators from ~2013 to ~2023. Green = improvement, red = deterioration.">
          {!trajectory
            ? <p className="empty-hint">Loading trajectory data...</p>
            : trajectoryRows.length === 0
              ? <p className="empty-hint">No trajectory data for selection.</p>
              : (
                <div className="table-wrap">
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: 'left', padding: '6px 10px', fontSize: '0.8rem' }}>Country</th>
                        {['Human Rights', 'Democracy Score', 'Corruption Index', 'Internet Users', 'Trade Openness', 'CO2 per Capita', 'GDP per Capita'].map((ind) => (
                          <th key={ind} title={ind} style={{ padding: '6px 6px', fontSize: '0.75rem', textAlign: 'center' }}>
                            {ind.length > 10 ? ind.slice(0, 9) + '.' : ind}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {trajectoryRows.map((row) => (
                        <tr key={row.country}>
                          <td style={{ padding: '6px 10px', fontWeight: 600, fontSize: '0.82rem' }}>{row.country}</td>
                          {['Human Rights', 'Democracy Score', 'Corruption Index', 'Internet Users', 'Trade Openness', 'CO2 per Capita', 'GDP per Capita'].map((ind) => {
                            const d = row[ind];
                            if (!d) return <td key={ind} style={{ textAlign: 'center', padding: '4px 6px', fontSize: '0.75rem', color: 'var(--muted)' }}>-</td>;
                            const pct = d.change_pct;
                            const isBad = ind === 'CO2 per Capita';
                            const improved = isBad ? pct < 0 : pct > 0;
                            const color = Math.abs(pct) < 2 ? 'var(--muted)' : improved ? '#62d2a2' : '#f26b38';
                            return (
                              <td key={ind} style={{ textAlign: 'center', padding: '4px 6px' }}
                                title={`${d.start_year}: ${d.start} -> ${d.end_year}: ${d.end}`}>
                                <span style={{ fontSize: '0.78rem', fontWeight: 600, color }}>
                                  {pct > 0 ? '+' : ''}{pct}%
                                </span>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 8 }}>Green = improvement, red = deterioration over ~10 years. CO2 per capita: green means reduction (improvement). Hover for exact values.</p>
                </div>
              )}
        </Panel>
      )}

      {activeTab === 'correlation' && (
        <Panel title="Indicator-Conflict Correlations" subtitle="Pearson correlation between each governance indicator and conflict frequency per country (cross-sectional, all countries). Shows which indicators statistically link to conflict risk.">
          {!correlation
            ? <p className="empty-hint">Loading correlation data...</p>
            : correlation.correlations?.length === 0
              ? <p className="empty-hint">Insufficient data to compute correlations.</p>
              : (
                <>
                  <div className="chart-box">
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart
                        data={[...(correlation.correlations || [])].sort((a, b) => a.r - b.r)}
                        layout="vertical"
                        margin={{ top: 5, right: 40, bottom: 5, left: 130 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(138,165,191,0.08)" />
                        <XAxis type="number" domain={[-1, 1]} tick={{ fill: '#8aa5bf', fontSize: 10 }} axisLine={{ stroke: 'rgba(138,165,191,0.2)' }} tickLine={false}
                          label={{ value: 'Pearson r', position: 'insideBottom', offset: -2, fill: '#8aa5bf', fontSize: 11 }} />
                        <YAxis type="category" dataKey="indicator" tick={{ fill: '#8aa5bf', fontSize: 10 }} width={125} />
                        <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid rgba(138,165,191,0.2)', borderRadius: 8, fontSize: '0.8rem' }}
                          formatter={(v, _n, props) => [v.toFixed(4), props?.payload?.interpretation || '']} />
                        <Bar dataKey="r" radius={[0, 4, 4, 0]}>
                          {(correlation.correlations || []).map((entry, i) => (
                            <Cell key={i} fill={entry.r > 0 ? '#f26b38' : '#62d2a2'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.75rem' }}>
                    {(correlation.correlations || []).map((c) => (
                      <div key={c.indicator} style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '8px 12px', fontSize: '0.78rem' }}>
                        <div style={{ fontWeight: 700, marginBottom: 2 }}>{c.indicator}</div>
                        <div style={{ color: c.r > 0 ? '#f26b38' : '#62d2a2' }}>r = {c.r.toFixed(3)} ({c.direction})</div>
                        <div style={{ color: 'var(--muted)', marginTop: 2 }}>{c.interpretation}</div>
                        <div style={{ color: 'var(--muted)', fontSize: '0.7rem' }}>n = {c.n} countries</div>
                      </div>
                    ))}
                  </div>
                  <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 8 }}>Orange bars = positive correlation with conflict (more of this indicator = more conflicts). Green = negative (more = fewer conflicts). Based on cross-sectional comparison across all countries.</p>
                </>
              )}
        </Panel>
      )}
    </div>
  );
}