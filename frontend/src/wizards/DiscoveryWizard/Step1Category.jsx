export default function Step1Category({ w, patch }) {
  const confCls = (w.confidence ?? 0) >= 0.8 ? 'confidence-hi' : 'confidence-lo'
  return (
    <>
      <p>AI classification of "<b>{w.term}</b>":</p>
      <label>Category
        <input value={w.category} onChange={(e) => patch({ category: e.target.value })} />
      </label>
      <p className="muted">Confidence: <span className={confCls}>{Math.round((w.confidence || 0) * 100)}%</span></p>
      <p className="muted">{w.reasoning || ''}</p>
      {w.needsConfirmation && (
        <div className="note">The model flagged this as a lower-confidence guess — please
          check the category text above before continuing.</div>
      )}
    </>
  )
}

export async function advanceFrom1(w, patch, api, geoScope) {
  const category = w.category.trim()
  if (!category) throw new Error('Category is required.')
  const r = await api('/api/discovery/suggest-languages', {
    method: 'POST', body: { category, geo_scope: geoScope({ ...w, category }) },
  })
  patch({
    category,
    languages: r.languages,
    selectedLanguages: new Set(r.languages.map((l) => l.code)),
  })
}
