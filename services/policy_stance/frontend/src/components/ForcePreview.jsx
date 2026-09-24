import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph3D from 'react-force-graph-3d';

const BLOC_COLORS = {
  'Western Bloc': '#f26b38',
  'Russia+Allies': '#0f7b8c',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#7fb7be',
};

export default function ForcePreview({ graph, height = 340, onNodeClick, blocMap = {}, minNodes = 0, newEdgePairs = new Set() }) {
  const fgRef = useRef(null);
  const containerRef = useRef(null);
  const labelRef = useRef(null);
  const [width, setWidth] = useState(800);

  // Measure container once; debounce to avoid render loops
  useEffect(() => {
    if (!containerRef.current) return;
    const measure = () => {
      const w = containerRef.current?.getBoundingClientRect().width;
      if (w && Math.abs(w - width) > 2) setWidth(Math.floor(w));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []); // only on mount

  const fittedRef = useRef(false);

  const data = useMemo(() => {
    fittedRef.current = false; // reset so new data auto-fits once
    const allNodes = (graph?.nodes || []).filter((n) => n.gw_code >= 2 && n.gw_code <= 920);
    let nodes = allNodes;
    if (minNodes && nodes.length > minNodes) {
      nodes = [...allNodes]
        .sort((a, b) => (b.degree_centrality || 0) - (a.degree_centrality || 0))
        .slice(0, minNodes);
    }
    const allowed = new Set(nodes.map((n) => n.id));
    const links = (graph?.edges || []).filter((e) => {
      const s = typeof e.source === 'object' ? e.source?.id : e.source;
      const t = typeof e.target === 'object' ? e.target?.id : e.target;
      return allowed.has(s) && allowed.has(t);
    });
    // Remove isolated nodes — they scatter into a ring with no forces pulling them in
    const connected = new Set();
    links.forEach((e) => {
      const s = typeof e.source === 'object' ? e.source?.id : e.source;
      const t = typeof e.target === 'object' ? e.target?.id : e.target;
      connected.add(s); connected.add(t);
    });
    return { nodes: nodes.filter((n) => connected.has(n.id)), links };
  }, [graph, minNodes]);

  // Re-layout every time data changes (year change, filter change)
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force('charge')?.strength(-160);
    fg.d3Force('link')?.distance(50).strength(0.5);
    // Scatter nodes randomly so the new layout is visibly different
    (data.nodes || []).forEach((n) => { n.x = (Math.random() - 0.5) * 400; n.y = (Math.random() - 0.5) * 400; n.z = 0; });
    fg.d3ReheatSimulation?.();
  }, [data]);

  // Zoom to fit only once after initial load — never again (so user zoom isn't reset)
  const onEngineStop = useCallback(() => {
    if (fittedRef.current) return;
    fittedRef.current = true;
    fgRef.current?.zoomToFit?.(600, 40);
  }, []);

  // Node/link color — pure functions, no state deps → no re-render
  const nodeColor = useCallback((node) => BLOC_COLORS[blocMap[node.name]] || BLOC_COLORS['Non-Aligned'], [blocMap]);
  const linkColor = useCallback((link) => {
    const sName = typeof link.source === 'object' ? link.source?.name : link.source;
    const tName = typeof link.target === 'object' ? link.target?.name : link.target;
    if (newEdgePairs.has(`${sName}||${tName}`) || newEdgePairs.has(`${tName}||${sName}`)) return '#22c55e';
    return link.relationship_type === 'conflict' ? '#e05c3a66' : '#7fb7be44';
  }, [newEdgePairs]);

  // Hover: update label via DOM ref — zero re-renders
  const onNodeHover = useCallback((node) => {
    if (labelRef.current) {
      if (node) {
        const bloc = blocMap[node.name] || 'Non-Aligned';
        labelRef.current.textContent = `${node.name}  ·  ${bloc}`;
        labelRef.current.style.display = 'block';
      } else {
        labelRef.current.style.display = 'none';
      }
    }
  }, [blocMap]);

  return (
    <div ref={containerRef} style={{ width: '100%', height, position: 'relative', overflow: 'hidden' }}>
      <ForceGraph3D
        ref={fgRef}
        graphData={data}
        width={width}
        height={height}
        backgroundColor="rgba(0,0,0,0)"
        numDimensions={2}
        nodeRelSize={4}
        warmupTicks={200}
        cooldownTicks={0}
        d3AlphaDecay={0.01}
        d3VelocityDecay={0.4}
        onEngineStop={onEngineStop}
        linkColor={linkColor}
        linkOpacity={0.6}
        linkWidth={(link) => Math.max(0.5, Math.min(3, (link.conflict_count || 0) * 0.3 + (link.avg_intensity || 0) * 0.5))}
        nodeColor={nodeColor}
        nodeVal={(node) => Math.max(1, Math.min(10, (node.degree_centrality || 0.01) * 30))}
        onNodeClick={onNodeClick}
        onNodeHover={onNodeHover}
        nodeLabel=""
        showNavInfo={false}
        controlType="orbit"
      />
      <div
        ref={labelRef}
        style={{ display: 'none', position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)', background: 'rgba(19,41,47,0.88)', color: '#fff', padding: '3px 14px', borderRadius: 20, fontSize: '0.8rem', pointerEvents: 'none', whiteSpace: 'nowrap' }}
      />
      <div style={{ position: 'absolute', bottom: 6, right: 10, fontSize: '0.68rem', color: 'rgba(0,0,0,0.3)', pointerEvents: 'none' }}>
        Scroll to zoom · Drag to pan
      </div>
    </div>
  );
}
