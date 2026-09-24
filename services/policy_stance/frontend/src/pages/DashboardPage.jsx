import { Link } from 'react-router-dom';

import ForcePreview from '../components/ForcePreview';
import Panel from '../components/Panel';
import StatCard from '../components/StatCard';

const quickLinks = [
  ['/graph', 'Explore graph'],
  ['/compare', 'Compare countries'],
  ['/policy-stance', 'Policy stance'],
  ['/blocs', 'Alliance blocs'],
];

export default function DashboardPage({ status, countries, datasets, graph, blocMap }) {
  const years = graph?.edges?.flatMap((edge) => edge.years || []) || [];
  const yearMin = years.length ? years.reduce((a, b) => (b < a ? b : a), Infinity) : 1989;
  const yearMax = years.length ? years.reduce((a, b) => (b > a ? b : a), -Infinity) : 2025;

  return (
    <div className="page-grid wide">
      <Panel title="Geopolitical Intelligence System — Policy Stance Analyser" subtitle="Conflict, voting, alliance, and stance analytics built directly from the datasets in this directory." className="hero-panel">
        <div className="hero-copy">
          <div className="stat-grid four">
            <StatCard label="Total Countries" value={countries.length} hint="graph nodes" />
            <StatCard label="Conflict Edges" value={status.edge_count || 0} hint="relationships" />
            <StatCard label="Years Covered" value={`${yearMin}–${yearMax}`} hint="temporal graph" />
            <StatCard label="Datasets Loaded" value={datasets.length} hint="sources parsed" />
          </div>
          <div className="quick-links">
            {quickLinks.map(([to, label]) => (
              <Link key={to} to={to} className="action-link">
                {label}
              </Link>
            ))}
          </div>
          {!status.ready ? (
            <div className="loading-box">
              <div className="spinner" />
              <div>
                <strong>Backend is processing data</strong>
                <p>{status.progress}</p>
              </div>
            </div>
          ) : null}
        </div>
      </Panel>

      <Panel title="Network Preview" subtitle="Global conflict network — all 144 sovereign nations, coloured by alliance bloc. Hover to identify, click for country profile.">
        <ForcePreview graph={graph} height={420}  blocMap={blocMap} />
      </Panel>

      <Panel title="Loaded Datasets" subtitle="Current backend inventory.">
        <div className="table-wrap compact-table">
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
                  <td>{dataset.rows}</td>
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
