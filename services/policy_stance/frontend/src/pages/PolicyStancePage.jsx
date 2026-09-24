import { useEffect, useMemo, useRef, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { getPolicyStance } from '../api';
import Panel from '../components/Panel';

const COLORS = ['#f26b38', '#0f7b8c', '#e3a008', '#7fb7be', '#f7d08a', '#a8dadc', '#e76f51', '#457b9d', '#2a9d8f', '#c77dff'];

function AgreementMiniGraph({ network, countries }) {
  const nodes = network?.nodes || [];
  const edges = network?.edges || [];
  if (!nodes.length) return <p className="empty-hint">Select countries and issues to see agreement links.</p>;

  const W = 400, H = 340, R = 130, cx = W / 2, cy = H / 2;
  const pos = Object.fromEntries(nodes.map((node, i) => {
    const angle = (Math.PI * 2 * i) / nodes.length - Math.PI / 2;
    return [node.id, { x: cx + Math.cos(angle) * R, y: cy + Math.sin(angle) * R }];
  }));
  const maxW = Math.max(...edges.map((e) => e.weight || 1), 1);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="agreement-svg">
      {edges.map((edge, i) => {
        const s = pos[edge.source], t = pos[edge.target];
        if (!s || !t) return null;
        const opacity = 0.2 + 0.7 * ((edge.weight || 1) / maxW);
        return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="#f26b38" strokeOpacity={opacity} strokeWidth={Math.max(1, 3 * ((edge.weight || 1) / maxW))} />;
      })}
      {nodes.map((node) => {
        const p = pos[node.id];
        if (!p) return null;
        const label = node.id.length > 6 ? node.id.slice(0, 6) : node.id;
        const color = COLORS[countries.indexOf(node.id) % COLORS.length] || '#0f7b8c';
        return (
          <g key={node.id} transform={`translate(${p.x},${p.y})`}>
            <circle r={13} fill={color} />
            <text textAnchor="middle" y={4} fontSize={9} fill="#fff" fontWeight="bold">{label}</text>
            <text textAnchor="middle" y={27} fontSize={9} fill="var(--ink)" opacity={0.85}>{node.id}</text>
          </g>
        );
      })}
    </svg>
  );
}

function SearchableChipList({ label, allItems, selected, onToggle }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [dropPos, setDropPos] = useState({ top: 0, left: 0, width: 300 });
  const btnRef = useRef(null);
  const dropRef = useRef(null);

  const filtered = allItems.filter((item) => !query || item.toLowerCase().includes(query.toLowerCase()));

  const openDropdown = () => {
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setDropPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(300, rect.width) });
    }
    setOpen(true);
  };

  useEffect(() => {
    const handler = (e) => {
      if (dropRef.current && dropRef.current.contains(e.target)) return;
      if (btnRef.current && btnRef.current.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="searchable-chip-section">
      <div className="control-label-row">
        <span className="control-label">{label}</span>
        <span className="chip-count">{selected.length} selected</span>
      </div>
      <div className="chip-row selected-chips">
        {selected.map((item) => (
          <button key={item} type="button" className="chip active" onClick={() => onToggle(item)}>{item} ✕</button>
        ))}
        <button ref={btnRef} type="button" className="chip add-btn" onClick={openDropdown}>+ Add</button>
      </div>
      {open && (
        <div
          ref={dropRef}
          className="chip-dropdown"
          style={{ position: 'fixed', top: dropPos.top, left: dropPos.left, width: dropPos.width, zIndex: 9999 }}
        >
          <input autoFocus placeholder={`Search ${label.toLowerCase()}…`} value={query} onChange={(e) => setQuery(e.target.value)} className="chip-search-input" />
          <div className="chip-dropdown-list">
            {filtered.map((item) => (
              <div key={item} className={`chip-option${selected.includes(item) ? ' selected' : ''}`} onClick={() => { onToggle(item); }}>
                {selected.includes(item) ? '✓ ' : ''}{item}
              </div>
            ))}
            {filtered.length === 0 && <div className="chip-option muted">No matches</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function PolicyStancePage({ countries, issues, topics }) {
  const [selectedCountries, setSelectedCountries] = useState([]);
  const [selectedIssues, setSelectedIssues] = useState([]);
  const [selectedTopic, setSelectedTopic] = useState('');
  const [payload, setPayload] = useState({ countries: [], issues: [], matrix: [], agreement_network: { nodes: [], edges: [] }, rankings: {}, temporal: {}, resolution_votes: [] });
  const [loading, setLoading] = useState(false);

  const allCountryNames = useMemo(() => countries.map((c) => c.name).sort(), [countries]);
  const allIssueNames = useMemo(() => issues.map((i) => i.issue).sort(), [issues]);

  useEffect(() => {
    if (!countries.length || selectedCountries.length) return;
    // Start with a geopolitically interesting set
    const defaults = ['India', 'Pakistan', 'USA', 'Russia', 'China', 'Israel'];
    const names = countries.map((c) => c.name);
    const initial = defaults.filter((n) => names.includes(n));
    setSelectedCountries(initial.length >= 2 ? initial : names.slice(0, 5));
  }, [countries]);

  useEffect(() => {
    if (!issues.length || selectedIssues.length) return;
    setSelectedIssues(issues.slice(0, 4).map((i) => i.issue));
  }, [issues]);

  useEffect(() => {
    if (topics.length && !selectedTopic) setSelectedTopic(topics[0]?.topic || '');
  }, [topics]);

  useEffect(() => {
    if (!selectedCountries.length) return;
    setLoading(true);
    getPolicyStance(selectedCountries, selectedIssues, selectedTopic)
      .then((data) => { setPayload(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, [selectedCountries, selectedIssues, selectedTopic]);

  const chartData = useMemo(() => payload.issues.map((issue) => ({
    issue: issue.length > 20 ? issue.slice(0, 18) + '…' : issue,
    fullIssue: issue,
    ...Object.fromEntries(payload.countries.map((c) => [c, payload.matrix.find((row) => row.country === c)?.[issue] || 0])),
  })), [payload]);

  const temporalData = useMemo(() => {
    const firstIssue = payload.issues[0];
    if (!firstIssue) return [];
    const decades = new Set();
    Object.values(payload.temporal || {}).forEach((issueMap) => Object.keys(issueMap[firstIssue] || {}).forEach((d) => decades.add(d)));
    return [...decades].sort().map((decade) => {
      const row = { decade };
      payload.countries.forEach((c) => { row[c] = payload.temporal?.[c]?.[firstIssue]?.[decade] || 0; });
      return row;
    });
  }, [payload]);

  const toggleCountry = (name) => {
    setSelectedCountries((curr) => curr.includes(name) ? curr.filter((c) => c !== name) : curr.length < 12 ? [...curr, name] : curr);
  };

  const toggleIssue = (name) => {
    setSelectedIssues((curr) => curr.includes(name) ? curr.filter((i) => i !== name) : [...curr, name]);
  };

  return (
    <div className="page-grid wide">
      <Panel title="Policy Stance" subtitle="Compare issue activity, alignment, and UN resolution voting across selected countries.">
        <div className="control-stack">
          <SearchableChipList label="Countries" allItems={allCountryNames} selected={selectedCountries} onToggle={toggleCountry} />
          <SearchableChipList label="Issues" allItems={allIssueNames} selected={selectedIssues} onToggle={toggleIssue} />
          <div className="control-label-row">
            <span className="control-label">Topic</span>
            <select value={selectedTopic} onChange={(e) => setSelectedTopic(e.target.value)}>
              {topics.map((t) => <option key={t.topic} value={t.topic}>{t.topic}</option>)}
            </select>
          </div>
        </div>
        {loading && <div className="loading-inline">Fetching data…</div>}
      </Panel>

      <Panel title="Stance Matrix" subtitle="Issue participation counts by country and issue.">
        <div className="table-wrap compact-table">
          <table>
            <thead>
              <tr><th>Country</th>{payload.issues.map((issue) => <th key={issue} title={issue}>{issue.length > 18 ? issue.slice(0, 16) + '…' : issue}</th>)}</tr>
            </thead>
            <tbody>
              {payload.matrix.map((row) => (
                <tr key={row.country}>
                  <td>{row.country}</td>
                  {payload.issues.map((issue) => <td key={issue} style={{ background: row[issue] > 0 ? `rgba(242,107,56,${Math.min(0.7, row[issue] / 20)})` : undefined }}>{row[issue] || 0}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Issue Activity Comparison" subtitle="Which countries are most active on each selected issue.">
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="issue" />
              <YAxis />
              <Tooltip labelFormatter={(_, payload) => payload?.[0]?.payload?.fullIssue || ''} />
              <Legend />
              {payload.countries.map((c, i) => <Bar key={c} dataKey={c} fill={COLORS[i % COLORS.length]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="Agreement Network" subtitle="Countries connected by shared issue involvement. Edge thickness = shared events.">
        <AgreementMiniGraph network={payload.agreement_network} countries={selectedCountries} />
      </Panel>

      <Panel title="Issue Rankings" subtitle="Ranked issue activity — who is most active per issue.">
        <div className="ranking-grid">
          {Object.entries(payload.rankings || {}).map(([issue, rows]) => (
            <div key={issue} className="mini-card">
              <h3 title={issue}>{issue.length > 22 ? issue.slice(0, 20) + '…' : issue}</h3>
              {(rows || []).slice(0, 5).map((row) => (
                <div key={row.country} className="list-row">
                  <span>{row.country}</span>
                  <small>{row.count} events</small>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Temporal Stance Shifts" subtitle={`Activity by decade for: ${payload.issues[0] || 'first selected issue'}`}>
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={temporalData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="decade" />
              <YAxis />
              <Tooltip />
              <Legend />
              {payload.countries.map((c, i) => <Line key={c} type="monotone" dataKey={c} stroke={COLORS[i % COLORS.length]} strokeWidth={2.5} dot={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      {/* Topic Voting Stance — only when a topic is selected and data exists */}
      {payload.selected_topic && Object.keys(payload.topic_stance || {}).length > 0 && (
        <Panel title={`UN Voting: "${payload.selected_topic}"`} subtitle="How each country votes on resolutions under this topic. Green = mostly yes, red = mostly no.">
          <div className="topic-stance-grid">
            {payload.countries.map((c) => {
              const ts = payload.topic_stance?.[c] || {};
              const pct = ts.pct_yes || 0;
              const color = pct > 60 ? '#2a9d8f' : pct > 40 ? '#e3a008' : '#f26b38';
              return (
                <div key={c} className="topic-stance-card">
                  <div className="ts-country">{c}</div>
                  <div className="ts-bar-wrap">
                    <div className="ts-bar" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <div className="ts-stats">
                    <span style={{ color: '#2a9d8f' }}>✓ {ts.yes || 0}</span>
                    <span style={{ color: '#f26b38' }}>✗ {ts.no || 0}</span>
                    <span style={{ color: '#aaa' }}>~ {ts.abstain || 0}</span>
                    <strong style={{ color }}>{pct}% yes</strong>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      <Panel title="UN Resolution Deep Dive" subtitle="Votes on the selected topic, ranked by recency.">
        <div className="table-wrap compact-table">
          <table>
            <thead><tr><th>Country</th><th>Year</th><th>Resolution</th><th>Vote</th></tr></thead>
            <tbody>
              {(payload.resolution_votes || []).slice(0, 80).map((vote, i) => (
                <tr key={i} style={{ color: vote.vote === 'yes' ? '#2a9d8f' : vote.vote === 'no' ? '#f26b38' : undefined }}>
                  <td>{vote.country}</td><td>{vote.year}</td><td>{vote.resolution}</td><td>{vote.vote}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
