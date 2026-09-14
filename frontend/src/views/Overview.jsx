import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'
import { Card, HelpBox, Stat } from '../components/Ui.jsx'

export default function Overview() {
  const { projectId, project } = useAppState()
  const { jobs } = useJobs()
  const [dash, setDash] = useState(null)

  useEffect(() => {
    if (!projectId) return
    api(`/api/projects/${projectId}/dashboard`).then(setDash).catch(() => setDash(null))
  }, [projectId, jobs])

  if (!project) return null
  const cfg = project.config
  const seg = cfg.source_plan?.segments || {}

  return (
    <>
      <HelpBox view="overview" />
      <Card title={project.name}
        headExtra={<a href={`/api/projects/${projectId}/config.yaml`} target="_blank" rel="noreferrer" className="muted">config.yaml ↗</a>}>
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
        <div className="grid">
          {dash ? (
            <>
              <Stat lbl="Total items" num={dash.total_items} />
              <Stat lbl="Analyzed" num={dash.total_analyzed} />
              <Stat lbl="Awaiting analysis" num={dash.unanalyzed} />
              <Stat lbl="Net sentiment" num={dash.overall_net_score + (dash.low_confidence_overall ? ' ⚠' : '')} />
              <Stat lbl="Languages seen" num={Object.keys(dash.language_breakdown || {}).join(', ') || '—'} />
            </>
          ) : <span className="muted">loading…</span>}
        </div>
      </Card>
      <Card title={null}>
        <h3>Segment applicability</h3>
        <div>
          {Object.entries(seg).map(([k, v]) => (
            <span key={k} className={`badge ${v ? 'pos' : 'neu'}`}>{k}: {v ? 'on' : 'off'}</span>
          ))}
        </div>
      </Card>
    </>
  )
}
