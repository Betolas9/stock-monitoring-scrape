import { useEffect, useState } from 'react'

type Kind = 'ok' | 'error'
interface ToastMsg {
  id: number
  text: string
  kind: Kind
}

const EVENT = 'app-toast'
let counter = 0

export function toast(text: string, kind: Kind = 'ok') {
  window.dispatchEvent(new CustomEvent<ToastMsg>(EVENT, { detail: { id: ++counter, text, kind } }))
}

export function Toaster() {
  const [items, setItems] = useState<ToastMsg[]>([])
  useEffect(() => {
    const onToast = (e: Event) => {
      const msg = (e as CustomEvent<ToastMsg>).detail
      setItems((xs) => [...xs, msg])
      window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== msg.id)), msg.kind === 'error' ? 6000 : 3000)
    }
    window.addEventListener(EVENT, onToast)
    return () => window.removeEventListener(EVENT, onToast)
  }, [])
  return (
    <div className="toaster" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  )
}
