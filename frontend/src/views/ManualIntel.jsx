import { useEffect, useState } from 'react'
import { ClipboardList } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, EmptyState, HelpBox } from '../components/Ui.jsx'

const emptyForm = { advertiser: '', platform: '', creative_theme: '', format: '', first_seen_date: '', source_url: '', notes: '' }

export default function ManualIntel() {
  const { projectId } = useAppState()
  const toast = useToast()
  const [plan, setPlan] = useState(null)
  const [intel, setIntel] = useState(null)
  const [form, setForm] = useState(emptyForm)

  async function reload() {
    const [p, i] = await Promise.all([
      api(`/api/projects/${projectId}/manual-plan`),
      api(`/api/projects/${projectId}/market-intel`),
    ])
    setPlan(p); setIntel(i)
  }

  useEffect(() => { if (projectId) reload() }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function onSubmit(e) {
    e.preventDefault()
    try {
      await api(`/api/projects/${projectId}/manual-intel`, { method: 'POST', body: form })
      toast('Observation saved')
      setForm(emptyForm)
      await reload()
    } catch (err) {
      toast(err.message, true)
    }
  }

  if (!plan || !intel) return null

  return (
    <>
      <HelpBox view="manual" />
      <Card title="Manual Intelligence (Tier-2)">
        <p className="muted">These platforms are free to browse but hostile to automation. Open the deep
          links, then record observations below.</p>
        {plan.platforms.map((p) => (
          <div className="channel-row" key={p.name}>
            <div className="channel-meta">
              <b>{p.name}</b> <span className="badge tier2">Tier 2</span>
              <div className="lim">{p.note}</div>
              <div className="deep-links">
                {(p.deep_links || []).length
                  ? p.deep_links.map((d) => <a key={d.url} href={d.url} target="_blank" rel="noreferrer">{d.name} ↗</a>)
                  : <span className="muted">no name-search deep links</span>}
              </div>
            </div>
          </div>
        ))}
      </Card>

      <Card><h3>Record an ad observation</h3>
        <form onSubmit={onSubmit}>
          <div className="row">
            <label>Advertiser <input required value={form.advertiser} onChange={(e) => setForm((f) => ({ ...f, advertiser: e.target.value }))} /></label>
            <label>Platform <input required value={form.platform} onChange={(e) => setForm((f) => ({ ...f, platform: e.target.value }))} /></label>
            <label>Creative theme <input value={form.creative_theme} onChange={(e) => setForm((f) => ({ ...f, creative_theme: e.target.value }))} /></label>
          </div>
          <div className="row">
            <label>Format <input value={form.format} onChange={(e) => setForm((f) => ({ ...f, format: e.target.value }))} placeholder="video / static / carousel" /></label>
            <label>First seen <input type="date" value={form.first_seen_date} onChange={(e) => setForm((f) => ({ ...f, first_seen_date: e.target.value }))} /></label>
            <label>Source URL <input value={form.source_url} onChange={(e) => setForm((f) => ({ ...f, source_url: e.target.value }))} /></label>
          </div>
          <label>Notes <textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} /></label>
          <button type="submit">Save observation</button>
        </form>
        <div style={{ marginTop: '1rem' }}>
          {intel.manual_ads.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Platform</th><th>Advertiser</th><th>Theme</th><th>Format</th><th>First seen</th><th>By</th></tr></thead>
              <tbody>{intel.manual_ads.map((e, i) => (
                <tr key={i}>
                  <td>{e.source_name}</td><td>{e.value}</td>
                  <td>{e.extra.creative_theme || ''}</td><td>{e.extra.format || ''}</td>
                  <td>{e.extra.first_seen_date || ''}</td><td>{e.entered_by || ''}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <EmptyState icon={ClipboardList} title="No observations yet" hint="Record one above after browsing a Tier-2 platform's deep links." />}
        </div>
      </Card>

      <Card><h3>Tier-3 — NOT covered (documented gaps)</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>Platform</th><th>Reason</th></tr></thead>
          <tbody>{plan.tier3_gaps.map((g) => (
            <tr key={g.platform}><td><span className="badge tier3">{g.platform}</span></td><td className="muted">{g.reason}</td></tr>
          ))}</tbody>
        </table></div>
        <div className="note">MarketLens never claims coverage of these platforms and never fabricates data for a failed scrape.</div>
      </Card>
    </>
  )
}
