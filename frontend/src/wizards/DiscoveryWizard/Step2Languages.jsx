import { useState } from 'react'

export default function Step2Languages({ w, patch }) {
  const [manual, setManual] = useState('')

  function toggle(code, checked) {
    const next = new Set(w.selectedLanguages)
    if (checked) next.add(code); else next.delete(code)
    patch({ selectedLanguages: next })
  }

  if (!w.languages.length) {
    return (
      <>
        <p className="muted">No languages suggested — add at least one code manually.</p>
        <label>Language code <input value={manual} onChange={(e) => { setManual(e.target.value); patch({ _manualLang: e.target.value }) }} placeholder="e.g. en" /></label>
      </>
    )
  }

  return (
    <>
      <p>Confirm which languages this study should cover:</p>
      <div className="pick-list">
        {w.languages.map((l) => (
          <label className="pick-row" key={l.code}>
            <input type="checkbox" checked={w.selectedLanguages.has(l.code)}
              onChange={(e) => toggle(l.code, e.target.checked)} />
            <div className="pick-main">
              <div className="pick-name">{l.name || l.code} ({l.code})
                {!l.known && <span className="badge neu"> unrecognized code</span>}</div>
              <div className="pick-why">{l.why || ''}</div>
            </div>
          </label>
        ))}
      </div>
      <label>Add another code (optional)
        <input value={manual} onChange={(e) => { setManual(e.target.value); patch({ _manualLang: e.target.value }) }} placeholder="e.g. te" />
      </label>
    </>
  )
}

export async function advanceFrom2(w, patch, api, geoScope) {
  const selected = new Set(w.selectedLanguages)
  const manual = (w._manualLang || '').trim()
  if (manual) selected.add(manual)
  if (selected.size === 0) throw new Error('Select or add at least one language.')

  const r = await api('/api/discovery/suggest-source-types', {
    method: 'POST', body: { category: w.category, geo_scope: geoScope(w) },
  })
  // Tier-3/app-only platforms (Instagram, WhatsApp, ...) are shown but never
  // pre-selected -- there is no real mechanism to collect from them (CLAUDE.md's
  // documented, permanent gap), so defaulting them "on" would misleadingly suggest
  // this study will cover them.
  patch({
    selectedLanguages: selected, _manualLang: '',
    sourceTypes: r.source_types,
    selectedSourceTypes: new Set(r.source_types.filter((s) => s.strategy !== 'unsupported').map((s) => s.name)),
  })
}
