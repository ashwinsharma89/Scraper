import { useNavigate } from 'react-router-dom'
import { Loader2, Plus, Sparkles } from 'lucide-react'
import { useAppState } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'

export default function Topbar({ onNewStudy, onNewDiscovery }) {
  const { projects, projectId, selectProject } = useAppState()
  const { activeCount } = useJobs()
  const navigate = useNavigate()

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
          <button className="ghost jobs-chip" onClick={() => navigate('/collect')}>
            <Loader2 size={14} className="spin" />
            {activeCount} job{activeCount === 1 ? '' : 's'} running
          </button>
        )}
        <button className="ghost" onClick={onNewStudy}><Plus size={15} /> New study</button>
        <button onClick={onNewDiscovery}><Sparkles size={15} /> AI-guided study</button>
      </div>
    </header>
  )
}
