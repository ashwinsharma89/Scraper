import { useEffect, useState } from 'react'
import { CheckCircle2, MessageSquareQuote, XCircle } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, EmptyState, HelpBox, Skeleton } from '../components/Ui.jsx'

function SentBar({ c }) {
  const n = c.n || 1
  const pct = (x) => `${((x / n) * 100).toFixed(0)}%`
  return (
    <div className="bar">
      <div className="seg-pos" style={{ width: pct(c.positive) }} />
      <div className="seg-neg" style={{ width: pct(c.negative) }} />
      <div className="seg-mix" style={{ width: pct(c.mixed) }} />
      <div className="seg-neu" style={{ width: pct(c.neutral) }} />
    </div>
  )
}

export default function Analysis() {
  const { projectId, health } = useAppState()
  const toast = useToast()
  const [dash, setDash] = useState(null)
  const [aggs, setAggs] = useState(null)
  const [verbatims, setVerbatims] = useState(null)
  const [status, setStatus] = useState('')
  const [running, setRunning] = useState(false)

  async function reload() {
    const d = await api(`/api/projects/${projectId}/dashboard`)
    setDash(d)
    const [bvc, drivers, trends, verb] = await Promise.all([
      api(`/api/projects/${projectId}/analytics/brand_vs_competitor`),
      api(`/api/projects/${projectId}/analytics/purchase_drivers`),
      api(`/api/projects/${projectId}/analytics/trend_volume`),
      api(`/api/projects/${projectId}/analytics/verbatims`),
    ])
    setAggs({ bvc, drivers, trends })
    setVerbatims(verb)
  }

  useEffect(() => { if (projectId) reload() }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function doAnalyze(mode) {
    setRunning(true)
    setStatus('Analyzing… (calls the Claude API; needs ANTHROPIC_API_KEY)')
    try {
      const r = await api(`/api/projects/${projectId}/analyze`, { method: 'POST', body: { mode } })
      if (r.status === 'error') toast(`Analysis error: ${r.error || ''}`, true)
      setStatus(`Analyzed ${r.analyzed}; remaining ${r.remaining ?? '?'}.`)
      await reload()
    } catch (e) {
      setStatus('')
      toast(e.message, true)
    } finally {
      setRunning(false)
    }
  }

  if (!dash) return <Card><Skeleton rows={3} /></Card>

  const hasKey = !!health?.keys?.anthropic
  const nItems = dash.total_items || 0

  return (
    <>
      <HelpBox view="analysis" />
      <Card>
        <div className="card-head">
          <h2>Analysis {hasKey
            ? <span className="keychip ok"><CheckCircle2 size={11} /> ANTHROPIC_API_KEY detected</span>
            : <span className="keychip missing"><XCircle size={11} /> ANTHROPIC_API_KEY not set</span>}</h2>
          <div className="actions">
            <button className="ghost" disabled={!nItems || running} onClick={() => doAnalyze('batch')}>Analyze one batch (12)</button>
            <button disabled={!nItems || !hasKey || running} onClick={() => doAnalyze('all')}>Analyze all</button>
          </div>
        </div>
        {nItems === 0 && <div className="note">No items to analyze yet. Go to <b>Collect</b> and run a scraper first, then come back here.</div>}
        {!!nItems && !hasKey && (
          <div className="note">You have <b>{nItems}</b> items ready, but analysis needs{' '}
            <span className="kbd">ANTHROPIC_API_KEY</span>. Add it to <b>.env</b>, restart the app, then reload this page.</div>
        )}
        <div className="muted">{status}</div>
      </Card>

      <Card><h3>Sentiment × channel</h3>
        <p className="muted">Overall net {dash.overall_net_score}{' '}
          {dash.low_confidence_overall && <span className="flag">low-confidence (n&lt;100)</span>}
          {' '}· {dash.total_analyzed}/{dash.total_items} analyzed</p>
        <div className="table-wrap"><table>
          <thead><tr><th>Channel</th><th>n</th><th>Sentiment</th><th>Net</th><th>Languages</th><th></th></tr></thead>
          <tbody>
            {dash.by_channel.length === 0 && <tr><td colSpan={6} className="muted">No analyzed items yet.</td></tr>}
            {dash.by_channel.map((c) => (
              <tr key={c.channel}>
                <td>{c.channel}</td><td>{c.n}</td>
                <td style={{ minWidth: 120 }}><SentBar c={c} /></td>
                <td>{c.net_score}</td>
                <td className="muted">{JSON.stringify(c.language_breakdown)}</td>
                <td>{c.low_confidence && <span className="flag">emerging</span>}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Card>

      <Card><h3>Brand vs. competitor · drivers · trends</h3>
        {aggs && (
          <>
            <h4>Brand focus (net sentiment, n)</h4>
            {aggs.bvc.data.length ? aggs.bvc.data.map((r) => (
              <div key={r.brand_focus}>{r.brand_focus}: <b>{r.net_score}</b> <span className="muted">(n={r.n})</span>
                {r.low_confidence && <span className="flag">emerging</span>}</div>
            )) : <span className="muted">—</span>}
            <h4 style={{ marginTop: '.8rem' }}>Top purchase drivers (n={aggs.drivers.n})</h4>
            {aggs.drivers.drivers.length
              ? aggs.drivers.drivers.map((d) => <span key={d.driver} className="badge neu">{d.driver} · {d.count} </span>)
              : <span className="muted">—</span>}
            <h4 style={{ marginTop: '.8rem' }}>Trend volume</h4>
            {aggs.trends.series.length ? aggs.trends.series.map((s) => (
              <div key={s.trend_category}>{s.trend_category}: <b>{s.n}</b> {s.low_confidence && <span className="flag">emerging</span>}</div>
            )) : <span className="muted">—</span>}
          </>
        )}
      </Card>

      <Card><h3>Top verbatims per theme</h3>
        {verbatims && (verbatims.themes.length ? verbatims.themes.map((t) => (
          <div style={{ marginBottom: '.7rem' }} key={t.theme}>
            <b>{t.theme}</b> <span className="muted">(n={t.n})</span>
            {t.verbatims.map((v, i) => (
              <div className="muted" style={{ marginLeft: '1rem' }} key={i}>
                • "{v.summary_en || v.text}"{' '}
                <span className={`badge ${v.sentiment === 'positive' ? 'pos' : v.sentiment === 'negative' ? 'neg' : 'neu'}`}>{v.sentiment}</span>{' '}
                <i>{v.source}</i>
              </div>
            ))}
          </div>
        )) : <EmptyState icon={MessageSquareQuote} title="No verbatims yet" />)}
      </Card>
    </>
  )
}
