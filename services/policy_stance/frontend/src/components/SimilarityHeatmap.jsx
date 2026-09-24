import Plot from 'react-plotly.js';

import SectionCard from './SectionCard';

export default function SimilarityHeatmap({ data }) {
  return (
    <SectionCard title="Country Similarity Heatmap" kicker="Policy Alignment Matrix">
      <Plot
        className="w-full"
        data={[
          {
            z: data?.matrix || [],
            x: data?.countries || [],
            y: data?.countries || [],
            type: 'heatmap',
            colorscale: [
              [0, '#09141f'],
              [0.4, '#1f6f8b'],
              [0.7, '#62d2a2'],
              [1, '#ffb55a'],
            ],
            hoverongaps: false,
          },
        ]}
        layout={{
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          margin: { t: 20, r: 20, b: 80, l: 80 },
          font: { color: '#e2e8f0' },
          xaxis: { tickangle: -35, automargin: true },
          yaxis: { automargin: true },
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: '100%', height: '420px' }}
      />
    </SectionCard>
  );
}
