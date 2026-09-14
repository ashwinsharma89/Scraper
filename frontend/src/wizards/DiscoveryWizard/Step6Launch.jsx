export default function Step6Launch({ w, patch }) {
  const genericDomains = [...w.selectedDomains]
  return (
    <>
      <div className="card">
        <p><b>Category:</b> {w.category}</p>
        <p><b>Geo-scope:</b> {w.geoLevel} — {w.geoValue} ({w.geoCountry})</p>
        <p><b>Languages:</b> {[...w.selectedLanguages].join(', ')}</p>
        <p><b>Source types:</b> {[...w.selectedSourceTypes].join(', ')}</p>
        {genericDomains.length > 0 && <p><b>Sites to collect from:</b> {genericDomains.join(', ')}</p>}
      </div>
      <label>Per-source volume cap
        <input type="number" min="10" value={w.volumeCap}
          onChange={(e) => patch({ volumeCap: parseInt(e.target.value || '500', 10) })} />
      </label>
      <label style={{ display: 'flex', alignItems: 'center', gap: '.4rem', fontWeight: 600 }}>
        <input type="checkbox" checked={w.runDaily} style={{ width: 'auto' }}
          onChange={(e) => patch({ runDaily: e.target.checked })} />
        Also run this as a standing daily job
      </label>
      {w.runDaily && (
        <div className="note">Daily scheduling isn't wired up yet — this just records the
          intent; you'll need to re-run the backfill manually for now.</div>
      )}
      {genericDomains.length > 0 && (
        <p className="muted">Clicking Launch confirms these sites into the shared
          site-intelligence ledger and starts a real backfill job in the background —
          you can watch its progress in the Run log tab once the study opens.</p>
      )}
    </>
  )
}

export async function launch(w, api) {
  const geoScope = { level: w.geoLevel, value: w.geoValue, country: w.geoCountry }
  const intake = {
    name: w.brand || w.category,
    market: { country: w.geoCountry, languages: [...w.selectedLanguages], geo_scope: geoScope },
    product: { brand: w.brand, category: w.category, category_type: w.categoryType },
    competitors: [...w.selectedBrands],
    keywords: { trend_terms: [] },
  }
  const payload = {
    intake,
    generic_site_domains: [...w.selectedDomains],
    keywords: [w.category, ...w.selectedVariants],
    volume_cap: w.volumeCap,
    run_daily: w.runDaily,
  }
  if (w.termSuggestions && (w.selectedVariants.size || w.selectedBrands.size)) {
    payload.term_expansion = {
      term: w.category,
      variants: [...w.selectedVariants],
      brands: [...w.selectedBrands],
      translations: w.termSuggestions.translations || {},
    }
  }
  return api('/api/discovery/launch-study', { method: 'POST', body: payload })
}
