import { useEffect, type ReactNode } from 'react'
import type { Product } from '../types'
import { useToggleFavorite } from '../hooks'
import { tcgColor } from '../format'

export function Toggle({
  checked, onChange, label, disabled, title,
}: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean; title?: string }) {
  return (
    <label className={`toggle ${disabled ? 'is-disabled' : ''}`} title={title}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-track" aria-hidden><span className="toggle-thumb" /></span>
      {label !== undefined && <span className="toggle-label">{label}</span>}
    </label>
  )
}

export function StatusDot({ status, enabled = true }: { status: string; enabled?: boolean }) {
  const s = enabled ? status : 'disabled'
  const label: Record<string, string> = {
    ok: 'OK', error: 'Error', running: 'Checking…', pending: 'Waiting for first check', disabled: 'Disabled',
  }
  return <span className={`dot dot-${s}`} title={label[s] ?? s} aria-label={label[s] ?? s} />
}

export function Badge({ children, tone = 'default', title }: { children: ReactNode; tone?: string; title?: string }) {
  return <span className={`badge badge-${tone}`} title={title}>{children}</span>
}

export function TcgBadge({ tcg, label }: { tcg: string | null; label?: string }) {
  if (!tcg) return null
  return (
    <span className="badge badge-tcg" style={{ ['--tcg' as string]: tcgColor(tcg) }}>
      {label ?? tcg}
    </span>
  )
}

export function Modal({
  open, onClose, title, children, footer, wide,
}: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Pagination({
  page, total, pageSize, onPage,
}: { page: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="pagination">
      <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>← Prev</button>
      <span className="muted">Page {page} of {pages}</span>
      <button className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next →</button>
    </div>
  )
}

export function FavButton({ product, size = 'md' }: { product: Pick<Product, 'id' | 'favorite'>; size?: 'md' | 'lg' }) {
  const toggle = useToggleFavorite()
  return (
    <button
      className={`fav-btn fav-${size} ${product.favorite ? 'is-fav' : ''}`}
      title={product.favorite ? 'Remove from favourites' : 'Add to favourites (get alerts)'}
      aria-pressed={product.favorite}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        toggle.mutate(product)
      }}
    >
      {product.favorite ? '★' : '☆'}
    </button>
  )
}

export function ProductImage({ src, alt, className = '' }: { src: string | null; alt: string; className?: string }) {
  if (!src) return <div className={`img-ph ${className}`} aria-hidden>🃏</div>
  return <img className={className} src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" />
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Spinner() {
  return <div className="spinner" aria-label="Loading" />
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}
