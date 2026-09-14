import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import Modal from '../components/Modal.jsx'
import SuggestSourcesPanel from '../components/SuggestSourcesPanel.jsx'
import { useNavigate } from 'react-router-dom'

// The original single-form intake wizard, ported field-for-field from
// static/index.html's #wizard-form + static/app.js's submit handler. The AI-guided
// wizard (DiscoveryWizard) is the newer, richer flow -- this one stays for a quick,
// manually-specified study.
export default function NewStudyWizard({ onClose }) {
  const { loadProjects, selectProject } = useAppState()
  const toast = useToast()
  const navigate = useNavigate()

  const [countries, setCountries] = useState([])
  const [languages, setLanguages] = useState([])
  const [countriesError, setCountriesError] = useState('')
  const [languagesError, setLanguagesError] = useState('')

  const [pickedCountries, setPickedCountries] = useState([])
  const [countryOther, setCountryOther] = useState('')
  const [pickedLanguages, setPickedLanguages] = useState([])
  const [languagesOther, setLanguagesOther] = useState('')
  const [brand, setBrand] = useState('')
  const [parentCompany, setParentCompany] = useState('')
  const [category, setCategory] = useState('')
  const [categoryType, setCategoryType] = useState('fmcg_food')
  const [competitors, setCompetitors] = useState('')
  const [trendTerms, setTrendTerms] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // HANDOFF §7 item 1: "Suggested-RSS-feeds baked into the wizard per country" —
  // once the study exists, offer the exact same ✨ Suggest sources → validate →
  // confirm flow right here instead of requiring the user to remember Source plan
  // afterward. Non-null once creation succeeds; its presence switches the modal to
  // this second, final step.
  const [createdProject, setCreatedProject] = useState(null)

  useEffect(() => {
    api('/api/reference/countries').then(setCountries).catch((e) => setCountriesError(e.message))
    api('/api/reference/languages').then(setLanguages).catch((e) => setLanguagesError(e.message))
  }, [])

  const csv = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)

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

    const intake = {
      name: brandTrim || categoryTrim,
      market: { country: countryCandidates[0], languages: langs.length ? langs : ['en'] },
      product: { brand: brandTrim, parent_company: parentCompany, category: categoryTrim, category_type: categoryType },
      competitors: csv(competitors),
      keywords: { trend_terms: csv(trendTerms) },
    }
    setSubmitting(true)
    try {
      const r = await api('/api/projects/wizard', { method: 'POST', body: intake })
      // Real bug found live: loadProjects() alone keeps whatever project was ALREADY
      // selected if it still exists in the list (it always does here) -- creating a
      // new study while another was open silently left that OTHER study showing.
      // selectProject() explicitly switches focus to the one just created, so the
      // SuggestSourcesPanel step below (and the sidebar dropdown) both reflect it.
      await loadProjects()
      await selectProject(r.id)
      toast(`Study "${r.name}" created`)
      setCreatedProject(r) // switch to the post-creation "suggest sources" step, below
    } catch (err) {
      toast(err.message, true)
    } finally {
      setSubmitting(false)
    }
  }

  function finishAndGoToCollect() {
    onClose()
    navigate('/collect')
  }

  const toggleMulti = (setter) => (e) =>
    setter([...e.target.selectedOptions].map((o) => o.value))

  if (createdProject) {
    return (
      <Modal title="New study — intake wizard" onClose={finishAndGoToCollect}>
        <p><b>"{createdProject.name}"</b> created. Optionally, let AI suggest real news RSS
          feeds (+ e-commerce/forum candidates) for this market right now — each one is
          validated (feed-health-checked / reachability-checked) before you confirm it,
          exactly like Source plan's own ✨ Suggest sources.</p>
        <SuggestSourcesPanel projectId={createdProject.id} onApplied={() => {}} />
        <div className="actions">
          <button type="button" onClick={finishAndGoToCollect}>Done — go to Collect</button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title="New study — intake wizard" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <fieldset>
          <legend>Market</legend>
          <label>Country / region
            <select multiple size={6} value={pickedCountries} onChange={toggleMulti(setPickedCountries)}>
              {countriesError
                ? <option disabled>Couldn't load — {countriesError}. Use "Other" below, or reload the page.</option>
                : countries.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <p className="muted">A study targets one market — click to select it. (Cmd/Ctrl-click
            also works, but only one country per study is allowed.)</p>
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
          <p className="muted">Click to select one, or Cmd/Ctrl-click (Shift-click for a range) to select several.</p>
          <label>Other language codes (optional, comma-separated — if not in the list above)
            <input value={languagesOther} onChange={(e) => setLanguagesOther(e.target.value)} placeholder="e.g. haw, gsw" />
          </label>
        </fieldset>
        <fieldset>
          <legend>Product</legend>
          <p className="muted">Give a brand name, a product category, or both — e.g. a
            category-only study of "instant noodles in Malaysia" with no single target brand is fine.</p>
          <label>Brand name (optional) <input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="e.g. Acme Cola" /></label>
          <label>Parent company (optional) <input value={parentCompany} onChange={(e) => setParentCompany(e.target.value)} /></label>
          <label>Category <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. carbonated soft drinks" /></label>
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
        <fieldset>
          <legend>Trend / issue terms</legend>
          <label>Trend terms (comma-separated) — seed the trend taxonomy
            <input value={trendTerms} onChange={(e) => setTrendTerms(e.target.value)} placeholder="e.g. sugar-free, sustainability, local flavor" />
          </label>
          <p className="muted">Native-language keyword slots (brand, brand+price, category-generic,
            brand+complaint) are scaffolded per language after creation — fill them in the
            Source plan tab. Nothing is pre-filled with any real third-party brand.</p>
        </fieldset>
        <div className="actions">
          <button type="submit" disabled={submitting}>{submitting ? 'Creating…' : 'Create study'}</button>
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  )
}
