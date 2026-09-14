import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Compass, Download, ScrollText, BarChart3,
  FileText, Brain, Landmark, ClipboardList, CalendarClock, FileOutput,
} from 'lucide-react'
import { useAppState } from '../state/AppState.jsx'

const TABS = [
  { to: '/overview', label: 'Overview', icon: LayoutDashboard },
  { to: '/sources', label: 'Source plan', icon: Compass },
  { to: '/collect', label: 'Collect', icon: Download },
  { to: '/runlog', label: 'Run log', icon: ScrollText },
  { to: '/results', label: 'Results dashboard', icon: BarChart3 },
  { to: '/items', label: 'Items', icon: FileText },
  { to: '/analysis', label: 'Analysis', icon: Brain },
  { to: '/intel', label: 'Market intel', icon: Landmark },
  { to: '/manual', label: 'Manual intel', icon: ClipboardList },
  { to: '/schedules', label: 'Schedules', icon: CalendarClock },
  { to: '/export', label: 'Export & report', icon: FileOutput },
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
            <t.icon size={16} strokeWidth={2.1} />
            <span>{t.label}</span>
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
