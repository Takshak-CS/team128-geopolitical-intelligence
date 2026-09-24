import CytoscapeComponent from 'react-cytoscapejs';

import SectionCard from './SectionCard';

export default function NetworkGraph({ data }) {
  const elements = [
    ...(data?.nodes || []).map((node) => ({ data: { id: node.id, label: node.label, centrality: node.centrality, community: node.community } })),
    ...(data?.edges || []).map((edge, index) => ({ data: { id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, weight: edge.weight, edgeType: edge.edge_type } })),
  ];

  return (
    <SectionCard title="Interactive Geopolitical Network" kicker="Relations + Similarity Overlay">
      <div className="h-[430px] rounded-3xl border border-white/10 bg-black/10">
        <CytoscapeComponent
          elements={elements}
          style={{ width: '100%', height: '100%' }}
          layout={{ name: 'cose', animate: true, fit: true, padding: 18 }}
          stylesheet={[
            {
              selector: 'node',
              style: {
                label: 'data(label)',
                width: 'mapData(centrality, 0, 1, 20, 70)',
                height: 'mapData(centrality, 0, 1, 20, 70)',
                'background-color': '#62d2a2',
                color: '#f8fafc',
                'font-size': 10,
                'text-valign': 'center',
                'text-halign': 'center',
                'border-width': 2,
                'border-color': '#07131f',
              },
            },
            {
              selector: 'edge',
              style: {
                width: 'mapData(weight, -10, 10, 1, 7)',
                'line-color': '#ff8c42',
                opacity: 0.6,
                'curve-style': 'bezier',
              },
            },
          ]}
        />
      </div>
    </SectionCard>
  );
}
