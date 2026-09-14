import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null) // { msg, isErr }
  const timerRef = useRef(null)

  const showToast = useCallback((msg, isErr = false) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setToast({ msg, isErr })
    timerRef.current = setTimeout(() => setToast(null), 3200)
  }, [])

  return (
    <ToastContext.Provider value={showToast}>
      {children}
      <div className={`toast${toast ? '' : ' hidden'}${toast?.isErr ? ' err' : ''}`}>
        {toast && (toast.isErr ? <XCircle size={16} /> : <CheckCircle2 size={16} />)}
        {toast?.msg}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
