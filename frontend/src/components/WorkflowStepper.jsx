import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'

// The four-step Configure -> Collect -> Analyze -> Export guide shown on every view.
// Ported from static/app.js's renderWorkflow() -- re-fetches the dashboard whenever
// `jobs` changes (a job finishing is exactly when these numbers can have moved),
// instead of the old imperative "call renderWorkflow() after this specific action".
export default function WorkflowStepper() {
  const { projectId, health } = useAppState()
  const { jobs } = useJobs()
  const [dash, setDash] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!projectId) { setDash(null); return }
    let cancelled = false
    api(`/api/projects/${projectId}/dashboard`)
      .then((d) => { if (!cancelled) setDash(d) })
      .catch(() => { if (!cancelled) setDash(null) })
    return () => { cancelled = true }
  }, [projectId, jobs])

  if (!dash) return null

  const hasKey = !!health?.keys?.anthropic
  const collected = dash.total_items > 0
  const analyzed = dash.total_analyzed > 0 && dash.unanalyzed === 0
  const partiallyAnalyzed = dash.total_analyzed > 0 && dash.unanalyzed > 0

  const steps = [
    { view: 'overview', n: 1, title: 'Configure',
      sub: 'Wizard + Source plan — define market, keywords, and where to look.',
      done: true, status: '✓ study created' },
    { view: 'collect', n: 2, title: 'Collect',
      sub: 'Run scrapers to gather items. Start with News / Reddit / GDELT.',
      done: collected, current: !collected,
      status: collected ? `✓ ${dash.total_items} items collected` : '→ run a scraper' },
    { view: 'analysis', n: 3, title: 'Analyze',
      sub: hasKey ? 'Tag items with sentiment, English summaries, drivers, themes.'
        : 'Needs ANTHROPIC_API_KEY in .env, then restart.',
      done: analyzed,
      warn: collected && !analyzed && !hasKey,
      current: collected && !analyzed && hasKey,
      status: analyzed ? `✓ ${dash.total_analyzed} analyzed`
        : partiallyAnalyzed ? `${dash.total_analyzed} done · ${dash.unanalyzed} left`
          : !hasKey ? '⚠ set API key first' : collected ? '→ click Analyze all' : 'collect first' },
    { view: 'export', n: 4, title: 'Export',
      sub: 'Build the Excel workbook + report draft. Best after Analyze.',
      done: false, current: analyzed,
      status: analyzed ? '→ ready to export' : 'richer after Analyze' },
  ]

  return (
    <div className="workflow">
      {steps.map((s) => (
        <div
          key={s.view}
          className={['step', s.done && 'done', s.current && 'current', s.warn && 'warn']
            .filter(Boolean).join(' ')}
          onClick={() => navigate(`/${s.view}`)}
        >
          <div><span className="step-n">{s.done ? '✓' : s.n}</span><span className="step-title">{s.title}</span></div>
          <div className="step-sub">{s.sub}</div>
          <div className="step-status">{s.status}</div>
        </div>
      ))}
    </div>
  )
}
