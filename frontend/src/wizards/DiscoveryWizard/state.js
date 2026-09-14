// Pure helpers for the discovery wizard's state, kept out of the component so they're
// trivially testable and so the component itself stays focused on rendering.

export function geoScopeOf(w) {
  if (!w.geoValue.trim()) return null
  const country = w.geoLevel === 'country' ? w.geoValue.trim() : w.geoCountry.trim()
  if (!country) return null
  return { level: w.geoLevel, value: w.geoValue.trim(), country }
}

// Merge newly-discovered sites into the existing list, deduping by domain, tagging
// each new one with the bucket (source-type genre, or seed-site expansion) it came
// from. Returns a NEW array (never mutates) so React state updates trigger correctly.
export function mergeSites(existing, newSites, bucket) {
  const seen = new Set(existing.map((s) => s.domain))
  const added = []
  for (const s of newSites) {
    if (seen.has(s.domain)) continue
    seen.add(s.domain)
    added.push({ ...s, bucket })
  }
  return { merged: [...existing, ...added], added }
}

export const STEP_NAMES = ['Term & geo', 'Category', 'Languages', 'Source types', 'Sites', 'Brand terms', 'Launch']

export function initialWizardState() {
  return {
    step: 0,
    term: '', brand: '', categoryType: 'other',
    geoLevel: 'country', geoValue: '', geoCountry: '',
    category: '', confidence: null, reasoning: '', needsConfirmation: false,
    languages: [], selectedLanguages: new Set(),
    sourceTypes: [], selectedSourceTypes: new Set(),
    sites: [], selectedDomains: new Set(), expandedDomains: new Set(), similarFoundCounts: {},
    termSuggestions: null, selectedVariants: new Set(), selectedBrands: new Set(),
    volumeCap: 500, runDaily: false,
  }
}
