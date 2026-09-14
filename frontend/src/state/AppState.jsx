import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../api.js'

const AppStateContext = createContext(null)

// Which channels are ready with no extra setup vs. what each one needs -- ported
// verbatim from the old static/app.js CHREQ table.
export const CHREQ = {
  news: { ready: true, needs: '' },
  gdelt: { ready: true, needs: '' },
  reddit: { ready: true, needs: '' },
  trends: { ready: false, needs: 'pytrends (bundled in Docker)' },
  forums: { ready: false, needs: 'your forum URLs (Source plan)' },
  quora: { ready: false, needs: 'your Quora URLs (Source plan)' },
  ecommerce: { ready: false, needs: 'your product URLs + Playwright (Docker)' },
  youtube: { ready: false, needs: 'YOUTUBE_API_KEY' },
  google_business: { ready: false, needs: 'GOOGLE_PLACES_API_KEY' },
  image_analysis: { ready: false, needs: 'run E-commerce first + ANTHROPIC_API_KEY' },
}

export function AppStateProvider({ children }) {
  const [booted, setBooted] = useState(false)
  const [needsLogin, setNeedsLogin] = useState(false)
  const [mode, setMode] = useState('solo')
  const [user, setUser] = useState(null)
  const [version, setVersion] = useState(null)
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState(null)
  const [project, setProject] = useState(null)
  const [channels, setChannels] = useState(null)
  const [health, setHealth] = useState(null)

  const loadProject = useCallback(async (pid) => {
    const p = await api(`/api/projects/${pid}`)
    setProject(p)
    setProjectId(pid)
  }, [])

  const loadProjects = useCallback(async () => {
    const list = await api('/api/projects')
    setProjects(list)
    if (list.length === 0) {
      setProject(null)
      setProjectId(null)
      return
    }
    const stillExists = projectId && list.some((p) => p.id === projectId)
    const pid = stillExists ? projectId : list[0].id
    await loadProject(pid)
  }, [projectId, loadProject])

  const boot = useCallback(async () => {
    try {
      const v = await api('/api/version')
      setVersion(v)
      const m = await api('/api/mode')
      setMode(m.mode)
      setUser(m.user)
      if (m.team && !m.authenticated) {
        setNeedsLogin(true)
        setBooted(true)
        return
      }
      const ch = await api('/api/channels')
      setChannels(ch)
      try { setHealth(await api('/api/health')) } catch { /* optional, non-fatal */ }
      await loadProjects()
    } finally {
      setBooted(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    boot()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const login = useCallback(async (username, password) => {
    await api('/api/auth/login', { method: 'POST', body: { username, password } })
    setNeedsLogin(false)
    const ch = await api('/api/channels')
    setChannels(ch)
    await loadProjects()
  }, [loadProjects])

  const logout = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' })
    window.location.reload()
  }, [])

  const value = {
    booted, needsLogin, mode, user, version,
    projects, projectId, project, channels, health,
    loadProjects, selectProject: loadProject, login, logout,
  }

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState() {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
