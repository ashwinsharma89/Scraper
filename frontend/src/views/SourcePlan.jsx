import { useState } from 'react'
import { Compass, Rss } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, EmptyState, HelpBox } from '../components/Ui.jsx'
import SuggestSourcesPanel from '../components/SuggestSourcesPanel.jsx'

function ListEditor({ label, hint, value, onChange }) {
  return (
    <label>{label} <span className="muted">{hint}</span>
      <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

export default function SourcePlan() {
  const { projectId, project, channels } = useAppState()
  const toast = useToast()
  const cfg = project.config
  const sp = cfg.source_plan
  const mkt = cfg.market || {}

  const [lists, setLists] = useState({
    rss_feeds: (sp.rss_feeds || []).join('\n'),
    ecommerce_urls: (sp.ecommerce_urls || []).join('\n'),
    ecommerce_search: (sp.ecommerce_search || []).join('\n'),
    ecommerce_keywords: (sp.ecommerce_keywords || []).join('\n'),
    forum_urls: (sp.forum_urls || []).join('\n'),
    quora_topics: (sp.quora_topics || []).join('\n'),
    subreddits: (sp.subreddits || []).join('\n'),
  })
  const [marketTerms, setMarketTerms] = useState((mkt.market_terms || []).join(', '))
  const [kwByLang, setKwByLang] = useState(cfg.keywords.by_language || {})
  const [feedResults, setFeedResults] = useState(null)
  const [feedChecking, setFeedChecking] = useState(false)

  const [expandTerm, setExpandTerm] = useState(cfg.product?.category || '')
  const [expansion, setExpansion] = useState(null)
  const [expanding, setExpanding] = useState(false)
  const [expChecks, setExpChecks] = useState({ variants: new Set(), brands: new Set(), translations: {} })

  const [outlets, setOutlets] = useState(null)
  const [discoveringOutlets, setDiscoveringOutlets] = useState(false)
  const [checkedOutlets, setCheckedOutlets] = useState(new Set())

  const [geoTerms, setGeoTerms] = useState(null)
  const [discoveringGeoTerms, setDiscoveringGeoTerms] = useState(false)
  const [checkedGeoTerms, setCheckedGeoTerms] = useState(new Set())

  async function saveSources() {
    const newCfg = structuredClone(cfg)
    for (const [key, text] of Object.entries(lists)) {
      newCfg.source_plan[key] = text.split('\n').map((x) => x.trim()).filter(Boolean)
    }
    for (const [lang, slots] of Object.entries(kwByLang)) {
      newCfg.keywords.by_language[lang] = slots
    }
    newCfg.market = newCfg.market || {}
    newCfg.market.market_terms = marketTerms.split(',').map((x) => x.trim()).filter(Boolean)
    try {
      await api(`/api/projects/${projectId}/config`, { method: 'PUT', body: { config: newCfg } })
      const r = await api(`/api/projects/${projectId}/regenerate-feeds`, { method: 'POST' })
      toast(`Config saved — ${r.google_news_feeds} Google News + ${r.bing_news_feeds} Bing News feed(s) regenerated.`)
      window.location.reload() // simplest correct way to pick up the recomputed feeds everywhere
    } catch (e) {
      toast(e.message, true)
    }
  }

  async function runFeedHealth() {
    const feeds = lists.rss_feeds.split('\n').map((x) => x.trim()).filter(Boolean)
    setFeedChecking(true)
    setFeedResults(null)
    try {
      const r = await api(`/api/projects/${projectId}/feed-health`, { method: 'POST', body: { urls: feeds } })
      setFeedResults(r.results)
    } catch (e) {
      toast(e.message, true)
    } finally {
      setFeedChecking(false)
    }
  }

  async function doExpandTerm() {
    const term = expandTerm.trim()
    if (!term) { toast('Enter a term to expand', true); return }
    setExpanding(true)
    setExpansion(null)
    try {
      const r = await api(`/api/projects/${projectId}/suggest-terms`, { method: 'POST', body: { term } })
      setExpansion(r)
      setExpChecks({
        variants: new Set(r.variants || []),
        brands: new Set(r.brands || []),
        translations: Object.fromEntries(Object.entries(r.translations || {}).map(([lang, e]) =>
          [lang, { term: e.term, variants: new Set(e.variants || []) }])),
      })
    } catch (e) {
      toast(e.message, true)
    } finally {
      setExpanding(false)
    }
  }

  async function applyExpansion() {
    const translations = {}
    for (const [lang, e] of Object.entries(expChecks.translations)) {
      translations[lang] = { term: e.term, variants: [...e.variants] }
    }
    try {
      const r = await api(`/api/projects/${projectId}/apply-terms`, {
        method: 'POST',
        body: { term: expansion.term, variants: [...expChecks.variants], brands: [...expChecks.brands], translations },
      })
      toast(`Added — ${r.google_news_feeds} Google News + ${r.bing_news_feeds} Bing News feed(s) total now.`)
      window.location.reload()
    } catch (e) {
      toast(e.message, true)
    }
  }

  async function doDiscoverOutlets() {
    setDiscoveringOutlets(true)
    setOutlets(null)
    try {
      const r = await api(`/api/projects/${projectId}/suggest-outlets`, { method: 'POST' })
      setOutlets(r)
      setCheckedOutlets(new Set((r.outlets || []).filter((o) => !o.caution).map((o) => o.name)))
    } catch (e) {
      toast(e.message, true)
    } finally {
      setDiscoveringOutlets(false)
    }
  }

  async function applyOutlets() {
    const names = [...checkedOutlets]
    try {
      const r = await api(`/api/projects/${projectId}/apply-outlets`, { method: 'POST', body: { names } })
      toast(`Added ${names.length} outlet(s) — ${r.market_terms_count} market term(s) total now.`)
      window.location.reload()
    } catch (e) {
      toast(e.message, true)
    }
  }

  async function doDiscoverGeoTerms() {
    setDiscoveringGeoTerms(true)
    setGeoTerms(null)
    try {
      const r = await api(`/api/projects/${projectId}/suggest-market-terms`, { method: 'POST' })
      setGeoTerms(r)
      setCheckedGeoTerms(new Set((r.terms || []).map((t) => t.name)))
    } catch (e) {
      toast(e.message, true)
    } finally {
      setDiscoveringGeoTerms(false)
    }
  }

  async function applyGeoTerms() {
    const names = [...checkedGeoTerms]
    try {
      const r = await api(`/api/projects/${projectId}/apply-outlets`,
        { method: 'POST', body: { names, kind: 'city/region market term' } })
      toast(`Added ${names.length} place(s) — ${r.market_terms_count} market term(s) total now.`)
      window.location.reload()
    } catch (e) {
      toast(e.message, true)
    }
  }

  return (
    <>
      <HelpBox view="sources" />
      <Card title={<><Compass size={17} className="title-icon" /> Source plan</>}
        headExtra={<div className="actions">
          <button onClick={saveSources}>Save config</button>
        </div>}>

        <SuggestSourcesPanel projectId={projectId} onApplied={() => window.location.reload()} />

        <div className="note">🌏 <b>Market filter</b> — news items must show a signal they're in{' '}
          <b>{mkt.country || 'the market'}</b> (a market term appears, or the outlet uses{' '}
          <b>{mkt.cctld || 'the country domain'}</b>); otherwise they're dropped (this is what
          removes e.g. Indian coverage from a Malaysia study). Add cities/regions to sharpen it.</div>
        <label>Market terms (comma-separated) <span className="muted">country name matches its demonym automatically</span>
          <input value={marketTerms} onChange={(e) => setMarketTerms(e.target.value)}
            placeholder="e.g. Malaysia, Kuala Lumpur, KL, Selangor, Penang, Johor" />
        </label>
        <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '.8rem 0' }} />
        <div className="note">📎 <b>Add sources here — one per line.</b> URLs vary per study and are
          never fixed in the tool; this is where every channel's links live. Prefer keyword-search
          where URLs change constantly (e.g. e-commerce): give a <b>template with <code>{'{q}'}</code></b>{' '}
          + keywords instead of pasting a URL per product. Use ✨ Suggest sources to auto-propose &amp; validate.</div>
        <ListEditor label="Direct RSS feeds" hint="(feed-health-checked)" value={lists.rss_feeds}
          onChange={(v) => setLists((s) => ({ ...s, rss_feeds: v }))} />
        <ListEditor label="E-commerce — explicit product/category/search URLs" hint="" value={lists.ecommerce_urls}
          onChange={(v) => setLists((s) => ({ ...s, ecommerce_urls: v }))} />
        <ListEditor label="E-commerce — search-URL templates" hint="use {q} for the keyword, e.g. https://shopee.com.my/search?keyword={q}"
          value={lists.ecommerce_search} onChange={(v) => setLists((s) => ({ ...s, ecommerce_search: v }))} />
        <ListEditor label="E-commerce — keywords for the templates above" hint="defaults to relevance terms if empty"
          value={lists.ecommerce_keywords} onChange={(v) => setLists((s) => ({ ...s, ecommerce_keywords: v }))} />
        <ListEditor label="Forum thread/listing URLs" hint="" value={lists.forum_urls}
          onChange={(v) => setLists((s) => ({ ...s, forum_urls: v }))} />
        <ListEditor label="Quora question URLs" hint="" value={lists.quora_topics}
          onChange={(v) => setLists((s) => ({ ...s, quora_topics: v }))} />
        <ListEditor label="Subreddits (confirm candidates)" hint="" value={lists.subreddits}
          onChange={(v) => setLists((s) => ({ ...s, subreddits: v }))} />
        <div className="row" style={{ marginTop: '.6rem' }}>
          <button className="ghost" onClick={runFeedHealth} disabled={feedChecking}>
            {feedChecking ? 'Checking…' : 'Run feed health check'}
          </button>
        </div>
        {feedResults && (
          <div className="table-wrap"><table>
            <thead><tr><th>Feed</th><th>Status</th><th>Entries</th><th>Health</th></tr></thead>
            <tbody>{feedResults.map((f) => (
              <tr key={f.url}>
                <td>{f.url}</td><td>{f.status || '—'}</td><td>{f.entries}</td>
                <td>{f.healthy ? <span className="badge pos">healthy</span> : <span className="flag">DEAD: {f.reason}</span>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>

      <Card><h3>Google News feeds (generated)</h3>
        <p className="muted">Chunkable by date — used for full-year extensive research.</p>
        <FeedTable feeds={sp.google_news_feeds} />
      </Card>
      <Card><h3>Bing News feeds (generated)</h3>
        <p className="muted">A second, independent index — catches sources Google News's crawl missed.
          No date-range support, so this runs once per collection (not chunked).</p>
        <FeedTable feeds={sp.bing_news_feeds} />
      </Card>

      <Card><h3>Keyword slots per language</h3>
        {Object.entries(kwByLang).map(([lang, slots]) => (
          <fieldset key={lang}><legend>{lang}</legend>
            {Object.entries(slots).map(([slot, terms]) => (
              <label key={slot}>{slot}
                <input value={(terms || []).join(', ')} onChange={(e) => {
                  const vals = e.target.value.split(',').map((x) => x.trim()).filter(Boolean)
                  setKwByLang((prev) => ({ ...prev, [lang]: { ...prev[lang], [slot]: vals } }))
                }} />
              </label>
            ))}
          </fieldset>
        ))}
      </Card>

      <Card><h3>✨ Expand a term (AI)</h3>
        <p className="muted">A single narrow term (e.g. "coffee") hides everything adjacent to it:
          product variants (instant coffee, cold coffee, latte, cappuccino, americano...), real
          brand/shop names people search for instead (Starbucks, Costa Coffee...), and
          equivalents of all of that in this study's OTHER languages. Each one you add becomes
          its own keyword structure — its own feed, its own ~100-result ceiling — so this is
          also the main lever for a study's collectible volume, not just recall.</p>
        <div className="row">
          <label style={{ flex: 1 }}>Term to expand <span className="muted">defaults to the study's category</span>
            <input value={expandTerm} onChange={(e) => setExpandTerm(e.target.value)} placeholder="e.g. coffee" />
          </label>
          <button style={{ alignSelf: 'flex-end', height: '2.1rem' }} onClick={doExpandTerm} disabled={expanding}>
            {expanding ? 'Asking Claude…' : '✨ Expand'}
          </button>
        </div>
        {expansion && (
          <ExpansionResults r={expansion} checks={expChecks} setChecks={setExpChecks} onApply={applyExpansion} />
        )}
      </Card>

      <Card><h3>✨ Discover local outlets (AI)</h3>
        <p className="muted">The market filter only keeps items whose outlet or text shows a signal
          they're in this market — but most real local outlets (Scroll.in, NDTV, ScoopWhoop...)
          don't carry the country's name in their own brand, unlike "Times of India"/"Indian
          Express". This finds real local outlets across news, business, tech, sports,
          lifestyle, culture, and regional/native-language press, so genuinely local coverage
          from them stops being wrongly dropped. Each one you add teaches the filter that
          outlet, market-wide — no feed changes, this only affects relevance filtering.</p>
        <button onClick={doDiscoverOutlets} disabled={discoveringOutlets}>
          {discoveringOutlets ? 'Asking Claude…' : '✨ Discover outlets for this market'}
        </button>
        {outlets && (
          <OutletResults r={outlets} checked={checkedOutlets} setChecked={setCheckedOutlets} onApply={applyOutlets} />
        )}
      </Card>

      <Card><h3>✨ Suggest city/region market terms (AI)</h3>
        <p className="muted">Same market filter, one geographic level down: an article naming
          only a city or region — never the country itself — is genuinely in-market but
          currently invisible to the filter unless that place is already a market term.
          This finds REAL cities/regions in {mkt.country || 'this market'} that are
          specifically significant for <b>{cfg.product?.category || 'this category'}</b> (major
          consumption/manufacturing hubs, not just the biggest cities generically). Each one
          you add becomes a market term, market-wide.</p>
        <button onClick={doDiscoverGeoTerms} disabled={discoveringGeoTerms}>
          {discoveringGeoTerms ? 'Asking Claude…' : '✨ Suggest places for this category'}
        </button>
        {geoTerms && (
          <GeoTermResults r={geoTerms} checked={checkedGeoTerms} setChecked={setCheckedGeoTerms} onApply={applyGeoTerms} />
        )}
      </Card>
    </>
  )
}

function FeedTable({ feeds }) {
  if (!feeds?.length) {
    return <EmptyState icon={Rss} title="No feeds yet" hint="Add native-language keyword terms below." />
  }
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Lang</th><th>Structure</th><th>Query</th></tr></thead>
      <tbody>{feeds.map((f, i) => <tr key={i}><td>{f.language}</td><td>{f.structure}</td><td>{f.query}</td></tr>)}</tbody>
    </table></div>
  )
}

function ExpansionResults({ r, checks, setChecks, onApply }) {
  const toggleSet = (field, value) => setChecks((prev) => {
    const next = new Set(prev[field])
    next.has(value) ? next.delete(value) : next.add(value)
    return { ...prev, [field]: next }
  })
  const toggleTransVariant = (lang, value) => setChecks((prev) => {
    const entry = prev.translations[lang] || { term: '', variants: new Set() }
    const nextVariants = new Set(entry.variants)
    nextVariants.has(value) ? nextVariants.delete(value) : nextVariants.add(value)
    return { ...prev, translations: { ...prev.translations, [lang]: { ...entry, variants: nextVariants } } }
  })
  const toggleTransTerm = (lang, term) => setChecks((prev) => {
    const entry = prev.translations[lang] || { term: '', variants: new Set() }
    return { ...prev, translations: { ...prev.translations, [lang]: { ...entry, term: entry.term ? '' : term } } }
  })

  const hasAny = r.variants?.length || r.brands?.length || Object.keys(r.translations || {}).length
  return (
    <div className="card" style={{ borderColor: 'var(--primary)' }}>
      <div className="card-head"><h4>✨ Expansion of "{r.term}"</h4><button onClick={onApply}>Add checked to keywords</button></div>
      <p className="muted">AI-proposed — nothing is added until you click above. Uncheck anything
        irrelevant or wrong; a brand you check is also added to Competitors.</p>
      {!!r.variants?.length && <>
        <h5>Product variants ({r.variants.length})</h5>
        {r.variants.map((v) => (
          <label key={v} style={{ display: 'flex', gap: '.5rem', alignItems: 'center', fontWeight: 400, margin: '.2rem 0' }}>
            <input type="checkbox" checked={checks.variants.has(v)} style={{ width: 'auto' }} onChange={() => toggleSet('variants', v)} />
            <span>{v}</span>
          </label>
        ))}</>}
      {!!r.brands?.length && <>
        <h5 style={{ marginTop: '.6rem' }}>Real brands/shops in this market ({r.brands.length})</h5>
        {r.brands.map((b) => (
          <label key={b} style={{ display: 'flex', gap: '.5rem', alignItems: 'center', fontWeight: 400, margin: '.2rem 0' }}>
            <input type="checkbox" checked={checks.brands.has(b)} style={{ width: 'auto' }} onChange={() => toggleSet('brands', b)} />
            <span>{b} <span className="muted">(also added as a competitor)</span></span>
          </label>
        ))}</>}
      {!!Object.keys(r.translations || {}).length && <>
        <h5 style={{ marginTop: '.6rem' }}>Translations ({Object.keys(r.translations).length} language(s))</h5>
        {Object.entries(r.translations).map(([lang, entry]) => (
          <div style={{ margin: '.4rem 0' }} key={lang}>
            <b>{lang}</b>
            {entry.term && (
              <label style={{ display: 'flex', gap: '.5rem', alignItems: 'center', fontWeight: 400, margin: '.15rem 0 .15rem 1rem' }}>
                <input type="checkbox" checked={!!checks.translations[lang]?.term} style={{ width: 'auto' }}
                  onChange={() => toggleTransTerm(lang, entry.term)} />
                <span>{entry.term} <span className="muted">(base term)</span></span>
              </label>
            )}
            {(entry.variants || []).map((v) => (
              <label key={v} style={{ display: 'flex', gap: '.5rem', alignItems: 'center', fontWeight: 400, margin: '.15rem 0 .15rem 1rem' }}>
                <input type="checkbox" checked={!!checks.translations[lang]?.variants?.has(v)} style={{ width: 'auto' }}
                  onChange={() => toggleTransVariant(lang, v)} />
                <span>{v}</span>
              </label>
            ))}
          </div>
        ))}</>}
      {!hasAny && <p className="muted">Nothing came back — try a different term.</p>}
    </div>
  )
}

function OutletResults({ r, checked, setChecked, onApply }) {
  const toggle = (name) => setChecked((prev) => {
    const next = new Set(prev)
    next.has(name) ? next.delete(name) : next.add(name)
    return next
  })
  const s = r._summary || {}
  return (
    <div className="card" style={{ borderColor: 'var(--primary)' }}>
      <div className="card-head"><h4>✨ {s.total || 0} local outlets found</h4><button onClick={onApply}>Add checked to market terms</button></div>
      <p className="muted">AI-proposed — nothing is added until you click above.
        {s.caution ? ` ${s.caution} short name(s) are unchecked by default — a brief name
        that's also a common word is safer to review before trusting at scale.` : ''}</p>
      {(r.outlets || []).length ? r.outlets.map((o) => (
        <label key={o.name} style={{ display: 'flex', gap: '.5rem', alignItems: 'flex-start', fontWeight: 400, margin: '.25rem 0' }}>
          <input type="checkbox" checked={checked.has(o.name)} style={{ width: 'auto', marginTop: '.2rem' }}
            onChange={() => toggle(o.name)} />
          <span><b>{o.name}</b>{' '}
            {o.caution && <span className="flag">⚠ short name — check before adding</span>}
            <span className="badge neu">{o.category || '—'}</span>{' '}
            <span className="badge neu">{o.language || '—'}</span>
            <br /><span className="muted">{o.domain || ''}{o.why ? ` — ${o.why}` : ''}</span></span>
        </label>
      )) : <p className="muted">Nothing came back — try again in a moment.</p>}
    </div>
  )
}

function GeoTermResults({ r, checked, setChecked, onApply }) {
  const toggle = (name) => setChecked((prev) => {
    const next = new Set(prev)
    next.has(name) ? next.delete(name) : next.add(name)
    return next
  })
  const s = r._summary || {}
  return (
    <div className="card" style={{ borderColor: 'var(--primary)' }}>
      <div className="card-head"><h4>✨ {s.total || 0} place(s) found</h4><button onClick={onApply}>Add checked to market terms</button></div>
      <p className="muted">AI-proposed — nothing is added until you click above. Places already
        in your market terms are never re-suggested.</p>
      {(r.terms || []).length ? r.terms.map((t) => (
        <label key={t.name} style={{ display: 'flex', gap: '.5rem', alignItems: 'flex-start', fontWeight: 400, margin: '.25rem 0' }}>
          <input type="checkbox" checked={checked.has(t.name)} style={{ width: 'auto', marginTop: '.2rem' }}
            onChange={() => toggle(t.name)} />
          <span><b>{t.name}</b><br /><span className="muted">{t.why || ''}</span></span>
        </label>
      )) : <p className="muted">Nothing came back — try again in a moment.</p>}
    </div>
  )
}
