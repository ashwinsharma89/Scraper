import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'
import { Card, HelpBox } from '../components/Ui.jsx'

export default function RunLog() {
  const { projectId } = useAppState()
  const { jobs } = useJobs() // a job finishing is exactly when a new run row can appear
  const [runs, setRuns] = useState([])

  useEffect(() => {
    if (!projectId) return
    api(`/api/projects/${projectId}/runs`).then(setRuns).catch(() => setRuns([]))
  }, [projectId, jobs])

  return (
    <>
      <HelpBox view="runlog" />
      <Card title="Run log — full audit trail">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Channel</th><th>Status</th><th>Started</th><th>Returned</th>
                <th>New</th><th>Dup</th><th>By</th><th>Errors</th></tr>
            </thead>
            <tbody>
              {runs.length === 0 && <tr><td colSpan={9} className="muted">No runs yet.</td></tr>}
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td><td>{r.channel}</td><td>{r.status}</td>
                  <td>{(r.started_at || '').slice(0, 19)}</td>
                  <td>{r.rows_returned}</td><td>{r.rows_new}</td><td>{r.rows_duplicate}</td>
                  <td>{r.triggered_by || ''}</td>
                  <td className="muted">{(r.errors_json || '[]').slice(0, 120)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
