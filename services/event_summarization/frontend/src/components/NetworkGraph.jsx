import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { select, pointer } from "d3-selection";
import { drag } from "d3-drag";
import { scaleSqrt, scaleLinear } from "d3-scale";
import { zoom, zoomIdentity } from "d3-zoom";
import InfoTip from "./InfoTip.jsx";

const HEIGHT = 500;

function edgeColor(score) {
  if (score >= 5)  return "#1a7a52";
  if (score >= 1)  return "#4fae8a";
  if (score >= -1) return "#6e92a3";
  if (score >= -5) return "#c0392b";
  return "#8b0000";
}

function nodeColor(score, isMain) {
  if (isMain) return "#e8763c";
  if (score >= 1)  return "#4fae8a";
  if (score <= -1) return "#d6604f";
  return "#6e92a3";
}

function buildGraph(tableRows, countryName) {
  if (!tableRows?.length) return { nodes: [], links: [] };

  const actorCount = {}, actorScoreSum = {}, actorCC = {};

  tableRows.forEach(row => {
    [[row.Actor1Name, row.Actor1CountryCode], [row.Actor2Name, row.Actor2CountryCode]].forEach(([name, cc]) => {
      const n = (name || "").trim();
      if (!n || n === "Unidentified" || n === "an unidentified party") return;
      actorCount[n]    = (actorCount[n] || 0) + 1;
      actorScoreSum[n] = (actorScoreSum[n] || 0) + (parseFloat(row.GoldsteinScale) || 0);
      if (cc && !actorCC[n]) actorCC[n] = cc;
    });
  });

  // Keep top 50 actors by event count
  const top = Object.entries(actorCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 50)
    .map(([name]) => name);
  const set = new Set(top);

  const nodes = top.map(id => ({
    id,
    count: actorCount[id],
    avgScore: actorScoreSum[id] / actorCount[id],
    isMain: id.toLowerCase() === countryName.toLowerCase(),
    cc: actorCC[id] || "",
  }));

  // Aggregate edges
  const edgeMap = {};
  tableRows.forEach(row => {
    const a1 = (row.Actor1Name || "").trim();
    const a2 = (row.Actor2Name || "").trim();
    if (!set.has(a1) || !set.has(a2) || a1 === a2) return;
    const key = [a1, a2].sort().join("\x00");
    if (!edgeMap[key]) edgeMap[key] = { source: a1, target: a2, count: 0, scoreSum: 0, types: new Set() };
    edgeMap[key].count++;
    edgeMap[key].scoreSum += parseFloat(row.GoldsteinScale) || 0;
    if (row.EventType) edgeMap[key].types.add(row.EventType);
  });

  const links = Object.values(edgeMap).map(e => ({
    source: e.source, target: e.target,
    count: e.count,
    avgScore: e.scoreSum / e.count,
    types: [...e.types].slice(0, 3),
  }));

  return { nodes, links };
}

export default function NetworkGraph({ tableRows, countryCode, countryName, onNodeClick }) {
  const svgRef       = useRef(null);
  const simRef       = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [stats, setStats]     = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  const { nodes, links } = useMemo(
    () => buildGraph(tableRows, countryName),
    [tableRows, countryName]
  );

  useEffect(() => {
    if (!svgRef.current || !nodes.length) return;

    const el  = svgRef.current;
    const W   = el.clientWidth || 700;
    const H   = HEIGHT;
    const svg = select(el);
    svg.selectAll("*").remove();

    const maxCount = Math.max(...nodes.map(n => n.count), 1);
    const rScale   = scaleSqrt().domain([1, maxCount]).range([5, 22]);
    const wScale   = scaleLinear().domain([1, Math.max(...links.map(l => l.count), 1)]).range([0.8, 5]);

    // Container for zoom/pan
    const g = svg.append("g");

    // Zoom behaviour
    const zoomBeh = zoom().scaleExtent([0.3, 3]).on("zoom", ev => g.attr("transform", ev.transform));
    svg.call(zoomBeh);

    // Links
    const linkSel = g.append("g").attr("class", "links")
      .selectAll("line").data(links).join("line")
      .attr("stroke", d => edgeColor(d.avgScore))
      .attr("stroke-width", d => wScale(d.count))
      .attr("stroke-opacity", 0.45)
      .attr("class", "net-edge");

    // Nodes
    const nodeSel = g.append("g").attr("class", "nodes")
      .selectAll("g").data(nodes).join("g")
      .attr("class", "net-node")
      .attr("cursor", "grab");

    nodeSel.append("circle")
      .attr("r", d => d.isMain ? 26 : rScale(d.count))
      .attr("fill", d => nodeColor(d.avgScore, d.isMain) + (d.isMain ? "" : "33"))
      .attr("stroke", d => nodeColor(d.avgScore, d.isMain))
      .attr("stroke-width", d => d.isMain ? 2.5 : 1)
      .attr("filter", d => d.isMain ? "drop-shadow(0 0 6px rgba(232,118,60,0.4))" : "none");

    // Selection ring (appears on click)
    nodeSel.append("circle")
      .attr("class", "select-ring")
      .attr("r", d => (d.isMain ? 26 : rScale(d.count)) + 7)
      .attr("fill", "none")
      .attr("stroke", "#e8763c")
      .attr("stroke-width", 2)
      .attr("stroke-dasharray", "4 3")
      .attr("opacity", 0);

    // Labels: main node + high-degree nodes
    const labelThresh = maxCount * 0.12;
    nodeSel.filter(d => d.isMain || d.count >= labelThresh)
      .append("text")
      .text(d => d.id.length > 16 ? d.id.slice(0, 15) + "…" : d.id)
      .attr("y", d => -(d.isMain ? 30 : rScale(d.count) + 6))
      .attr("text-anchor", "middle")
      .attr("fill", "var(--text-secondary, #93acb7)")
      .attr("font-size", "10px")
      .attr("font-family", "var(--font-mono, monospace)")
      .attr("pointer-events", "none");

    // Hover interaction
    nodeSel
      .on("click", (event, d) => {
        event.stopPropagation();
        setSelectedId(d.id);
        if (onNodeClick) onNodeClick(d);
        // Scroll to the explorer section smoothly
        setTimeout(() => {
          document.getElementById("actor-explorer")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 100);
      })
      .on("mouseenter", (event, d) => {
        const [mx, my] = pointer(event, el);
        setTooltip({ x: mx, y: my, data: d });
        // Highlight connected edges and dim others
        const connectedIds = new Set([d.id]);
        links.forEach(l => {
          if (l.source.id === d.id || l.target.id === d.id) {
            connectedIds.add(l.source.id || l.source);
            connectedIds.add(l.target.id || l.target);
          }
        });
        linkSel.attr("stroke-opacity", l =>
          (l.source.id === d.id || l.target.id === d.id) ? 0.85 : 0.08
        );
        nodeSel.attr("opacity", n => connectedIds.has(n.id) ? 1 : 0.2);
      })
      .on("mousemove", (event) => {
        const [mx, my] = pointer(event, el);
        setTooltip(t => t ? { ...t, x: mx, y: my } : null);
      })
      .on("mouseleave", () => {
        setTooltip(null);
        linkSel.attr("stroke-opacity", 0.45);
        nodeSel.attr("opacity", 1);
      });

    // Drag
    const dragBeh = drag()
      .on("start", (event, d) => {
        if (!event.active) simRef.current?.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
        select(event.sourceEvent.currentTarget).attr("cursor", "grabbing");
      })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => {
        if (!event.active) simRef.current?.alphaTarget(0);
        d.fx = null; d.fy = null;
        select(event.sourceEvent.currentTarget).attr("cursor", "grab");
      });
    nodeSel.call(dragBeh);

    // Force simulation
    const main = nodes.find(n => n.isMain);
    if (main) { main.fx = W / 2; main.fy = H / 2; }

    const sim = forceSimulation(nodes)
      .force("link", forceLink(links).id(d => d.id).distance(80).strength(0.4))
      .force("charge", forceManyBody().strength(-120))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide(d => (d.isMain ? 28 : rScale(d.count)) + 6))
      .on("tick", () => {
        linkSel
          .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        nodeSel.attr("transform", d =>
          `translate(${Math.max(30, Math.min(W-30, d.x))},${Math.max(30, Math.min(H-30, d.y))})`
        );
      });

    simRef.current = sim;

    // Update selection ring when selectedId changes (re-run on next render)
    nodeSel.selectAll(".select-ring")
      .attr("opacity", d => d.id === selectedId ? 1 : 0);

    // Compute stats
    const conflictEdges = links.filter(l => l.avgScore <= -1).length;
    const coopEdges     = links.filter(l => l.avgScore >= 1).length;
    setStats({ nodes: nodes.length, edges: links.length, conflictEdges, coopEdges });

    return () => { sim.stop(); simRef.current = null; };
  }, [nodes, links]);

  if (!nodes.length) return null;

  return (
    <section>
      <p className="section-label">
        05 · Actor network
        <InfoTip>
          Every named actor is a node. Each event between two actors
          is an edge — green = cooperative, red = conflictual, line
          thickness = event count. Drag nodes to reposition. Scroll
          to zoom. Hover a node to highlight its connections.
        </InfoTip>
      </p>
      <div className="network-card">
        {stats && (
          <div className="network-stats">
            <span>{stats.nodes} actors</span>
            <span>·</span>
            <span>{stats.edges} connections</span>
            <span>·</span>
            <span style={{color:"#d6604f"}}>{stats.conflictEdges} conflictual</span>
            <span>·</span>
            <span style={{color:"#4fae8a"}}>{stats.coopEdges} cooperative</span>
            <span className="network-hint">drag · scroll to zoom · hover for details</span>
          </div>
        )}

        <div style={{ position: "relative" }}>
          <svg ref={svgRef} width="100%" height={HEIGHT} />

          {/* Tooltip */}
          {tooltip && (
            <div className="net-tooltip" style={{
              left: Math.min(tooltip.x + 12, (svgRef.current?.clientWidth || 700) - 200),
              top: tooltip.y + 12,
            }}>
              <div className="net-tooltip-name">{tooltip.data.id}</div>
              <div className="net-tooltip-row">
                <span>{tooltip.data.count} events</span>
                <span style={{ color: nodeColor(tooltip.data.avgScore, false) }}>
                  avg {tooltip.data.avgScore >= 0 ? "+" : ""}{tooltip.data.avgScore.toFixed(1)}
                </span>
              </div>
              {tooltip.data.cc && (
                <div className="net-tooltip-cc">country: {tooltip.data.cc}</div>
              )}
            </div>
          )}
        </div>

        {/* Legend */}
        <div className="network-legend">
          <span><span className="net-leg-line" style={{background:"#4fae8a"}} /> cooperative edge</span>
          <span><span className="net-leg-line" style={{background:"#d6604f"}} /> conflictual edge</span>
          <span><span className="net-leg-dot" style={{background:"#e8763c"}} /> selected country</span>
          <span><span className="net-leg-dot" style={{background:"#4fae8a44",border:"1px solid #4fae8a"}} /> cooperative actor</span>
          <span><span className="net-leg-dot" style={{background:"#d6604f44",border:"1px solid #d6604f"}} /> conflictual actor</span>
        </div>
      </div>
    </section>
  );
}
