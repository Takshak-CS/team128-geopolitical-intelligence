import { useEffect, useMemo, useState } from 'react';
import { Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';

import { getAllianceBlocs, getChord, getEmbeddings2d } from '../api';
import ChordDiagram from '../components/ChordDiagram';
import Panel from '../components/Panel';

const BLOC_COLORS = {
  'Western Bloc': '#f26b38',
  'Russia+Allies': '#0f7b8c',
  'China-Centered Bloc': '#e3a008',
  'Non-Aligned': '#7fb7be',
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
      <Panel title="Alliance Bloc Detection" subtitle="Countries coloured by detected geopolitical bloc, positioned by embedding similarity.">
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={380}>
            <ScatterChart>
              <XAxis dataKey="x" name="x" hide />
              <YAxis dataKey="y" name="y" hide />
              <ZAxis range={[55, 55]} />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ payload }) => {
                const d = payload?.[0]?.payload;
                if (!d) return null;
                return <div style={{ background: '#fff', border: '1px solid #ddd', padding: '6px 10px', borderRadius: 4, fontSize: 13 }}><strong>{d.name}</strong></div>;
              }} />
              <Legend />
              {ALL_BLOCS.map((bloc) => (
                <Scatter key={bloc} name={bloc} data={scatterByBloc[bloc] || []} fill={BLOC_COLORS[bloc]} opacity={0.85} />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="Conflict Chord" subtitle="Conflict intensity flows between country pairs.">
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
