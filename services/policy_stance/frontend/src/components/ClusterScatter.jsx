import Plot from 'react-plotly.js';

import SectionCard from './SectionCard';

export default function ClusterScatter({ data }) {
  const points = data?.points || [];
  return (
    <SectionCard title="Latent Country Clusters" kicker="Embedding Projection">
      <Plot
        data={[
          {
            x: points.map((point) => point.x),
            y: points.map((point) => point.y),
            text: points.map((point) => `${point.country} | cluster ${point.cluster}`),
            mode: 'markers+text',
            textposition: 'top center',
            marker: {
              size: points.map((point) => Math.max(10, (point.intensity_mean || 0) * 2 + 10)),
              color: points.map((point) => point.cluster),
              colorscale: 'Portland',
              line: { width: 1, color: '#07131f' },
              opacity: 0.85,
            },
            type: 'scatter',
          },
        ]}
        layout={{
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          margin: { t: 20, r: 20, b: 40, l: 40 },
          font: { color: '#e2e8f0' },
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: '100%', height: '420px' }}
      />
    </SectionCard>
  );
}
