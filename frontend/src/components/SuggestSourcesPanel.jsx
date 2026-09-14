import { useState } from 'react'
import { api } from '../api.js'
import { useToast } from './Toast.jsx'

// HANDOFF §7 item 1: "Suggested-RSS-feeds baked into the wizard per country (still
// user-confirmed via health check)." Extracted out of SourcePlan.jsx so the exact
// same ✨ Suggest sources → validate → confirm flow can run right after a study is
// created (NewStudyWizard.jsx), not only if the user later remembers to visit
// Source plan. Always re-fetches the project's CURRENT config immediately before
// merging a selection in — safe to use from a context (like the wizard) that never
// loaded the full project object itself.
export default function SuggestSourcesPanel({ projectId, onApplied }) {
  const toast = useToast()
  const [suggestResults, setSuggestResults] = useState(null)
  const [suggesting, setSuggesting] = useState(false)
  const [checkedSugg, setCheckedSugg] = useState({}) // "channel|value" -> bool

  async function suggestSources() {
    setSuggesting(true)
    setSuggestResults(null)
    try {
      const s = await api(`/api/projects/${projectId}/suggest-sources`, { method: 'POST' })
      setSuggestResults(s)
      const defaults = {}
      const mark = (chan, list) => (list || []).forEach((c) => { defaults[`${chan}|${c.url}`] = c.valid !== false })
      mark('news_rss', s.news_rss); mark('ecommerce', s.ecommerce); mark('forums', s.forums)
      ;(s.subreddits || []).forEach((n) => { defaults[`subreddits|${n}`] = true })
      setCheckedSugg(defaults)
    } catch (e) {
      toast(e.message, true)
    } finally {
      setSuggesting(false)
    }
  }

  async function _mergeAndSave(mutate) {
    const cfg = (await api(`/api/projects/${projectId}`)).config
    const newCfg = structuredClone(cfg)
    const added = mutate(newCfg)
    await api(`/api/projects/${projectId}/config`, { method: 'PUT', body: { config: newCfg } })
    return added
  }

  async function addSelectedSources() {
    const added = await _mergeAndSave((newCfg) => {
      const keyFor = { news_rss: 'rss_feeds', ecommerce: 'ecommerce_urls', forums: 'forum_urls', subreddits: 'subreddits' }
      let count = 0
      for (const [k, checked] of Object.entries(checkedSugg)) {
        if (!checked) continue
        const [chan, value] = k.split('|')
        const key = keyFor[chan]
        if (!key) continue
        const cur = newCfg.source_plan[key] || []
        if (!cur.includes(value)) { cur.push(value); count += 1 }
        newCfg.source_plan[key] = cur
      }
      return count
    })
    toast(`Added ${added} source(s) to the plan`)
    await onApplied?.()
  }

  async function addAllValidated() {
    if (!suggestResults) return
    const added = await _mergeAndSave((newCfg) => {
      let count = 0
      const bulkAdd = (key, values) => {
        const cur = newCfg.source_plan[key] || []
        for (const v of values) { if (!cur.includes(v)) { cur.push(v); count += 1 } }
        newCfg.source_plan[key] = cur
      }
      bulkAdd('rss_feeds', (suggestResults.news_rss || []).filter((c) => c.valid !== false).map((c) => c.url))
      bulkAdd('ecommerce_urls', (suggestResults.ecommerce || []).filter((c) => c.valid !== false).map((c) => c.url))
      return count
    })
    if (added === 0) { toast('No validated RSS/e-commerce candidates to add', true); return }
    toast(`Added ${added} validated RSS + e-commerce source(s)`)
    await onApplied?.()
  }

  return (
    <div>
      <div className="actions" style={{ marginTop: 0 }}>
        <button className="ghost" onClick={suggestSources} disabled={suggesting}>
          {suggesting ? 'Asking Claude…' : '✨ Suggest sources (AI)'}
        </button>
      </div>
      {suggestResults && (
        <SuggestResultsCard s={suggestResults} checked={checkedSugg} setChecked={setCheckedSugg}
          onApply={addSelectedSources} onApplyAllValidated={addAllValidated} />
      )}
    </div>
  )
}

export function SuggestResultsCard({ s, checked, setChecked, onApply, onApplyAllValidated }) {
  const toggle = (k) => setChecked((prev) => ({ ...prev, [k]: !prev[k] }))
  const Row = ({ chan, value, label, valid, note, why }) => {
    const key = `${chan}|${value}`
    return (
      <div className="channel-row" style={{ padding: '.35rem 0' }}>
        <label style={{ flex: 1, fontWeight: 400, display: 'flex', gap: '.5rem', alignItems: 'flex-start', margin: 0 }}>
          <input type="checkbox" checked={!!checked[key]} style={{ width: 'auto', marginTop: '.2rem' }}
            onChange={() => toggle(key)} />
          <span><b>{label}</b>{' '}
            {valid === true ? <span className="ready-badge">✓ valid</span>
              : valid === false ? <span className="flag">✗ {note || 'unverified'}</span>
                : <span className="badge neu">{note || 'candidate'}</span>}
            <br /><span className="muted">{value}{why ? ` — ${why}` : ''}</span></span>
        </label>
      </div>
    )
  }
  const summary = s._summary || {}
  return (
    <div className="card" style={{ borderColor: 'var(--primary)' }}>
      <div className="card-head"><h2>✨ Suggested sources</h2>
        <div className="actions" style={{ marginTop: 0 }}>
          <button className="ghost" onClick={onApplyAllValidated}>✓ Add all validated (RSS + e-commerce)</button>
          <button onClick={onApply}>Add checked to source plan</button>
        </div>
      </div>
      <p className="muted">AI-proposed candidates, each validated by the tool. Uncheck any you don't want.
        App-only quick-commerce/social platforms are shown as documented gaps, not scrapers.</p>
      {!!s.news_rss?.length && <><h3>News RSS feeds — {summary.news_rss || 0}</h3>
        {s.news_rss.map((c) => <Row key={c.url} chan="news_rss" value={c.url} label={c.outlet || c.url} valid={c.valid} note={c.note} why={c.why} />)}</>}
      {!!s.ecommerce?.length && <><h3>E-commerce search URLs — {summary.ecommerce || 0}</h3>
        {s.ecommerce.map((c) => <Row key={c.url} chan="ecommerce" value={c.url} label={c.platform || c.url} valid={c.valid} note={c.note} why={c.why} />)}</>}
      {!!s.forums?.length && <><h3>Forums — {summary.forums || 0}</h3>
        {s.forums.map((c) => <Row key={c.url} chan="forums" value={c.url} label={c.name || c.url} valid={c.valid} note={c.note} why={c.why} />)}</>}
      {!!s.subreddits?.length && <><h3>Subreddits — {summary.subreddits || 0}</h3>
        {s.subreddits.map((n) => <Row key={n} chan="subreddits" value={n} label={`r/${n}`} valid={null} note="confirmed on run" />)}</>}
      {!!s.quick_commerce?.length && <><h3>Quick-commerce / delivery</h3>
        {s.quick_commerce.map((c, i) => (
          <div className="channel-row" style={{ padding: '.35rem 0' }} key={i}><div className="channel-meta">
            <b>{c.platform || ''}</b> {c.web_scrapable ? <span className="badge tier1">web</span> : <span className="badge tier3">app-only → Tier-3 gap</span>}
            <div className="lim">{c.note || ''}</div></div></div>
        ))}
        <div className="note">{s.social_note || ''}</div></>}
      {!s.quick_commerce?.length && s.social_note && <div className="note">{s.social_note}</div>}
    </div>
  )
}
