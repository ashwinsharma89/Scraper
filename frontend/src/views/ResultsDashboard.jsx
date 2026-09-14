import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { Card, HelpBox, Stat } from '../components/Ui.jsx'

export default function ResultsDashboard() {
  const { projectId } = useAppState()
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    Promise.all([
      api(`/api/projects/${projectId}/analytics/items_by_channel`),
      api(`/api/projects/${projectId}/analytics/items_by_domain`),
      api(`/api/projects/${projectId}/source-health`),
      api(`/api/projects/${projectId}/site-intelligence`),
    ]).then(([byChannel, byDomain, health, ledger]) => {
      if (!cancelled) setData({ byChannel, byDomain, health, ledger })
    })
    return () => { cancelled = true }
  }, [projectId])

  return (
    <>
      <HelpBox view="results" />
      <Card><h3>Volume by channel</h3>
        {!data ? <span className="muted">Loading…</span>
          : data.byChannel.data.length ? (
            <div className="grid">
              {data.byChannel.data.map((c) => (
                <Stat key={c.channel} lbl={c.channel} num={`${c.n} (${c.analyzed_n} analyzed)`} />
              ))}
            </div>
          ) : <p className="muted">Nothing collected yet — run a channel from the Collect tab.</p>}
      </Card>

      <Card><h3>Top sites (generic-site discovery)</h3>
        {data && (data.byDomain.domains.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Domain</th><th>Items collected</th></tr></thead>
            <tbody>{data.byDomain.domains.map((d) => (
              <tr key={d.domain}><td>{d.domain}</td><td>{d.n}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <p className="muted">No generic-site items collected yet.</p>)}
      </Card>

      <Card><h3>Access &amp; reliability</h3>
        <p className="muted">Sources auto-paused after repeated failures — never retried
          forever, never silently dropped (DESIGN_01 §7.4).</p>
        {data && (data.health.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Domain</th><th>Consecutive failures</th><th>Paused</th>
              <th>Last status</th><th>Last checked</th></tr></thead>
            <tbody>{data.health.map((h) => (
              <tr key={h.domain}>
                <td>{h.domain}</td><td>{h.consecutive_failures}</td>
                <td>{h.paused ? <span className="badge tier3">paused</span> : <span className="badge tier1">active</span>}</td>
                <td className="muted">{h.last_status || ''}</td>
                <td className="muted">{(h.last_checked_at || '').slice(0, 19)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <p className="muted">No source-health history yet for this project.</p>)}
      </Card>

      <Card><h3>Site intelligence — what this category has learned so far</h3>
        <p className="muted">The cross-project ledger for "<b>{data?.ledger?.category || '(no category set)'}</b>":
          every real site any study has ever tried for this category, with its accumulated
          track record. This is the literal output of the learning mechanism (DESIGN_01 §4b)
          — not just this study's own runs.</p>
        {data && (data.ledger.sites.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Domain</th><th>Times used</th><th>Kept / dropped</th>
              <th>Confidence</th><th>Blocked</th><th>Status</th></tr></thead>
            <tbody>{data.ledger.sites.map((s) => (
              <tr key={s.domain}>
                <td>{s.domain}</td><td>{s.times_used}</td>
                <td>{s.items_kept} / {s.items_dropped}</td>
                <td>{s.confidence == null ? '—' : `${Math.round(s.confidence * 100)}%`}</td>
                <td>{s.times_blocked}</td>
                <td>{s.validated_by_human ? <span className="badge tier1">human-validated</span>
                  : (s.times_used >= 3 && s.confidence >= 0.5) ? <span className="badge tier1">auto-trusted</span>
                    : <span className="needs-badge">needs validation</span>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <p className="muted">No sites in the ledger for this category yet — run the
          AI-guided study wizard's site discovery step, or collect via the generic-site
          pipeline first.</p>)}
      </Card>
    </>
  )
}
