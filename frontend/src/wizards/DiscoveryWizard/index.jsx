import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api.js'
import { useAppState } from '../../state/AppState.jsx'
import { useToast } from '../../components/Toast.jsx'
import Modal from '../../components/Modal.jsx'
import { geoScopeOf, initialWizardState, STEP_NAMES } from './state.js'

import Step0TermGeo, { advanceFrom0 } from './Step0TermGeo.jsx'
import Step1Category, { advanceFrom1 } from './Step1Category.jsx'
import Step2Languages, { advanceFrom2 } from './Step2Languages.jsx'
import Step3SourceTypes, { advanceFrom3 } from './Step3SourceTypes.jsx'
import Step4Sites, { advanceFrom4 } from './Step4Sites.jsx'
import Step5BrandTerms, { advanceFrom5 } from './Step5BrandTerms.jsx'
import Step6Launch, { launch } from './Step6Launch.jsx'

const ADVANCERS = [advanceFrom0, advanceFrom1, advanceFrom2, advanceFrom3, advanceFrom4, advanceFrom5]

export default function DiscoveryWizard({ onClose }) {
  const [w, setW] = useState(initialWizardState())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { loadProjects } = useAppState()
  const toast = useToast()
  const navigate = useNavigate()

  const patch = (partial) => setW((prev) => ({ ...prev, ...partial }))
  const geoScope = (state = w) => geoScopeOf(state)

  const hasGenericSiteType = w.sourceTypes.some(
    (s) => w.selectedSourceTypes.has(s.name) && s.strategy === 'generic_site_discovery')

  async function onNext() {
    setError('')
    if (w.step === STEP_NAMES.length - 1) {
      setBusy(true)
      try {
        const r = await launch(w, api)
        onClose()
        toast(r.run_id ? `Study "${r.name}" launched — collection running in the background`
          : `Study "${r.name}" created`)
        await loadProjects()
        navigate(r.run_id ? '/runlog' : '/collect')
      } catch (e) {
        setError(e.message)
        setBusy(false)
      }
      return
    }

    setBusy(true)
    try {
      const advance = ADVANCERS[w.step]
      const before = w.step
      // Each advanceFromN() call patches state itself (category, languages, sites, ...);
      // step 3's advancer sets _skipSitesStep when nothing routes to site discovery, in
      // which case we jump straight from step 3 to step 5 (Brand terms), skipping 4 (Sites).
      let skipSitesStep = false
      await advance(w, (partial) => {
        if (partial._skipSitesStep) skipSitesStep = true
        patch(partial)
      }, api, geoScope)
      patch({ step: skipSitesStep ? before + 2 : before + 1 })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function onBack() {
    if (w.step === 0) return
    let prevStep = w.step - 1
    if (prevStep === 4 && w.sites.length === 0 && !hasGenericSiteType) prevStep -= 1
    patch({ step: prevStep })
  }

  const StepComponent = [Step0TermGeo, Step1Category, Step2Languages, Step3SourceTypes, Step4Sites, Step5BrandTerms, Step6Launch][w.step]

  return (
    <Modal title="AI-guided study" onClose={onClose}>
      <div className="disc-steps">
        {STEP_NAMES.map((name, i) => (
          <div key={name} className={`disc-dot ${i < w.step ? 'done' : i === w.step ? 'current' : ''}`}>
            {i + 1}. {name}
          </div>
        ))}
      </div>
      <div>
        <StepComponent w={w} patch={patch} api={api} geoScope={geoScope} />
      </div>
      <p className="error">{error}</p>
      <div className="actions">
        <button type="button" className="ghost" disabled={w.step === 0 || busy} onClick={onBack}>Back</button>
        <button type="button" disabled={busy} onClick={onNext}>
          {busy ? 'Working…' : w.step === STEP_NAMES.length - 1 ? 'Launch study' : 'Next'}
        </button>
        <button type="button" className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}
