import { useEffect, useState } from 'react'
import { CalendarClock } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, EmptyState, HelpBox } from '../components/Ui.jsx'

export default function Schedules() {
  const { projectId, channels } = useAppState()
  const toast = useToast()
  const [scheds, setScheds] = useState([])
  const [channel, setChannel] = useState('')
  const [interval, setInterval_] = useState('86400')

  async function reload() {
    const s = await api(`/api/projects/${projectId}/schedules`)
    setScheds(s)
  }

  useEffect(() => {
    if (!projectId) return
    if (channels && !channel) setChannel(channels.channels[0])
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, channels])

  async function onSubmit(e) {
    e.preventDefault()
    await api(`/api/projects/${projectId}/schedules`, {
      method: 'POST', body: { channel, interval_seconds: parseInt(interval, 10), params: {} },
    })
    toast('Schedule created')
    await reload()
  }

  async function togglePause(s) {
    await api(`/api/schedules/${s.id}/pause`, { method: 'POST', body: { paused: !s.paused } })
    await reload()
  }

  async function del(id) {
    await api(`/api/schedules/${id}`, { method: 'DELETE' })
    await reload()
  }

  if (!channels) return null

  return (
    <>
      <HelpBox view="schedules" />
      <Card title="Schedules">
        <form className="row" onSubmit={onSubmit}>
          <label>Channel
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              {channels.channels.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Interval
            <select value={interval} onChange={(e) => setInterval_(e.target.value)}>
              <option value="3600">Hourly</option>
              <option value="86400">Daily</option>
              <option value="604800">Weekly</option>
            </select>
          </label>
          <button type="submit">Add schedule</button>
        </form>
      </Card>
      <Card><h3><CalendarClock size={16} className="title-icon" /> Active schedules</h3>
        {scheds.length === 0 ? (
          <EmptyState icon={CalendarClock} title="No schedules yet" hint="Add one above to automate recurring collection." />
        ) : (
        <div className="table-wrap"><table>
          <thead><tr><th>#</th><th>Channel</th><th>Every</th><th>Next run</th><th>Paused</th><th></th></tr></thead>
          <tbody>
            {scheds.map((s) => (
              <tr key={s.id}>
                <td>{s.id}</td><td>{s.channel}</td><td>{s.interval_seconds}s</td>
                <td>{(s.next_run || '').slice(0, 19)}</td><td>{s.paused ? 'yes' : 'no'}</td>
                <td>
                  <button className="ghost" onClick={() => togglePause(s)}>{s.paused ? 'Resume' : 'Pause'}</button>{' '}
                  <button className="ghost" onClick={() => del(s.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
        )}
      </Card>
    </>
  )
}
