import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useToast } from '../components/Toast.jsx'
import Modal from '../components/Modal.jsx'

// HANDOFF §7 item 3: "Edit-study-settings form (change market/brand/competitors and
// regenerate the source plan in place — today the market is only set at wizard
// time)." Field layout mirrors NewStudyWizard.jsx for consistency, but pre-filled
// from the project's current config and posting to /update-settings instead of
// /wizard — that endpoint preserves every hand-filled source_plan URL list and every
// existing language's keyword structures (see config.update_settings()'s docstring).
export default function EditSettingsModal({ project, onClose, onSaved }) {
  const toast = useToast()
  const cfg = project.config
  const mkt = cfg.market || {}
  const prod = cfg.product || {}

  const [countries, setCountries] = useState([])
  const [languages, setLanguages] = useState([])
  const [countriesError, setCountriesError] = useState('')
  const [languagesError, setLanguagesError] = useState('')

  const [pickedCountries, setPickedCountries] = useState([mkt.country].filter(Boolean))
  const [countryOther, setCountryOther] = useState('')
  const [pickedLanguages, setPickedLanguages] = useState(mkt.languages || [])
  const [languagesOther, setLanguagesOther] = useState('')
  const [brand, setBrand] = useState(prod.brand || '')
  const [parentCompany, setParentCompany] = useState(prod.parent_company || '')
  const [category, setCategory] = useState(prod.category || '')
  const [categoryType, setCategoryType] = useState(prod.category_type || 'other')
  const [competitors, setCompetitors] = useState((cfg.competitors || []).join(', '))
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api('/api/reference/countries').then(setCountries).catch((e) => setCountriesError(e.message))
    api('/api/reference/languages').then(setLanguages).catch((e) => setLanguagesError(e.message))
  }, [])

  const csv = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)
  const toggleMulti = (setter) => (e) => setter([...e.target.selectedOptions].map((o) => o.value))

  const countryChanging = pickedCountries[0] && pickedCountries[0] !== mkt.country
  const willDropGeoScope = mkt.geo_scope && (countryChanging || countryOther.trim())

  async function onSubmit(e) {
    e.preventDefault()
    const brandTrim = brand.trim()
    const categoryTrim = category.trim()
    if (!brandTrim && !categoryTrim) {
      toast('Provide a brand name, a product category, or both.', true)
      return
    }
    const otherCountry = countryOther.trim()
    const countryCandidates = [...pickedCountries, ...(otherCountry ? [otherCountry] : [])]
    if (countryCandidates.length === 0) {
      toast('Select a country/region, or type one in "Other".', true)
      return
    }
    if (countryCandidates.length > 1) {
      toast(`A study targets one country/region — you selected ${countryCandidates.length} `
        + `(${countryCandidates.join(', ')}). Pick just one.`, true)
      return
    }
    const langs = [...new Set([...pickedLanguages, ...csv(languagesOther)])]

    setSubmitting(true)
    try {
      const r = await api(`/api/projects/${project.id}/update-settings`, {
        method: 'POST',
        body: {
          market: { country: countryCandidates[0], languages: langs.length ? langs : ['en'] },
          product: { brand: brandTrim, parent_company: parentCompany, category: categoryTrim, category_type: categoryType },
          competitors: csv(competitors),
        },
      })
      toast(`Settings updated — ${r.google_news_feeds} Google News + ${r.bing_news_feeds} Bing News feed(s) regenerated.`)
      onSaved()
    } catch (err) {
      toast(err.message, true)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal title="Edit study settings" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <p className="muted">Existing RSS/e-commerce/forum URLs, hand-edited keyword slots,
          and anything added via ✨ Suggest sources / Expand a term / Discover outlets are
          all preserved — only market/brand/competitor-derived fields are recomputed.</p>
        <fieldset>
          <legend>Market</legend>
          <label>Country / region
            <select multiple size={6} value={pickedCountries} onChange={toggleMulti(setPickedCountries)}>
              {countriesError
                ? <option disabled>Couldn't load — {countriesError}. Use "Other" below, or reload the page.</option>
                : countries.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <label>Other country/region (optional — if not in the list above)
            <input value={countryOther} onChange={(e) => setCountryOther(e.target.value)} placeholder="e.g. Luxembourg" />
          </label>
          <label>Target languages
            <select multiple size={8} value={pickedLanguages} onChange={toggleMulti(setPickedLanguages)}>
              {languagesError
                ? <option disabled>Couldn't load — {languagesError}. Use "Other" below, or reload the page.</option>
                : languages.map((l) => <option key={l.code} value={l.code}>{l.name} ({l.code})</option>)}
            </select>
          </label>
          <label>Other language codes (optional, comma-separated)
            <input value={languagesOther} onChange={(e) => setLanguagesOther(e.target.value)} placeholder="e.g. haw, gsw" />
          </label>
          {willDropGeoScope && (
            <p className="note">⚠ This study has a state/region/city scope ({mkt.geo_scope.value}).
              Changing the country will drop it back to a plain country-level study — re-run the
              Discovery wizard's geo-scope step if you need a new sub-country scope.</p>
          )}
        </fieldset>
        <fieldset>
          <legend>Product</legend>
          <label>Brand name (optional) <input value={brand} onChange={(e) => setBrand(e.target.value)} /></label>
          <label>Parent company (optional) <input value={parentCompany} onChange={(e) => setParentCompany(e.target.value)} /></label>
          <label>Category <input value={category} onChange={(e) => setCategory(e.target.value)} /></label>
          <label>Category type
            <select value={categoryType} onChange={(e) => setCategoryType(e.target.value)}>
              <option value="fmcg_food">FMCG / food</option>
              <option value="consumer_electronics">Consumer electronics</option>
              <option value="fashion">Fashion</option>
              <option value="services">Services</option>
              <option value="b2b_industrial">B2B / industrial</option>
              <option value="other">Other</option>
            </select>
          </label>
        </fieldset>
        <fieldset>
          <legend>Competitors</legend>
          <label>Competitor brands (comma-separated)
            <input value={competitors} onChange={(e) => setCompetitors(e.target.value)} placeholder="e.g. Fizzly, PopMax" />
          </label>
        </fieldset>
        <div className="actions">
          <button type="submit" disabled={submitting}>{submitting ? 'Saving…' : 'Save settings'}</button>
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  )
}
