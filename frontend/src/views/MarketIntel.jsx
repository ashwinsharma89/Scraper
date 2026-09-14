import { useEffect, useState } from 'react'
import { Landmark } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, EmptyState, HelpBox } from '../components/Ui.jsx'

const emptyForm = {
  category: '', metric: '', value: '', source_name: '', source_url: '',
  confidence: '', publication_date: '', accessed_date: '', notes: '',
}

export default function MarketIntel() {
  const { projectId } = useAppState()
  const toast = useToast()
  const [data, setData] = useState(null)
  const [form, setForm] = useState(emptyForm)

  async function reload() {
    const d = await api(`/api/projects/${projectId}/market-intel`)
    setData(d)
    setForm((f) => ({ ...f, category: f.category || d.categories[0] || '', confidence: f.confidence || d.confidence_levels[0] || '' }))
  }

  useEffect(() => { if (projectId) reload() }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function onSubmit(e) {
    e.preventDefault()
    try {
      await api(`/api/projects/${projectId}/market-intel`, { method: 'POST', body: form })
      toast('Cited entry added')
      setForm(emptyForm)
      await reload()
    } catch (err) {
      toast(err.message, true)
    }
  }

  async function onDelete(id) {
    await api(`/api/projects/${projectId}/market-intel/${id}`, { method: 'DELETE' })
    await reload()
  }

  if (!data) return null

  return (
    <>
      <HelpBox view="intel" />
      <Card title="Market Intelligence — cited layer">
        <p className="muted">Every entry requires a full citation. No paywalled research is auto-scraped.</p>
        <form onSubmit={onSubmit}>
          <div className="row">
            <label>Category
              <select value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}>
                {data.categories.map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
            <label>Metric <input value={form.metric} onChange={(e) => setForm((f) => ({ ...f, metric: e.target.value }))} placeholder="e.g. Market size 2024" /></label>
            <label>Value <input required value={form.value} onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} /></label>
          </div>
          <div className="row">
            <label>Source name <input required value={form.source_name} onChange={(e) => setForm((f) => ({ ...f, source_name: e.target.value }))} /></label>
            <label>Source URL <input required value={form.source_url} onChange={(e) => setForm((f) => ({ ...f, source_url: e.target.value }))} /></label>
            <label>Confidence
              <select value={form.confidence} onChange={(e) => setForm((f) => ({ ...f, confidence: e.target.value }))}>
                {data.confidence_levels.map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
          </div>
          <div className="row">
            <label>Publication date <input required type="date" value={form.publication_date} onChange={(e) => setForm((f) => ({ ...f, publication_date: e.target.value }))} /></label>
            <label>Accessed date <input required type="date" value={form.accessed_date} onChange={(e) => setForm((f) => ({ ...f, accessed_date: e.target.value }))} /></label>
            <label>Notes <input value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} /></label>
          </div>
          <button type="submit">Add cited entry</button>
        </form>
      </Card>
      <Card><h3><Landmark size={16} className="title-icon" /> Cited entries</h3>
        {data.cited.length === 0 ? (
          <EmptyState icon={Landmark} title="No cited entries yet" hint="Add one above with a full citation." />
        ) : (
        <div className="table-wrap"><table>
          <thead><tr><th>Category</th><th>Metric</th><th>Value</th><th>Source</th><th>Pub</th><th>Conf</th><th>By</th><th></th></tr></thead>
          <tbody>
            {data.cited.map((e) => (
              <tr key={e.id}>
                <td>{e.category}</td><td>{e.metric}</td><td>{e.value}</td>
                <td><a href={e.source_url} target="_blank" rel="noreferrer">{e.source_name}</a></td>
                <td>{e.publication_date}</td><td>{e.confidence}</td><td>{e.entered_by || ''}</td>
                <td><button className="ghost" onClick={() => onDelete(e.id)}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table></div>
        )}
      </Card>
    </>
  )
}
