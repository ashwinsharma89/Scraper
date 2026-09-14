import { useState } from 'react'
import { AlertCircle, CheckCircle2, Clock, FlaskConical, Loader2, ListChecks } from 'lucide-react'
import { api } from '../api.js'
import { useAppState, CHREQ } from '../state/AppState.jsx'
import { useJobs } from '../state/JobsState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, EmptyState, HelpBox } from '../components/Ui.jsx'

const EXT_CHANNELS = [
  { value: 'news', label: 'News (Google + Bing)', defaultOn: true },
  { value: 'gdelt', label: 'GDELT', defaultOn: true },
  { value: 'reddit', label: 'Reddit', defaultOn: true },
  { value: 'forums', label: 'Forums', defaultOn: false },
  { value: 'ecommerce', label: 'E-commerce', defaultOn: false },
]

function statusBadge(status) {
  if (status === 'running') return <span className="badge tier1"><Loader2 size={11} className="spin" /> running</span>
  if (status === 'queued') return <span className="badge neu"><Clock size={11} /> queued</span>
  if (status === 'error') return <span className="badge neg"><AlertCircle size={11} /> error</span>
  return <span className="badge pos"><CheckCircle2 size={11} /> done</span>
}

export default function Collect() {
  const { projectId, project, channels } = useAppState()
  const { jobs, startWatching } = useJobs()
  const toast = useToast()

  const [year, setYear] = useState(new Date().getFullYear())
  const [extChannels, setExtChannels] = useState(new Set(EXT_CHANNELS.filter((c) => c.defaultOn).map((c) => c.value)))
  const [marketOnly, setMarketOnly] = useState(true)
  const [extStatus, setExtStatus] = useState('')

  if (!project || !channels) return null
  const mkt = project.config.market || {}
  const ordered = [...channels.channels].sort((a, b) => (CHREQ[b]?.ready ? 1 : 0) - (CHREQ[a]?.ready ? 1 : 0))

  function toggleExt(value, checked) {
    const next = new Set(extChannels)
    if (checked) next.add(value); else next.delete(value)
    setExtChannels(next)
  }

  async function runExtensive() {
    const list = [...extChannels]
    if (!list.length) { toast('Pick at least one channel', true); return }
    setExtStatus(`Queuing ${list.length} channel(s) for all of ${year}…`)
    try {
      const r = await api(`/api/projects/${projectId}/collect-extensive`, {
        method: 'POST', body: { channels: list, year, market_only: marketOnly },
      })
      toast(`Extensive research queued: ${r.jobs.map((j) => j.channel).join(', ')} (${year})`)
      setExtStatus(`Running ${list.length} channel(s) for ${year} — monthly chunks, this can take a few minutes. Watch "Recent jobs", or the running-jobs indicator in the top bar from any tab.`)
      startWatching()
    } catch (e) {
      setExtStatus('')
      toast(e.message, true)
    }
  }

  async function runCollect(channel) {
    try {
      const params = {}
      if (channel === 'news') params.market_only = marketOnly
      const r = await api(`/api/projects/${projectId}/collect`, { method: 'POST', body: { channel, params } })
      toast(`Queued ${channel} (job #${r.job_id})`)
      startWatching()
    } catch (e) {
      toast(e.message, true)
    }
  }

  return (
    <>
      <HelpBox view="collect" />
      <Card title={<><FlaskConical size={17} strokeWidth={2.1} className="title-icon" /> Extensive research (one click)</>}>
        <p className="muted">Full-year, month-by-month collection across the chosen channels
          (monthly chunking beats Google News's ~100-results cap), market-filtered and
          de-duplicated. You pick the channels and year — this never auto-fires.</p>
        <div className="row">
          <label style={{ flex: '0 0 120px' }}>Year
            <input type="number" value={year} min="2015" max={new Date().getFullYear()}
              onChange={(e) => setYear(parseInt(e.target.value, 10) || new Date().getFullYear())} />
          </label>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: '.2rem' }}>Channels</div>
            {EXT_CHANNELS.map((c) => (
              <label key={c.value} style={{ fontWeight: 400, display: 'inline-block', marginRight: '1rem' }}>
                <input type="checkbox" checked={extChannels.has(c.value)} style={{ width: 'auto' }}
                  onChange={(e) => toggleExt(c.value, e.target.checked)} /> {c.label}
              </label>
            ))}
          </div>
        </div>
        <div className="actions" style={{ marginTop: '.6rem' }}>
          <button onClick={runExtensive}>Run extensive research</button>
          <span className="muted">{extStatus}</span>
        </div>
        <div className="note">Forums/E-commerce only run if you've added their URLs in Source plan.
          Reddit/GDELT need network that isn't bot-blocked (works from a normal connection).</div>
      </Card>

      <Card title="Collect a single channel">
        <label style={{ fontWeight: 600 }}>
          <input type="checkbox" checked={marketOnly} style={{ width: 'auto', marginRight: '.4rem' }}
            onChange={(e) => setMarketOnly(e.target.checked)} />
          Restrict news to {mkt.country || 'the target market'} (drop off-market items, e.g. other countries)
        </label>
        <p className="muted" style={{ margin: '.2rem 0 .6rem' }}>
          Uses market terms <b>{(mkt.market_terms || []).join(', ') || mkt.country || '—'}</b> and
          domain <b>{mkt.cctld || '—'}</b>. Edit these in Source plan. Uncheck to collect globally.
        </p>
        {ordered.map((ch) => {
          const i = channels.info[ch] || {}
          const req = CHREQ[ch] || { ready: false, needs: '' }
          return (
            <div className="channel-row" key={ch}>
              <div className="channel-meta">
                <b>{i.name || ch}</b> <span className="badge tier1">Tier {i.tier || '1'}</span>{' '}
                {req.ready ? <span className="ready-badge">ready — no setup</span>
                  : <span className="needs-badge">needs: {req.needs}</span>}
                <div className="lim">{i.method || ''}</div>
                <div className="lim">⚠ {i.limitation || ''}</div>
              </div>
              <div><button onClick={() => runCollect(ch)}>Run</button></div>
            </div>
          )
        })}
      </Card>

      <Card title="Recent jobs">
        {jobs.length === 0 ? (
          <EmptyState icon={ListChecks} title="No jobs yet" hint="Run a channel above to see it tracked here." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>#</th><th>Channel</th><th>Status</th><th>By</th><th>New</th><th>Dup</th></tr></thead>
              <tbody>
                {jobs.map((j) => {
                  const s = j.summary || {}
                  return (
                    <tr key={j.id}>
                      <td>{j.id}</td><td>{j.channel}</td><td>{statusBadge(j.status)}</td>
                      <td>{j.triggered_by || ''}</td><td>{s.new ?? '—'}</td><td>{s.duplicate ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
