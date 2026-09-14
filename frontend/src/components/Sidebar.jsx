import { NavLink } from 'react-router-dom'
import { useAppState } from '../state/AppState.jsx'

const TABS = [
  { to: '/overview', label: 'Overview' },
  { to: '/sources', label: 'Source plan' },
  { to: '/collect', label: 'Collect' },
  { to: '/runlog', label: 'Run log' },
  { to: '/results', label: 'Results dashboard' },
  { to: '/items', label: 'Items' },
  { to: '/analysis', label: 'Analysis' },
  { to: '/intel', label: 'Market intel' },
  { to: '/manual', label: 'Manual intel' },
  { to: '/schedules', label: 'Schedules' },
  { to: '/export', label: 'Export & report' },
]

export default function Sidebar() {
  const { mode, user, version, logout } = useAppState()
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="mark">M</span>
        <div className="brand-text">
          <span className="brand-name">MarketLens</span>
          <span className="brand-tag">market &amp; product intelligence</span>
        </div>
      </div>

      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => (isActive ? 'active' : '')}>
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-foot">
        {mode === 'team' && user && <span className="chip">{user}</span>}
        {mode === 'team' && <button className="ghost" onClick={logout}>Sign out</button>}
        <span className="muted">
          {version ? `MarketLens v${version.version} · ${version.mode} mode` : 'MarketLens'}
        </span>
      </div>
    </aside>
  )
}
