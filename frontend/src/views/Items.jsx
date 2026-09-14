import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { Card, HelpBox } from '../components/Ui.jsx'

function sentimentBadge(s) {
  if (!s) return null
  return <span className={`badge ${s === 'positive' ? 'pos' : s === 'negative' ? 'neg' : 'neu'}`}>{s}</span>
}

export default function Items() {
  const { projectId } = useAppState()
  const [sources, setSources] = useState([])
  const [filters, setFilters] = useState({ q: '', source: '', brand_focus: '', sentiment: '' })
  const [data, setData] = useState(null)
  const debounceRef = useRef(null)

  useEffect(() => {
    if (!projectId) return
    api(`/api/projects/${projectId}/items-table?limit=1`).then((d) => setSources(Object.keys(d.sources || {})))
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const p = new URLSearchParams()
      if (filters.source) p.set('source', filters.source)
      if (filters.brand_focus) p.set('brand_focus', filters.brand_focus)
      if (filters.sentiment) p.set('sentiment', filters.sentiment)
      if (filters.q) p.set('q', filters.q)
      api(`/api/projects/${projectId}/items-table?${p.toString()}`).then(setData)
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [projectId, filters])

  return (
    <>
      <HelpBox view="items" />
      <Card title="Items"
        headExtra={data && <span className="muted">showing {data.rows.length} of {data.matched} matched · {data.total} total</span>}
      >
        <div className="row">
          <label>Search
            <input value={filters.q} onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
              placeholder="title, text, or summary…" />
          </label>
          <label>Channel
            <select value={filters.source} onChange={(e) => setFilters((f) => ({ ...f, source: e.target.value }))}>
              <option value="">all</option>
              {sources.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Brand focus
            <select value={filters.brand_focus} onChange={(e) => setFilters((f) => ({ ...f, brand_focus: e.target.value }))}>
              <option value="">any</option>
              <option>target brand</option><option>named competitor</option>
              <option>category-generic</option><option>corporate</option><option>unrelated</option>
            </select>
          </label>
          <label>Sentiment
            <select value={filters.sentiment} onChange={(e) => setFilters((f) => ({ ...f, sentiment: e.target.value }))}>
              <option value="">any</option><option>positive</option><option>negative</option>
              <option>neutral</option><option>mixed</option>
            </select>
          </label>
        </div>
        <div className="table-wrap">
          {!data ? <p className="muted">Loading…</p> : (
            <table>
              <thead><tr><th>#</th><th>Channel</th><th>Title</th><th>Sentiment</th><th>Lang</th>
                <th>Brand focus</th><th>Driver</th><th>Summary (EN)</th></tr></thead>
              <tbody>
                {data.rows.length === 0 && <tr><td colSpan={8} className="muted">No items match. Collect data first, or loosen the filters.</td></tr>}
                {data.rows.map((r, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td><td>{r.source}</td>
                    <td>{r.link ? <a href={r.link} target="_blank" rel="noreferrer">{(r.title || '').slice(0, 90)}</a> : (r.title || '').slice(0, 90)}</td>
                    <td>{sentimentBadge(r.sentiment)}</td><td>{r.language || ''}</td>
                    <td>{r.brand_focus || '—'}</td><td>{r.purchase_driver || '—'}</td>
                    <td className="muted">{(r.summary_en || r.text || '').slice(0, 140)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </>
  )
}
