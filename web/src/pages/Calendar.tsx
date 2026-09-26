import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { SetInfo } from '../types'
import { useMeta } from '../hooks'
import { daysUntil, money, releaseDate, tcgColor } from '../format'
import { Badge, Empty, Field, Modal, Spinner, TcgBadge, Toggle } from '../components/ui'
import { toast } from '../components/Toaster'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function ymd(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function SetForm({ set, onClose }: { set: Partial<SetInfo> | null; onClose: () => void }) {
  const qc = useQueryClient()
  const { data: meta } = useMeta()
  const isNew = !set?.id
  const [f, setF] = useState({
    tcg: set?.tcg ?? 'pokemon',
    code: set?.code ?? '',
    name: set?.name ?? '',
    aliases: (set?.aliases ?? []).join(', '),
    release_date: set?.release_date ?? '',
    date_confirmed: set?.date_confirmed ?? true,
    focus: set?.focus ?? true,
    notes: set?.notes ?? '',
  })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f,
        code: f.code.trim() || null,
        aliases: f.aliases.split(',').map((a) => a.trim()).filter(Boolean),
        release_date: f.release_date || null,
        notes: f.notes || null,
      }
      return isNew ? api.post('/sets', body) : api.patch(`/sets/${encodeURIComponent(set!.id!)}`, body)
    },
    onSuccess: () => {
      toast(isNew ? 'Release added — matching store listings in the background' : 'Release saved')
      qc.invalidateQueries({ queryKey: ['sets'] })
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const del = useMutation({
    mutationFn: () => api.del(`/sets/${encodeURIComponent(set!.id!)}`),
    onSuccess: () => { toast('Release deleted'); qc.invalidateQueries({ queryKey: ['sets'] }); onClose() },
  })
  return (
    <Modal open onClose={onClose} title={isNew ? 'Add release' : `Edit ${set?.name}`} footer={
      <>
        {!isNew && <button className="btn btn-danger" onClick={() => { if (window.confirm('Delete this set? Its products lose their set.')) del.mutate() }}>Delete</button>}
        <span className="spacer" />
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!f.name.trim() || save.isPending} onClick={() => save.mutate()}>Save</button>
      </>
    }>
      <div className="form-grid">
        <Field label="Game">
          <select className="input" value={f.tcg} disabled={!isNew} onChange={(e) => setF({ ...f, tcg: e.target.value })}>
            {meta && Object.entries(meta.tcgs).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Code" hint="As printed / used by stores, e.g. ME06, OP-15">
          <input className="input" value={f.code} disabled={!isNew} onChange={(e) => setF({ ...f, code: e.target.value })} />
        </Field>
      </div>
      <Field label="Name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Delta Reign" /></Field>
      <Field label="Other names stores use" hint="Comma separated. Used to recognise this set in product names.">
        <input className="input" value={f.aliases} onChange={(e) => setF({ ...f, aliases: e.target.value })} />
      </Field>
      <div className="form-grid">
        <Field label="Release date"><input className="input" type="date" value={f.release_date} onChange={(e) => setF({ ...f, release_date: e.target.value })} /></Field>
        <div className="stack-sm pad-top">
          <Toggle checked={f.date_confirmed} onChange={(v) => setF({ ...f, date_confirmed: v })} label="Date confirmed" />
          <Toggle checked={f.focus} onChange={(v) => setF({ ...f, focus: v })} label="🔥 Focus (alert on everything)" />
        </div>
      </div>
      <Field label="Notes"><textarea className="input" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
    </Modal>
  )
}

function SetRow({ s, onEdit }: { s: SetInfo; onEdit: () => void }) {
  const qc = useQueryClient()
  const { data: meta } = useMeta()
  const focus = useMutation({
    mutationFn: (v: boolean) => api.patch(`/sets/${encodeURIComponent(s.id)}`, { focus: v }),
    onSuccess: (_d, v) => {
      toast(v ? `🔥 Focus on ${s.name}: you'll be alerted about every listing, restock and pre-order` : `${s.name} is no longer a focus`)
      qc.invalidateQueries({ queryKey: ['sets'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
  })
  const days = daysUntil(s.release_date)
  return (
    <div className={`set-row card ${s.focus ? 'is-focus' : ''}`}>
      <div className="set-date">
        <div className="strong">{releaseDate(s.release_date)}</div>
        <div className="muted small">
          {days === null ? 'date unknown' : days > 0 ? `in ${days} day${days === 1 ? '' : 's'}` : days === 0 ? 'today!' : `${-days} days ago`}
          {s.release_date && !s.date_confirmed && ' · unconfirmed'}
        </div>
      </div>
      <div className="set-main">
        <div className="product-meta">
          <TcgBadge tcg={s.tcg} label={meta?.tcgs[s.tcg] ?? s.tcg} />
          {s.code && <Badge>{s.code}</Badge>}
          {s.auto_created && <Badge tone="warn" title="Created automatically from a code seen in a store — give it a name">new code spotted</Badge>}
        </div>
        <Link to={`/?set=${encodeURIComponent(s.id)}`} className="strong set-name">{s.name}</Link>
        <div className="muted small">
          {s.product_count} products · {s.listing_count} listings · <span className={s.in_stock_count ? 'text-good' : ''}>{s.in_stock_count} in stock</span>
          {s.preorder_count > 0 && <> · <span className="text-info">{s.preorder_count} pre-orders</span></>}
          {s.min_best_price !== null && <> · from {money(s.min_best_price)}</>}
        </div>
      </div>
      <div className="set-actions">
        <Toggle checked={s.focus} onChange={(v) => focus.mutate(v)} label="🔥 Focus" title="Alert on every new listing / restock of this set" />
        <button className="btn btn-sm" onClick={onEdit}>Edit</button>
      </div>
    </div>
  )
}

export default function CalendarPage() {
  const { data: meta } = useMeta()
  const [tcg, setTcg] = useState('')
  const [month, setMonth] = useState(() => { const d = new Date(); d.setDate(1); return d })
  const [editing, setEditing] = useState<Partial<SetInfo> | null | undefined>(undefined)
  const [showOld, setShowOld] = useState(false)
  const [showUndated, setShowUndated] = useState(false)
  const { data: sets, isLoading } = useQuery({
    queryKey: ['sets', tcg],
    queryFn: () => api.get<SetInfo[]>(`/sets${tcg ? `?tcg=${tcg}` : ''}`),
  })

  const today = ymd(new Date())
  const { upcoming, recent, undated, focusCount } = useMemo(() => {
    const all = sets ?? []
    const up = all.filter((s) => s.release_date && s.release_date >= today).sort((a, b) => a.release_date!.localeCompare(b.release_date!))
    const past = all.filter((s) => s.release_date && s.release_date < today)
    const und = all.filter((s) => !s.release_date).sort((a, b) => Number(b.focus) - Number(a.focus) || Number(b.auto_created) - Number(a.auto_created) || b.listing_count - a.listing_count)
    return { upcoming: up, recent: past, undated: und, focusCount: all.filter((s) => s.focus).length }
  }, [sets, today])

  const byDay = useMemo(() => {
    const m: Record<string, SetInfo[]> = {}
    for (const s of sets ?? []) if (s.release_date) (m[s.release_date] ??= []).push(s)
    return m
  }, [sets])

  const cells = useMemo(() => {
    const first = new Date(month)
    const offset = (first.getDay() + 6) % 7
    const start = new Date(first)
    start.setDate(1 - offset)
    return Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  }, [month])

  const shift = (n: number) => setMonth((m) => { const d = new Date(m); d.setMonth(d.getMonth() + n); return d })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Release calendar</h1>
          <p className="muted">Mark a release as <b>🔥 focus</b> to get alerts for every new listing, pre-order and restock of its products — even ones you haven't favourited. {focusCount > 0 && <>{focusCount} focus release{focusCount === 1 ? '' : 's'} active.</>}</p>
        </div>
        <button className="btn btn-primary" onClick={() => setEditing(null)}>+ Add release</button>
      </header>

      <div className="chips">
        <button className={`chip ${!tcg ? 'active' : ''}`} onClick={() => setTcg('')}>All games</button>
        {meta && ['pokemon', 'onepiece', 'mtg', 'lorcana', 'riftbound', 'dbs'].map((t) => (
          <button key={t} className={`chip ${tcg === t ? 'active' : ''}`} onClick={() => setTcg(tcg === t ? '' : t)}>{meta.tcgs[t]}</button>
        ))}
      </div>

      <section className="card section">
        <div className="section-head">
          <h2>{month.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}</h2>
          <div className="btn-group">
            <button className="btn btn-sm" onClick={() => shift(-1)}>←</button>
            <button className="btn btn-sm" onClick={() => { const d = new Date(); d.setDate(1); setMonth(d) }}>Today</button>
            <button className="btn btn-sm" onClick={() => shift(1)}>→</button>
          </div>
        </div>
        <div className="cal-grid">
          {WEEKDAYS.map((w) => <div key={w} className="cal-head">{w}</div>)}
          {cells.map((d) => {
            const key = ymd(d)
            const items = byDay[key] ?? []
            return (
              <div key={key} className={`cal-cell ${d.getMonth() !== month.getMonth() ? 'other' : ''} ${key === today ? 'today' : ''}`}>
                <div className="cal-day">{d.getDate()}</div>
                {items.map((s) => (
                  <button key={s.id} className={`cal-chip ${s.focus ? 'focus' : ''}`} style={{ ['--tcg' as string]: tcgColor(s.tcg) }}
                    onClick={() => setEditing(s)} title={`${s.code ?? ''} ${s.name}`}>
                    {s.focus && '🔥 '}{s.code ?? s.name}
                    <span className="cal-chip-name"> {s.name}</span>
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      </section>

      {isLoading ? <Spinner /> : (
        <>
          <h2 className="list-title">Upcoming</h2>
          {upcoming.length ? upcoming.map((s) => <SetRow key={s.id} s={s} onEdit={() => setEditing(s)} />)
            : <Empty>No upcoming releases with a date. Add the next sets you care about with <b>+ Add release</b>, or give a date to one from the list below.</Empty>}

          <h2 className="list-title">
            <button className="btn-link" onClick={() => setShowUndated((v) => !v)}>{showUndated ? '▾' : '▸'} No date yet ({undated.length})</button>
          </h2>
          {showUndated && undated.map((s) => <SetRow key={s.id} s={s} onEdit={() => setEditing(s)} />)}

          <h2 className="list-title">
            <button className="btn-link" onClick={() => setShowOld((v) => !v)}>{showOld ? '▾' : '▸'} Released ({recent.length})</button>
          </h2>
          {showOld && recent.map((s) => <SetRow key={s.id} s={s} onEdit={() => setEditing(s)} />)}
        </>
      )}
      {editing !== undefined && <SetForm set={editing} onClose={() => setEditing(undefined)} />}
    </div>
  )
}
