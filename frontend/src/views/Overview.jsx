import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Database, FileCheck2, FileClock, Gauge, Languages, Settings2, Trash2 } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, HelpBox, Skeleton, Stat } from '../components/Ui.jsx'
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.jsx'
import EditSettingsModal from '../wizards/EditSettingsModal.jsx'

export default function Overview() {
  const { projectId, project, loadProjects } = useAppState()
  const { jobs } = useJobs()
  const [dash, setDash] = useState(null)
  const [editOpen, setEditOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const toast = useToast()
  const navigate = useNavigate()

  useEffect(() => {
    if (!projectId) return
    api(`/api/projects/${projectId}/dashboard`).then(setDash).catch(() => setDash(null))
  }, [projectId, jobs])

  if (!project) return null
  const cfg = project.config
  const seg = cfg.source_plan?.segments || {}

  async function handleDelete() {
    try {
      await api(`/api/projects/${projectId}?confirm=DELETE`, { method: 'DELETE' })
      toast(`"${project.name}" deleted.`)
      setDeleteOpen(false)
      await loadProjects()
      navigate('/overview')
    } catch (e) {
      toast(e.message, true)
    }
  }

  return (
    <>
      <HelpBox view="overview" />
      <Card title={project.name}
        headExtra={<div className="actions">
          <a href={`/api/projects/${projectId}/config.yaml`} target="_blank" rel="noreferrer" className="muted">config.yaml ↗</a>
          <button className="ghost" onClick={() => setEditOpen(true)}><Settings2 size={14} /> Edit settings</button>
          <button className="danger" onClick={() => setDeleteOpen(true)}><Trash2 size={14} /> Delete study</button>
        </div>}>
        <div className="grid">
          <Stat lbl="Brand" num={cfg.product.brand || '— (category-only study)'} />
          <Stat lbl="Market" num={`${cfg.market.country} (${cfg.market.country_code || '?'})`} />
          <Stat lbl="Languages" num={(cfg.market.languages || []).join(', ')} />
          <Stat lbl="Category" num={`${cfg.product.category} / ${cfg.product.category_type}`} />
          <Stat lbl="Competitors" num={(cfg.competitors || []).join(', ') || '—'} />
          <Stat lbl="GDELT country" num={cfg.market.gdelt_country || '—'} />
        </div>
      </Card>
      <Card title={null}>
        <h3>Live snapshot</h3>
        {dash ? (
          <div className="grid">
            <Stat lbl="Total items" num={dash.total_items} icon={Database} tone="primary" />
            <Stat lbl="Analyzed" num={dash.total_analyzed} icon={FileCheck2} tone="good" />
            <Stat lbl="Awaiting analysis" num={dash.unanalyzed} icon={FileClock} tone="warn" />
            <Stat lbl="Net sentiment" num={dash.overall_net_score + (dash.low_confidence_overall ? ' ⚠' : '')} icon={Gauge} tone="primary" />
            <Stat lbl="Languages seen" num={Object.keys(dash.language_breakdown || {}).join(', ') || '—'} icon={Languages} tone="primary" />
          </div>
        ) : <Skeleton grid rows={5} />}
      </Card>
      <Card title={null}>
        <h3>Segment applicability</h3>
        <div>
          {Object.entries(seg).map(([k, v]) => (
            <span key={k} className={`badge ${v ? 'pos' : 'neu'}`}>{k}: {v ? 'on' : 'off'}</span>
          ))}
        </div>
      </Card>

      {editOpen && (
        <EditSettingsModal project={project} onClose={() => setEditOpen(false)}
          onSaved={() => window.location.reload()} />
      )}
      {deleteOpen && (
        <ConfirmDeleteModal projectName={project.name} onClose={() => setDeleteOpen(false)} onConfirm={handleDelete} />
      )}
    </>
  )
}
