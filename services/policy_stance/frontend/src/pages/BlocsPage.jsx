import { useEffect, useMemo, useState } from 'react';
import { Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';

import { getAllianceBlocs, getChord, getEmbeddings2d } from '../api';
import ChordDiagram from '../components/ChordDiagram';
import Panel from '../components/Panel';

const BLOC_COLORS = {
  'Western Bloc': '#ff8c42',
  'Russia+Allies': '#62d2a2',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#8aa5bf',
};
const ALL_BLOCS = Object.keys(BLOC_COLORS);

export default function BlocsPage() {
  const [blocs, setBlocs] = useState({ country_to_bloc: {}, blocs: [] });
  const [embeddings, setEmbeddings] = useState({});
  const [chord, setChord] = useState({ links: [] });

  useEffect(() => {
    getAllianceBlocs().then(setBlocs).catch(() => setBlocs({ country_to_bloc: {}, blocs: [] }));
    getEmbeddings2d().then(setEmbeddings).catch(() => setEmbeddings({}));
    getChord().then(setChord).catch(() => setChord({ links: [] }));
  }, []);

  const scatterByBloc = useMemo(() => {
    const grouped = {};
    ALL_BLOCS.forEach((b) => (grouped[b] = []));
    Object.entries(embeddings).forEach(([name, coords]) => {
      const bloc = blocs.country_to_bloc[name] || 'Non-Aligned';
      (grouped[bloc] = grouped[bloc] || []).push({ name, x: coords[0], y: coords[1] });
    });
    return grouped;
  }, [embeddings, blocs]);

  return (
    <div className="page-grid wide">
      <Panel title="Alliance Bloc Detection" subtitle="Countries coloured by detected geopolitical bloc. Proximity = similar conflict-network profile. Axis values are PCA embedding coordinates (not direct measurements).">
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={400}>
            <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 20 }}>
              <XAxis dataKey="x" name="x" type="number" tick={false} axisLine={{ stroke: 'rgba(138,165,191,0.15)' }} tickLine={false} label={{ value: '← Bloc alignment axis →', position: 'insideBottom', offset: -10, fill: '#8aa5bf', fontSize: 11 }} />
              <YAxis dataKey="y" name="y" type="number" tick={false} axisLine={{ stroke: 'rgba(138,165,191,0.15)' }} tickLine={false} label={{ value: '← Positioning axis →', angle: -90, position: 'insideLeft', offset: 15, fill: '#8aa5bf', fontSize: 11 }} />
              <ZAxis range={[55, 55]} />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ payload }) => {
                const d = payload?.[0]?.payload;
                if (!d) return null;
                return <div className="custom-tooltip"><strong>{d.name}</strong><br /><span style={{ color: '#8aa5bf', fontSize: '0.72rem' }}>{blocs.country_to_bloc[d.name] || 'Non-Aligned'}</span></div>;
              }} />
              <Legend />
              {ALL_BLOCS.map((bloc) => (
                <Scatter key={bloc} name={bloc} data={scatterByBloc[bloc] || []} fill={BLOC_COLORS[bloc]} opacity={0.85} />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="Conflict Chord" subtitle="Arc width = total conflict intensity between two countries. Hover an arc to see the pair. Thicker arcs = more severe or frequent conflicts.">
        <ChordDiagram links={chord.links} />
      </Panel>

      <Panel title="Bloc Membership" subtitle="Detected communities and assigned bloc labels.">
        <div className="accordion-list">
          {blocs.blocs.map((bloc) => (
            <details key={bloc.community}>
              <summary>{bloc.label}</summary>
              <p>{bloc.members.join(', ')}</p>
            </details>
          ))}
        </div>
      </Panel>
    </div>
  );
}
