import { useState } from 'react'
import { mergeSites } from './state.js'

function SimilarNote({ domain, w }) {
  const found = w.similarFoundCounts[domain]
  if (found === undefined) return null
  return found > 0
    ? <span className="muted">+ found {found} similar site{found === 1 ? '' : 's'}</span>
    : <span className="muted">No additional similar sites found.</span>
}

export default function Step4Sites({ w, patch, api, geoScope }) {
  const [expanding, setExpanding] = useState(null) // domain currently being expanded
  const [expandError, setExpandError] = useState({}) // domain -> message

  async function onToggle(domain, checked) {
    const nextSelected = new Set(w.selectedDomains)
    if (checked) nextSelected.add(domain); else { nextSelected.delete(domain); patch({ selectedDomains: nextSelected }); return }
    patch({ selectedDomains: nextSelected })

    if (w.expandedDomains.has(domain)) return // never re-expand the same seed twice
    patch({ expandedDomains: new Set(w.expandedDomains).add(domain) })
    setExpanding(domain)
    setExpandError((e) => ({ ...e, [domain]: undefined }))
    try {
      const r = await api('/api/discovery/similar-sites', {
        method: 'POST', body: { domain, category: w.category, geo_scope: geoScope(w) },
      })
      const bucket = w.sites.find((s) => s.domain === domain)?.bucket || ''
      const { merged, added } = mergeSites(w.sites, r.sites, bucket)
      const withSelections = new Set(w.selectedDomains)
      withSelections.add(domain)
      added.forEach((s) => withSelections.add(s.domain)) // auto-select, matching the ask
      patch({
        sites: merged,
        selectedDomains: withSelections,
        similarFoundCounts: { ...w.similarFoundCounts, [domain]: added.length },
      })
    } catch (e) {
      setExpandError((prev) => ({ ...prev, [domain]: e.message }))
    } finally {
      setExpanding(null)
    }
  }

  if (!w.sites.length) {
    return <p className="muted">No candidate sites found for this category/market.</p>
  }

  const buckets = [...new Set(w.sites.map((s) => s.bucket || ''))]

  // Bulk select for a bucket sets selectedDomains directly rather than routing through
  // onToggle: onToggle's side effect (auto-expanding to similar sites, one Claude call
  // per NEW domain) is meant for a deliberate single click, not something 20 simultaneous
  // checks should each separately trigger. Real friction fixed here: "every site has to
  // be selected manually by a checkbox" once a bucket returns many real sites.
  function setManyChecked(domains, checked) {
    const next = new Set(w.selectedDomains)
    domains.forEach((d) => (checked ? next.add(d) : next.delete(d)))
    patch({ selectedDomains: next })
  }

  const allDomains = w.sites.map((s) => s.domain)
  const allChecked = allDomains.length > 0 && allDomains.every((d) => w.selectedDomains.has(d))

  return (
    <>
      <p>Confirm which real sites to actually collect from. Sites with a proven track
        record are pre-checked; new/unverified ones need your explicit OK. Checking a
        site automatically looks for other real sites of the same kind.</p>
      <div className="row" style={{ marginBottom: '.4rem' }}>
        <button type="button" className="ghost" onClick={() => setManyChecked(allDomains, !allChecked)}>
          {allChecked ? 'Deselect all' : `Select all ${w.sites.length}`}
        </button>
      </div>
      {buckets.map((bucket) => {
        const bucketDomains = w.sites.filter((s) => (s.bucket || '') === bucket).map((s) => s.domain)
        const bucketAllChecked = bucketDomains.every((d) => w.selectedDomains.has(d))
        return (
        <div key={bucket || '_'}>
          {bucket && (
            <h3 className="pick-bucket" style={{ display: 'flex', alignItems: 'center', gap: '.6rem' }}>
              {bucket}
              <button type="button" className="link-btn" style={{ fontWeight: 400, fontSize: '.8em' }}
                onClick={() => setManyChecked(bucketDomains, !bucketAllChecked)}>
                {bucketAllChecked ? 'clear' : `select all ${bucketDomains.length}`}
              </button>
            </h3>
          )}
          <div className="pick-list">
            {w.sites.filter((s) => (s.bucket || '') === bucket).map((s) => (
              <label className="pick-row" key={s.domain}>
                <input type="checkbox" checked={w.selectedDomains.has(s.domain)}
                  onChange={(e) => onToggle(s.domain, e.target.checked)} />
                <div className="pick-main">
                  <div className="pick-name">{s.name || s.domain} <span className="muted">({s.domain})</span>
                    {s.known && <span className="badge tier1">known</span>}
                    {s.needs_validation && <span className="needs-badge">needs validation</span>}
                    {s.validated_by_human && <span className="badge tier1">human-validated</span>}
                  </div>
                  <div className="pick-why">{s.why || ''}
                    {!!s.times_used && ` · used ${s.times_used}× before, confidence ${Math.round((s.confidence || 0) * 100)}%`}
                  </div>
                  <div className="pick-similar">
                    {expanding === s.domain
                      ? <span className="spinner-line">Finding similar sites…</span>
                      : expandError[s.domain]
                        ? <span className="muted">Couldn't find similar sites: {expandError[s.domain]}</span>
                        : <SimilarNote domain={s.domain} w={w} />}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>
        )
      })}
    </>
  )
}

export async function advanceFrom4(w, patch, api) {
  const draftCfg = {
    market: { country: w.geoCountry, languages: [...w.selectedLanguages] },
    product: { brand: w.brand, category: w.category, category_type: w.categoryType },
    relevance_terms: [w.category],
  }
  const r = await api('/api/discovery/suggest-terms-draft', {
    method: 'POST', body: { cfg: draftCfg, term: w.category },
  })
  patch({
    termSuggestions: r,
    selectedVariants: new Set(r.variants || []),
    selectedBrands: new Set(r.brands || []),
  })
}
