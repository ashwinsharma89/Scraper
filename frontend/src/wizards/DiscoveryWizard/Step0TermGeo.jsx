export default function Step0TermGeo({ w, patch }) {
  const geoLabel = w.geoLevel === 'country' ? 'Country'
    : w.geoLevel === 'state' ? 'State / province'
      : w.geoLevel === 'region' ? 'Region' : 'City'

  return (
    <>
      <label>What are you researching?
        <input value={w.term} onChange={(e) => patch({ term: e.target.value })}
          placeholder="e.g. coffee, two-wheeler insurance" />
      </label>
      <label>Brand name (optional)
        <input value={w.brand} onChange={(e) => patch({ brand: e.target.value })} placeholder="e.g. Acme Cola" />
      </label>
      <label>Geo-scope level
        <select value={w.geoLevel} onChange={(e) => patch({ geoLevel: e.target.value })}>
          <option value="country">Country</option>
          <option value="state">State / province</option>
          <option value="region">Region</option>
          <option value="city">City</option>
        </select>
      </label>
      <label>{geoLabel}
        <input value={w.geoValue} onChange={(e) => patch({ geoValue: e.target.value })} placeholder="e.g. India" />
      </label>
      {w.geoLevel !== 'country' && (
        <label>Which country is that in?
          <input value={w.geoCountry} onChange={(e) => patch({ geoCountry: e.target.value })} placeholder="e.g. India" />
        </label>
      )}
      <p className="muted">A city/state/region study still needs its country named, so market facts
        (currency, language defaults, etc.) resolve correctly.</p>
    </>
  )
}

export async function advanceFrom0(w, patch, api, geoScope) {
  const term = w.term.trim()
  const geoValue = w.geoValue.trim()
  const geoCountry = w.geoLevel === 'country' ? geoValue : w.geoCountry.trim()
  if (!term) throw new Error("Tell us what you're researching (a product, category, or topic).")
  if (!geoValue) throw new Error('Geo-scope value is required.')
  if (w.geoLevel !== 'country' && !geoCountry) throw new Error("That location's country is required.")

  const r = await api('/api/discovery/classify-category', {
    method: 'POST', body: { term, geo_scope: geoScope({ ...w, term, geoValue, geoCountry }) },
  })
  patch({
    term, geoValue, geoCountry,
    category: r.category, confidence: r.confidence,
    reasoning: r.reasoning, needsConfirmation: r.needs_confirmation,
  })
}
