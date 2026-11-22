import { useEffect, useRef, useState } from 'react';
import Panel from '../components/Panel';
import { getAllianceBlocs, getVotingAgreementMatrix } from '../api';

const BLOC_COLORS = {
  'Western Bloc': '#ff8c42',
  'Russia+Allies': '#62d2a2',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#8aa5bf',
};
const BLOC_DISPLAY = {
  'Western Bloc': 'Western Bloc',
  'Russia+Allies': 'Russia + Allies',
  'China-Centered Bloc': 'China-Centered',
  'Non-Aligned': 'Non-Aligned',
};

// Key countries to always label
const ALWAYS_LABEL = new Set(['USA', 'China', 'Russia', 'India', 'Germany', 'France', 'Brazil', 'UK', 'Iran', 'Saudi Arabia', 'Japan', 'Australia', 'South Africa', 'Pakistan', 'Indonesia', 'Nigeria', 'Egypt', 'Argentina', 'Canada', 'Belarus', 'Israel', 'Ukraine', 'Turkey']);

function VoteNetwork({ matrix, blocMap, threshold }) {
  const svgRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);

  useEffect(() => {
    if (!matrix || !svgRef.current) return;
    const countries = matrix.countries || [];
    const scores = matrix.matrix || [];
    if (!countries.length) return;

    // Build edges above threshold
    const edges = [];
    for (let i = 0; i < countries.length; i++) {
      for (let j = i + 1; j < countries.length; j++) {
        const w = scores[i]?.[j];
        if (w != null && w >= threshold) edges.push({ source: i, target: j, weight: w });
      }
    }

    // Build nodes
    const nodes = countries.map((name, i) => ({
      id: i,
      name,
      bloc: blocMap[name] || 'Non-Aligned',
      degree: 0,
    }));
    edges.forEach((e) => { nodes[e.source].degree++; nodes[e.target].degree++; });

    // Filter to nodes that have at least 1 edge
    const activeIds = new Set(edges.flatMap((e) => [e.source, e.target]));
    const activeNodes = nodes.filter((n) => activeIds.has(n.id));
    if (!activeNodes.length) return;

    // Simple force-directed layout (custom, no d3 dependency)
    const W = svgRef.current.clientWidth || 800;
    const H = 520;
    const cx = W / 2, cy = H / 2;

    // Initialize positions by bloc
    const blocPos = {
      'Western Bloc': { x: cx - 220, y: cy - 100 },
      'Russia+Allies': { x: cx + 180, y: cy - 120 },
      'China-Centered Bloc': { x: cx + 160, y: cy + 120 },
      'Non-Aligned': { x: cx - 20, y: cy + 80 },
    };
    activeNodes.forEach((n) => {
      const bp = blocPos[n.bloc] || { x: cx, y: cy };
      n.x = bp.x + (Math.random() - 0.5) * 160;
      n.y = bp.y + (Math.random() - 0.5) * 160;
      n.vx = 0; n.vy = 0;
    });

    // Index for fast lookup
    const idxMap = {};
    activeNodes.forEach((n, i) => { idxMap[n.id] = i; });
    const edgesIdx = edges
      .filter((e) => idxMap[e.source] !== undefined && idxMap[e.target] !== undefined)
      .map((e) => ({ ...e, si: idxMap[e.source], ti: idxMap[e.target] }));

    // Run simulation
    const ITERS = 180;
    for (let iter = 0; iter < ITERS; iter++) {
      const alpha = 1 - iter / ITERS;
      // Repulsion
      for (let i = 0; i < activeNodes.length; i++) {
        for (let j = i + 1; j < activeNodes.length; j++) {
          const dx = activeNodes[j].x - activeNodes[i].x;
          const dy = activeNodes[j].y - activeNodes[i].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (1800 / (dist * dist)) * alpha;
          activeNodes[i].vx -= (dx / dist) * force;
          activeNodes[i].vy -= (dy / dist) * force;
          activeNodes[j].vx += (dx / dist) * force;
          activeNodes[j].vy += (dy / dist) * force;
        }
      }
      // Attraction along edges
      edgesIdx.forEach(({ si, ti, weight }) => {
        const a = activeNodes[si], b = activeNodes[ti];
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetLen = 80 + (1 - weight) * 120;
        const force = (dist - targetLen) * 0.06 * alpha;
        a.vx += (dx / dist) * force;
        a.vy += (dy / dist) * force;
        b.vx -= (dx / dist) * force;
        b.vy -= (dy / dist) * force;
      });
      // Center gravity
      activeNodes.forEach((n) => {
        n.vx += (cx - n.x) * 0.012 * alpha;
        n.vy += (cy - n.y) * 0.012 * alpha;
        n.vx *= 0.82; n.vy *= 0.82;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(28, Math.min(W - 28, n.x));
        n.y = Math.max(28, Math.min(H - 28, n.y));
      });
    }

    // Count blocs
    const blocCounts = {};
    const totalEdgeWeight = edges.reduce((s, e) => s + e.weight, 0);
    activeNodes.forEach((n) => { blocCounts[n.bloc] = (blocCounts[n.bloc] || 0) + 1; });

    // Render SVG
    const svg = svgRef.current;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

    // Edges
    const edgeGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    edgesIdx.forEach(({ si, ti, weight }) => {
      const a = activeNodes[si], b = activeNodes[ti];
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
      const opacity = 0.08 + (weight - threshold) / (1 - threshold) * 0.35;
      line.setAttribute('stroke', '#8aa5bf');
      line.setAttribute('stroke-width', 0.6 + (weight - threshold) * 2);
      line.setAttribute('stroke-opacity', opacity);
      edgeGroup.appendChild(line);
    });
    svg.appendChild(edgeGroup);

    // Nodes
    activeNodes.forEach((n) => {
      const r = 4 + Math.min(n.degree, 20) * 0.5;
      const color = BLOC_COLORS[n.bloc] || '#8aa5bf';
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.style.cursor = 'pointer';

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', n.x); circle.setAttribute('cy', n.y); circle.setAttribute('r', r);
      circle.setAttribute('fill', color); circle.setAttribute('fill-opacity', '0.85');
      circle.setAttribute('stroke', color); circle.setAttribute('stroke-width', '1');
      g.appendChild(circle);

      const showLabel = ALWAYS_LABEL.has(n.name) || n.degree >= 15;
      if (showLabel) {
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        const abbr = n.name === 'United States' ? 'USA' : n.name === 'United Kingdom' ? 'UK' : n.name === 'South Africa' ? 'ZAF' : n.name === 'Saudi Arabia' ? 'SAU' : n.name === 'South Korea' ? 'KOR' : n.name.length > 6 ? n.name.slice(0, 3).toUpperCase() : n.name;
        text.textContent = abbr;
        text.setAttribute('x', n.x); text.setAttribute('y', n.y - r - 2);
        text.setAttribute('text-anchor', 'middle'); text.setAttribute('font-size', '8');
        text.setAttribute('fill', '#c8d5e0'); text.setAttribute('pointer-events', 'none');
        g.appendChild(text);
      }

      g.addEventListener('mouseenter', (e) => {
        circle.setAttribute('r', r + 2);
        setTooltip({ x: e.clientX, y: e.clientY, name: n.name, bloc: n.bloc, degree: n.degree });
      });
      g.addEventListener('mouseleave', () => { circle.setAttribute('r', r); setTooltip(null); });
      svg.appendChild(g);
    });

    // Stats overlay
    return { nodeCount: activeNodes.length, edgeCount: edgesIdx.length, blocCounts };
  }, [matrix, blocMap, threshold]);

  return (
    <div style={{ position: 'relative' }}>
      <svg ref={svgRef} width="100%" height="520" style={{ display: 'block', background: 'var(--surface-2)', borderRadius: 10 }} />
      {tooltip && (
        <div style={{ position: 'fixed', left: tooltip.x + 12, top: tooltip.y - 10, background: 'var(--surface)', border: '1px solid rgba(138,165,191,0.25)', borderRadius: 8, padding: '8px 12px', fontSize: '0.8rem', pointerEvents: 'none', zIndex: 999, minWidth: 140 }}>
          <div style={{ fontWeight: 700 }}>{tooltip.name}</div>
          <div style={{ color: BLOC_COLORS[tooltip.bloc] || '#8aa5bf', fontSize: '0.75rem' }}>{BLOC_DISPLAY[tooltip.bloc] || tooltip.bloc}</div>
          <div style={{ color: 'var(--muted)', fontSize: '0.75rem' }}>{tooltip.degree} connections</div>
        </div>
      )}
    </div>
  );
}

export default function HeatmapsPage() {
  const [matrix, setMatrix] = useState(null);
  const [blocData, setBlocData] = useState({ country_to_bloc: {}, blocs: [] });
  const [threshold, setThreshold] = useState(0.5);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    Promise.all([getVotingAgreementMatrix(), getAllianceBlocs()])
      .then(([m, b]) => {
        setMatrix(m);
        setBlocData(b);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const countries = matrix?.countries || [];
  const totalCountries = countries.length;
  const detectedBlocs = blocData?.blocs?.length || 0;

  // Compute modularity-like stat: fraction of edges within-bloc vs total
  const edgeStats = (() => {
    if (!matrix || !blocData.country_to_bloc) return { total: 0, withinBloc: 0, q: 0 };
    const scores = matrix.matrix || [];
    let total = 0, withinBloc = 0;
    for (let i = 0; i < countries.length; i++) {
      for (let j = i + 1; j < countries.length; j++) {
        const w = scores[i]?.[j];
        if (w != null && w >= threshold) {
          total++;
          if ((blocData.country_to_bloc[countries[i]] || 'Non-Aligned') === (blocData.country_to_bloc[countries[j]] || 'Non-Aligned')) withinBloc++;
        }
      }
    }
    return { total, withinBloc, q: total > 0 ? (withinBloc / total).toFixed(2) : 0 };
  })();

  return (
    <div className="page-grid wide">
      <Panel title="Who votes with whom?" subtitle="GNN embeds all countries in a vote-similarity space. Louvain community detection finds blocs from the data — no hand-coded labels. Edge weight = UN GA vote agreement rate.">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="control-label">Min agreement</span>
            <input type="range" min={0.5} max={0.95} step={0.05} value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              style={{ width: 120, accentColor: '#ff8c42' }} />
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#ff8c42', minWidth: 32 }}>{Math.round(threshold * 100)}%</span>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            {Object.entries(BLOC_DISPLAY).map(([key, label]) => (
              <span key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.78rem' }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: BLOC_COLORS[key], display: 'inline-block' }} />
                {label}
              </span>
            ))}
          </div>
        </div>

        {loading
          ? <div style={{ height: 520, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-2)', borderRadius: 10, color: 'var(--muted)' }}>Loading vote data...</div>
          : !matrix
            ? <div style={{ height: 520, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-2)', borderRadius: 10, color: 'var(--muted)' }}>No data available</div>
            : <VoteNetwork matrix={matrix} blocMap={blocData.country_to_bloc || {}} threshold={threshold} />
        }

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginTop: '0.75rem' }}>
          {[
            { label: 'countries', value: totalCountries },
            { label: 'detected blocs', value: detectedBlocs },
            { label: 'within-bloc edges', value: `${Math.round(edgeStats.q * 100)}%` },
          ].map(({ label, value }) => (
            <div key={label} style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '12px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: '1.6rem', fontWeight: 800, color: '#ff8c42', lineHeight: 1 }}>{value}</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 4 }}>{label}</div>
            </div>
          ))}
        </div>
        <p style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: 8 }}>Node size = number of connections above threshold. Drag the slider to filter weaker ties. Hover a node for details.</p>
      </Panel>
    </div>
  );
}