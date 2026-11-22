import { NavLink } from 'react-router-dom';

const links = [
  ['/', 'Dashboard'],
  ['/graph', 'Network Graph'],
  ['/compare', 'Country Comparison'],
  ['/heatmaps', 'Heatmaps'],
  ['/temporal', 'Temporal Analysis'],
  ['/blocs', 'Alliance Blocs'],
  ['/policy-stance', 'Policy Stance'],
  ['/indicators', 'Policy Indicators'],
];

export default function AppShell({ status, children }) {
  return (
    <div className="app-shell">
      <header className="navbar">
        <div className="navbar-brand">
          <p className="eyebrow">Policy Stance · Team 128</p>
          <h1>Geopolitical Intelligence</h1>
        </div>
        <nav className="navbar-nav">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="status-pill">
          <span className={status.ready ? 'status-dot ready' : 'status-dot'} />
          <span>{status.ready ? 'Ready' : status.progress || 'Starting…'}</span>
        </div>
      </header>
      <main className="page-wrap">{children}</main>
    </div>
  );
}
