import { useNavigate } from 'react-router-dom'
import { Loader2, Plus, Sparkles } from 'lucide-react'
import { useAppState } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'

export default function Topbar({ onNewStudy, onNewDiscovery }) {
  const { projects, projectId, selectProject } = useAppState()
  const { activeCount, jobs } = useJobs()
  const navigate = useNavigate()
  // Jobs run one at a time (single-writer queue) — at most one is ever "running";
  // the rest are "queued". Its progress (when the channel reports one) is the real,
  // specific signal worth surfacing here, not just a generic spinner.
  const running = jobs.find((j) => j.status === 'running')
  const pct = running?.progress ? Math.round((running.progress.current / running.progress.total) * 100) : null

  return (
    <header className="topbar">
      <div className="project-picker">
        <select
          title="Active project"
          value={projectId ?? ''}
          onChange={(e) => selectProject(parseInt(e.target.value, 10))}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>#{p.id} · {p.name}</option>
          ))}
        </select>
      </div>
      <div className="topbar-right">
        {activeCount > 0 && (
          <button className="ghost jobs-chip" onClick={() => navigate('/collect')}
            title={running?.progress?.label || ''}>
            <Loader2 size={14} className="spin" />
            {pct !== null ? `${running.channel} ${pct}%` : `${activeCount} job${activeCount === 1 ? '' : 's'} running`}
            {pct !== null && activeCount > 1 ? ` (+${activeCount - 1} queued)` : ''}
          </button>
        )}
        <button className="ghost" onClick={onNewStudy}><Plus size={15} /> New study</button>
        <button onClick={onNewDiscovery}><Sparkles size={15} /> AI-guided study</button>
      </div>
    </header>
  )
}
