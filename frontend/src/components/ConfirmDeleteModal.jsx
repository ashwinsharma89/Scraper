import { useState } from 'react'
import Modal from './Modal.jsx'

// HANDOFF §7 item 4: "Delete-study button in the UI (backend DELETE
// /api/projects/{id}?confirm=DELETE already exists)." Typed-name confirmation
// (rather than a plain Yes/No) matches the destructiveness of a permanent purge —
// this deletes the project AND every item/run/audit row under it, with no undo.
export default function ConfirmDeleteModal({ projectName, onClose, onConfirm }) {
  const [typed, setTyped] = useState('')
  const [deleting, setDeleting] = useState(false)
  const canDelete = typed.trim() === projectName

  async function handleConfirm() {
    setDeleting(true)
    try {
      await onConfirm()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Modal title="Delete study" onClose={onClose} className="wizard-card">
      <p>This permanently deletes <b>{projectName}</b> — every collected item, run,
        job, and audit row under it. <b>This cannot be undone.</b></p>
      <label>Type the study name to confirm
        <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={projectName} autoFocus />
      </label>
      <div className="actions">
        <button type="button" className="danger" disabled={!canDelete || deleting} onClick={handleConfirm}>
          {deleting ? 'Deleting…' : 'Permanently delete'}
        </button>
        <button type="button" className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}
