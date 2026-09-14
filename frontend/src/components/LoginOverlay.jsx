import { useState } from 'react'
import { useAppState } from '../state/AppState.jsx'

export default function LoginOverlay() {
  const { login } = useAppState()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function onSubmit(e) {
    e.preventDefault()
    try {
      await login(username, password)
    } catch {
      setError('Invalid credentials')
    }
  }

  return (
    <div className="overlay">
      <form className="card login-card" onSubmit={onSubmit}>
        <h2>MarketLens</h2>
        <p className="muted">Team mode is active. Enter your credentials.</p>
        <label>Username
          <input value={username} onChange={(e) => setUsername(e.target.value)}
            autoComplete="username" required />
        </label>
        <label>Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password" required />
        </label>
        <button type="submit">Sign in</button>
        <p className="error">{error}</p>
      </form>
    </div>
  )
}
