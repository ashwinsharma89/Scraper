import { mergeSites } from './state.js'

export default function Step3SourceTypes({ w, patch }) {
  function toggle(name, checked) {
    const next = new Set(w.selectedSourceTypes)
    if (checked) next.add(name); else next.delete(name)
    patch({ selectedSourceTypes: next })
  }

  if (!w.sourceTypes.length) {
    return <p className="muted">No source types suggested for this category.</p>
  }

  return (
    <>
      <p>Which kinds of sources should this study collect from?</p>
      <div className="pick-list">
        {w.sourceTypes.map((s) => {
          const unsupported = s.strategy === 'unsupported'
          const badge = s.strategy === 'existing_channel'
            ? <span className="badge tier1">{s.channel} channel</span>
            : unsupported ? <span className="badge tier3">not supported</span>
              : <span className="badge tier2">new: site discovery</span>
          return (
            <label className="pick-row" key={s.name}>
              <input type="checkbox" checked={w.selectedSourceTypes.has(s.name)} disabled={unsupported}
                onChange={(e) => toggle(s.name, e.target.checked)} />
              <div className="pick-main">
                <div className="pick-name">{s.name} {badge}</div>
                <div className="pick-why">{s.why || ''}
                  {unsupported && ' — app-only/anti-automation platform; MarketLens has no way to collect from this (documented gap, not a bug).'}
                </div>
              </div>
            </label>
          )
        })}
      </div>
    </>
  )
}

export async function advanceFrom3(w, patch, api, geoScope) {
  if (w.selectedSourceTypes.size === 0) throw new Error('Select at least one source type.')
  const genericTypes = w.sourceTypes.filter(
    (s) => w.selectedSourceTypes.has(s.name) && s.strategy === 'generic_site_discovery')

  if (genericTypes.length === 0) {
    patch({ sites: [], selectedDomains: new Set(), _skipSitesStep: true })
    return
  }

  // One discovery call PER selected genre, not one blended call across all of them --
  // a single category-wide call kept surfacing the same handful of mainstream outlets,
  // crowding out smaller/specialist sites (food blogs, forums) a genre-scoped call finds.
  const results = await Promise.all(genericTypes.map((st) =>
    api('/api/discovery/sites', {
      method: 'POST',
      body: { category: w.category, geo_scope: geoScope(w), source_type_hint: st.name },
    })))

  let sites = []
  results.forEach((r, i) => { sites = mergeSites(sites, r.sites, genericTypes[i].name).merged })

  patch({
    sites,
    expandedDomains: new Set(),
    similarFoundCounts: {},
    selectedDomains: new Set(sites.filter((s) => !s.needs_validation).map((s) => s.domain)),
    _skipSitesStep: false,
  })
}
