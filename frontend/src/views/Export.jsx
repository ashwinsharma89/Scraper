import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { api } from '../api.js'
import { useAppState } from '../state/AppState.jsx'
import { useToast } from '../components/Toast.jsx'
import { Card, HelpBox, Skeleton } from '../components/Ui.jsx'

export default function Export() {
  const { projectId } = useAppState()
  const toast = useToast()
  const [dash, setDash] = useState(null)
  const [after, setAfter] = useState('')
  const [before, setBefore] = useState('')
  const [exportResult, setExportResult] = useState(null)
  const [building, setBuilding] = useState(false)
  const [targetBrandOnly, setTargetBrandOnly] = useState(false)
  const [report, setReport] = useState('Click "Generate / preview" to assemble the Markdown skeleton, or download it directly.')
  const [archiveResult, setArchiveResult] = useState(null)

  useEffect(() => {
    if (!projectId) return
    api(`/api/projects/${projectId}/dashboard`).then(setDash)
  }, [projectId])

  if (!dash) return <Card><Skeleton rows={3} /></Card>

  const nItems = dash.total_items || 0
  const nAnalyzed = dash.total_analyzed || 0

  async function buildWorkbook() {
    setBuilding(true)
    setExportResult(null)
    try {
      const r = await api(`/api/projects/${projectId}/export`, {
        method: 'POST', body: { published_after: after || null, published_before: before || null,
                                exclude_unrelated: targetBrandOnly },
      })
      setExportResult(r)
    } catch (e) {
      toast(e.message, true)
    } finally {
      setBuilding(false)
    }
  }

  async function genReport() {
    const md = await api(`/api/projects/${projectId}/report/draft`)
    setReport(md)
  }

  async function archiveExport() {
    const r = await api(`/api/projects/${projectId}/archive/export`, { method: 'POST' })
    setArchiveResult(r)
  }

  return (
    <>
      <HelpBox view="export" />
      <Card title="Export & report">
        {nItems === 0 ? (
          <div className="note"><AlertTriangle size={14} /> This study has <b>no collected items</b>. The workbook will be
            almost empty. Do <b>Collect</b> (and then <b>Analyze</b>) first.</div>
        ) : nAnalyzed === 0 ? (
          <div className="note"><AlertTriangle size={14} /> You've collected <b>{nItems}</b> items but <b>analyzed 0</b>.
            The workbook will have raw item tabs + Run Log, but <b>no sentiment / summary / driver
            columns</b> and empty Analysis Summary. Run <b>Analyze all</b> first for a useful report.</div>
        ) : (
          <div className="note note-good">
            <CheckCircle2 size={14} /> Ready: <b>{nItems}</b> items collected, <b>{nAnalyzed}</b> analyzed.
          </div>
        )}
        <div className="row">
          <label>Published after <input type="date" value={after} onChange={(e) => setAfter(e.target.value)} /></label>
          <label>Published before <input type="date" value={before} onChange={(e) => setBefore(e.target.value)} /></label>
          <button onClick={buildWorkbook} disabled={building}>{building ? 'Building…' : 'Build Excel workbook'}</button>
        </div>
        <label style={{ fontWeight: 400, display: 'flex', gap: '.5rem', alignItems: 'center', margin: '.4rem 0' }}>
          <input type="checkbox" checked={targetBrandOnly} style={{ width: 'auto' }}
            onChange={(e) => setTargetBrandOnly(e.target.checked)} />
          <span>Target brand only — drop <code>brand_focus=unrelated</code> rows from the raw
            data tabs (All Items + per-channel), matching what the headline numbers already exclude</span>
        </label>
        {exportResult && (
          <p>Built <b>{exportResult.filename}</b> —{' '}
            <a href={`/api/projects/${projectId}/export/download?path=${encodeURIComponent(exportResult.path)}`}>Download ↓</a></p>
        )}
        <div className="note">The Excel workbook is the client-facing artifact — it stamps the tool version
          and includes Methodology, Confidence, and Representativeness tabs (the honesty contract).
          It also has an <b>"All Items"</b> tab: every collected item across all channels in one sheet
          (id, source, title, text, link, published, run_id + all analysis columns). Off by default,
          "Target brand only" above narrows those raw tabs the same way the headline stats already
          are — nothing is ever silently hidden unless you opt in.</div>
      </Card>

      <Card>
        <div className="card-head"><h3>Report draft (five pillars)</h3>
          <div className="actions">
            <button className="ghost" onClick={genReport}>Generate / preview</button>
            <a className="dl-btn" href={`/api/projects/${projectId}/report/download?fmt=docx`}>Download Word (.docx)</a>
            <a className="dl-btn" href={`/api/projects/${projectId}/report/download?fmt=md`}>Download Markdown (.md)</a>
          </div>
        </div>
        <p className="muted">The report is a separate narrative deliverable — it is <b>not</b> a tab in the
          Excel workbook. Download it here as Word or Markdown, or preview it below.</p>
        <pre className="report">{report}</pre>
      </Card>

      <Card><h3>Portability</h3>
        <button className="ghost" onClick={archiveExport}>Export project archive (.mlz)</button>
        {archiveResult && (
          <p>Archived <b>{archiveResult.filename}</b> —{' '}
            <a href={`/api/projects/${projectId}/archive/download?path=${encodeURIComponent(archiveResult.path)}`}>Download ↓</a></p>
        )}
        <p className="muted">Archive = working-data transfer (config + items + analysis + intel + run log).
          Import via the API on another instance.</p>
      </Card>
    </>
  )
}
