import { Link } from 'react-router-dom';

import ForcePreview from '../components/ForcePreview';
import Panel from '../components/Panel';
import StatCard from '../components/StatCard';

const quickLinks = [
  ['/graph', 'Explore network graph'],
  ['/compare', 'Compare countries'],
  ['/policy-stance', 'Policy stance'],
  ['/blocs', 'Alliance blocs'],
];

export default function DashboardPage({ status, countries, datasets, graph, blocMap }) {
  const years = graph?.edges?.flatMap((edge) => edge.years || []) || [];
  const yearMin = years.length ? years.reduce((a, b) => (b < a ? b : a), Infinity) : 1989;
  const yearMax = years.length ? years.reduce((a, b) => (b > a ? b : a), -Infinity) : 2025;

  return (
    <div>
      <div className="page-header">
        <h2>Policy Stance Analyser</h2>
        <p>UN voting patterns, conflict data, and alliance analytics across 198 countries (1989–2025).</p>
      </div>

      <div className="stat-grid four" style={{ marginBottom: '1rem' }}>
        <StatCard label="Countries" value={countries.length} hint="graph nodes" />
        <StatCard label="Conflict Edges" value={status.edge_count || 0} hint="relationships" />
        <StatCard label="Years Covered" value={`${yearMin}–${yearMax}`} hint="temporal graph" />
        <StatCard label="Datasets" value={datasets.length} hint="sources parsed" />
      </div>

      {!status.ready && (
        <div className="loading-box" style={{ marginBottom: '1rem' }}>
          <div className="spinner" />
          <div>
            <strong>Processing data</strong>
            <p style={{ margin: '0.2rem 0 0', color: 'var(--muted)', fontSize: '0.85rem' }}>{status.progress}</p>
          </div>
        </div>
      )}

      <div className="page-grid wide" style={{ marginBottom: '1rem' }}>
        <Panel
          title="Network Preview"
          subtitle="Global conflict network — sovereign nations coloured by alliance bloc. Hover to identify, click for profile."
          className="hero-panel"
        >
          <ForcePreview graph={graph} height={420} blocMap={blocMap} />
        </Panel>

        <Panel title="Quick access">
          <div className="quick-links" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            {quickLinks.map(([to, label]) => (
              <Link key={to} to={to} className="action-link" style={{ justifyContent: 'flex-start' }}>
                {label}
              </Link>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Loaded Datasets" subtitle="Current backend data inventory.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Rows</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <tr key={dataset.dataset}>
                  <td>{dataset.dataset}</td>
                  <td>{dataset.rows?.toLocaleString?.() ?? dataset.rows}</td>
                  <td>{dataset.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
