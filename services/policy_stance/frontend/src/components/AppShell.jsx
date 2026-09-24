import { NavLink } from 'react-router-dom';

const links = [
  ['/', 'Dashboard'],
  ['/graph', 'Network Graph'],
  ['/compare', 'Country Comparison'],
  ['/heatmaps', 'Heatmaps'],
  ['/temporal', 'Temporal Analysis'],
  ['/blocs', 'Alliance Blocs'],
  ['/policy-stance', 'Policy Stance'],
];

export default function AppShell({ status, children }) {
  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />
      <header className="navbar">
        <div>
          <p className="eyebrow">Capstone Intelligence Platform</p>
          <h1>Geopolitical Intelligence System</h1>
        </div>
        <nav>
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="status-pill">
          <span className={status.ready ? 'status-dot ready' : 'status-dot'} />
          <span>{status.ready ? 'Ready' : status.progress || 'Starting'}</span>
        </div>
      </header>
      <main className="page-wrap">{children}</main>
    </div>
  );
}
