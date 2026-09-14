import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useToast } from '../components/Toast.jsx'

const JobsContext = createContext(null)

// Live job status tracker, visible from every tab (not just Collect) via the topbar
// chip -- ported from static/app.js's startJobsWatcher()/pollJobsOnce(), which itself
// replaced an earlier version that only ever polled a single job at a time (a real,
// user-reported gap: multiple queued jobs went stale in the UI until a manual reload).
// In React this is just a polling interval driving state -- no manual DOM patching,
// so the "busy re-render wipes user input" class of bug found in the vanilla wizard
// structurally can't happen here the same way.
export function JobsProvider({ projectId, children }) {
  const [jobs, setJobs] = useState([])
  const toast = useToast()
  const announced = useRef(new Set())
  const primed = useRef(false)
  const intervalRef = useRef(null)

  const poll = useCallback(async () => {
    if (!projectId) return
    let list
    try {
      list = await api(`/api/projects/${projectId}/jobs`)
    } catch {
      return // a transient fetch error shouldn't kill the watcher
    }
    setJobs(list)

    const firstPoll = !primed.current
    primed.current = true
    for (const j of list) {
      if ((j.status === 'done' || j.status === 'error') && !announced.current.has(j.id)) {
        announced.current.add(j.id)
        if (!firstPoll) {
          const s = j.summary || {}
          toast(`Job #${j.id} (${j.channel}) ${j.status}: +${s.new || 0} new / ${s.duplicate || 0} dup`,
            j.status === 'error')
        }
      }
    }

    const active = list.some((j) => j.status === 'queued' || j.status === 'running')
    if (!active && intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [projectId, toast])

  const startWatching = useCallback(() => {
    if (intervalRef.current) return
    intervalRef.current = setInterval(poll, 1500)
    poll()
  }, [poll])

  // Reset per-project state and pick up anything already running/queued.
  useEffect(() => {
    announced.current = new Set()
    primed.current = false
    setJobs([])
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    if (projectId) startWatching()
    return () => {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const activeCount = jobs.filter((j) => j.status === 'queued' || j.status === 'running').length

  const value = { jobs, activeCount, startWatching }

  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>
}

export function useJobs() {
  const ctx = useContext(JobsContext)
  if (!ctx) throw new Error('useJobs must be used within JobsProvider')
  return ctx
}
