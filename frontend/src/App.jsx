import { useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Compass, Plus } from 'lucide-react'
import { AppStateProvider, useAppState } from './state/AppState.jsx'
import { JobsProvider } from './state/JobsState.jsx'
import { ToastProvider } from './components/Toast.jsx'
import Sidebar from './components/Sidebar.jsx'
import Topbar from './components/Topbar.jsx'
import WorkflowStepper from './components/WorkflowStepper.jsx'
import LoginOverlay from './components/LoginOverlay.jsx'
import NewStudyWizard from './wizards/NewStudyWizard.jsx'
import DiscoveryWizard from './wizards/DiscoveryWizard/index.jsx'

import Overview from './views/Overview.jsx'
import SourcePlan from './views/SourcePlan.jsx'
import Collect from './views/Collect.jsx'
import RunLog from './views/RunLog.jsx'
import ResultsDashboard from './views/ResultsDashboard.jsx'
import Items from './views/Items.jsx'
import Analysis from './views/Analysis.jsx'
import MarketIntel from './views/MarketIntel.jsx'
import ManualIntel from './views/ManualIntel.jsx'
import Schedules from './views/Schedules.jsx'
import ExportView from './views/Export.jsx'

export default function App() {
  return (
    <ToastProvider>
      <AppStateProvider>
        <Shell />
      </AppStateProvider>
    </ToastProvider>
  )
}

function Shell() {
  const { booted, needsLogin, projects, projectId, project } = useAppState()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [discoveryOpen, setDiscoveryOpen] = useState(false)

  if (!booted) return null
  if (needsLogin) return <LoginOverlay />

  return (
    <JobsProvider projectId={projectId}>
      <div className="app-shell">
        <Sidebar />
        <div className="main-col">
          <Topbar onNewStudy={() => setWizardOpen(true)} onNewDiscovery={() => setDiscoveryOpen(true)} />
          <main>
            {projects.length === 0 || !project ? (
              <EmptyState onCreate={() => setWizardOpen(true)} />
            ) : (
              <>
                <WorkflowStepper />
                <Routes>
                  <Route path="/" element={<Navigate to="/overview" replace />} />
                  <Route path="/overview" element={<Overview />} />
                  <Route path="/sources" element={<SourcePlan />} />
                  <Route path="/collect" element={<Collect />} />
                  <Route path="/runlog" element={<RunLog />} />
                  <Route path="/results" element={<ResultsDashboard />} />
                  <Route path="/items" element={<Items />} />
                  <Route path="/analysis" element={<Analysis />} />
                  <Route path="/intel" element={<MarketIntel />} />
                  <Route path="/manual" element={<ManualIntel />} />
                  <Route path="/schedules" element={<Schedules />} />
                  <Route path="/export" element={<ExportView />} />
                  <Route path="*" element={<Navigate to="/overview" replace />} />
                </Routes>
              </>
            )}
          </main>
          <footer className="footer">
            <span className="muted">Decision-grade · honest feasibility · precision over volume</span>
          </footer>
        </div>
      </div>

      {wizardOpen && <NewStudyWizard onClose={() => setWizardOpen(false)} />}
      {discoveryOpen && <DiscoveryWizard onClose={() => setDiscoveryOpen(false)} />}
    </JobsProvider>
  )
}

function EmptyState({ onCreate }) {
  return (
    <div className="card empty-card">
      <div className="welcome-mark"><Compass size={26} strokeWidth={1.8} /></div>
      <h2>Welcome to MarketLens</h2>
      <p>Create a study to begin. Nothing here is hard-coded to any brand, category, or
        market — every value comes from the intake wizard.</p>
      <p className="muted">MarketLens works in four steps, always in this order:{' '}
        <b>1) Configure → 2) Collect → 3) Analyze → 4) Export.</b>{' '}
        Filling the source plan only says <i>where</i> to look; you still have to run
        Collect and Analyze before a report has anything in it.</p>
      <button onClick={onCreate}><Plus size={15} /> Create your first study</button>
    </div>
  )
}
