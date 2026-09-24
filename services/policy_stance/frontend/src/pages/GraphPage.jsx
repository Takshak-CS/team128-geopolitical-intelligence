import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getBlocsByYear, getCountry, getGraph, getGraphDelta } from '../api';
import CountrySidebar from '../components/CountrySidebar';
import ForcePreview from '../components/ForcePreview';
import Panel from '../components/Panel';

export default function GraphPage({ status, blocMap: staticBlocMap }) {
  const [year, setYear] = useState(2020);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [delta, setDelta] = useState(null);
  const [yearBlocMap, setYearBlocMap] = useState(null);
  const [selectedCountry, setSelectedCountry] = useState(null);
  const [profile, setProfile] = useState(null);
  const [selectedDatasets, setSelectedDatasets] = useState([]);
  const [minIntensity, setMinIntensity] = useState(0);
  const [newEdgePairs, setNewEdgePairs] = useState(new Set());
  const yearTimer = useRef(null);

  const fetchYear = useCallback((y) => {
    if (!status.ready) return;
    Promise.all([getGraph(y), getGraphDelta(y), getBlocsByYear(y)]).then(([graphData, deltaData, blocsData]) => {
      setGraph(graphData);
      setDelta(deltaData);
      setYearBlocMap(blocsData);
      const datasetNames = [...new Set((graphData.edges || []).flatMap((e) => e.datasets || []))];
      setSelectedDatasets(datasetNames);
      const newSet = new Set(
        (deltaData.new_edge_names || []).flatMap((e) => [`${e.source}||${e.target}`, `${e.target}||${e.source}`])
      );
      setNewEdgePairs(newSet);
    });
  }, [status.ready]);

  // Fetch on ready + whenever year changes (debounced)
  useEffect(() => {
    if (!status.ready) return;
    fetchYear(year);
  }, [status.ready]);

  const handleYearChange = (val) => {
    setYear(val);
    if (yearTimer.current) clearTimeout(yearTimer.current);
    yearTimer.current = setTimeout(() => fetchYear(val), 250);
  };

  useEffect(() => {
    if (!selectedCountry) return;
    getCountry(selectedCountry).then(setProfile).catch(() => setProfile(null));
  }, [selectedCountry]);

  const datasetOptions = useMemo(() => [...new Set((graph.edges || []).flatMap((e) => e.datasets || []))], [graph]);

  const filteredGraph = useMemo(() => {
    const edges = (graph.edges || []).filter((edge) => {
      const datasetMatch = !selectedDatasets.length || (edge.datasets || []).some((d) => selectedDatasets.includes(d));
      return datasetMatch && (edge.avg_intensity || edge.conflict_count || 0) >= minIntensity;
    });
    const nodeIds = new Set(edges.flatMap((e) => [e.source, e.target]));
    return { nodes: (graph.nodes || []).filter((n) => nodeIds.has(n.id)), edges };
  }, [graph, selectedDatasets, minIntensity]);

  const toggleDataset = (dataset) => {
    setSelectedDatasets((cur) => cur.includes(dataset) ? cur.filter((d) => d !== dataset) : [...cur, dataset]);
  };

  return (
    <div className="page-grid graph-layout">
      <Panel title="3D Relationship Graph" subtitle="Drag the year slider to see how the conflict network evolved. Green edges = new this year." className="graph-panel">
        <div className="control-row wrap">
          <label>
            <span>Year</span>
            <input type="range" min="1989" max="2025" value={year} onChange={(e) => handleYearChange(Number(e.target.value))} />
          </label>
          <strong style={{ minWidth: 44 }}>{year}</strong>
          <label>
            <span>Min intensity</span>
            <input type="range" min="0" max="5" step="0.5" value={minIntensity} onChange={(e) => setMinIntensity(Number(e.target.value))} />
          </label>
        </div>

        {/* Year delta badge */}
        {delta && (
          <div className="year-delta-bar" key={year}>
            <span className="delta-stat">{delta.nodes} countries</span>
            <span className="delta-stat">{delta.edges.toLocaleString()} connections</span>
            {delta.new_edges > 0 && <span className="delta-new">+{delta.new_edges} new</span>}
            {delta.ended_edges > 0 && <span className="delta-ended">−{delta.ended_edges} ended</span>}
            {delta.new_nodes > 0 && <span className="delta-new">+{delta.new_nodes} new actors</span>}
          </div>
        )}

        <div className="chip-row">
          {datasetOptions.map((ds) => (
            <button key={ds} type="button" className={selectedDatasets.includes(ds) ? 'chip active' : 'chip'} onClick={() => toggleDataset(ds)}>{ds}</button>
          ))}
        </div>

        <ForcePreview
          graph={filteredGraph}
          height={580}
          blocMap={yearBlocMap || staticBlocMap}
          newEdgePairs={newEdgePairs}
          onNodeClick={(node) => setSelectedCountry(node.name)}
        />

        {/* New connections this year */}
        {delta && delta.new_edge_names?.length > 0 && (
          <div className="new-edges-panel">
            <strong>New connections in {year}:</strong>
            <div className="new-edges-list">
              {delta.new_edge_names.slice(0, 20).map((e, i) => (
                <span key={i} className="new-edge-chip">{e.source} ↔ {e.target}</span>
              ))}
              {delta.new_edge_names.length > 20 && <span className="muted">+{delta.new_edge_names.length - 20} more</span>}
            </div>
          </div>
        )}

        <div className="legend-row">
          <span><i className="legend conflict" /> conflict</span>
          <span><i className="legend ally" /> ally</span>
          <span><i className="legend neutral" /> neutral</span>
          <span><i className="legend new-edge" /> new this year</span>
        </div>
      </Panel>
      <CountrySidebar profile={profile} />
    </div>
  );
}
