import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, qs } from '../api'
import type { EventItem, NotificationItem, Paged, Settings } from '../types'
import { EVENT_LABELS, REASON_LABELS, dateTime, money, relTime } from '../format'
import { Badge, Empty, Pagination, ProductImage, Spinner, Toggle } from '../components/ui'
import { toast } from '../components/Toaster'

function Events() {
  const [sp, setSp] = useSearchParams()
  const type = sp.get('type') ?? ''
  const alerted = sp.get('alerted') === '1'
  const page = Number(sp.get('page') ?? 1)
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) (v ? next.set(k, v) : next.delete(k))
    if (!('page' in patch)) next.delete('page')
    setSp(next, { replace: true })
  }
  const { data, isLoading } = useQuery({
    queryKey: ['events', type, alerted, page],
    queryFn: () => api.get<Paged<EventItem>>(`/events${qs({ type, alerted, page, page_size: 50 })}`),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  })
  return (
    <>
      <div className="filter-row">
        <div className="chips">
          <button className={`chip ${!type ? 'active' : ''}`} onClick={() => set({ type: null })}>All</button>
          {Object.entries(EVENT_LABELS).map(([k, v]) => (
            <button key={k} className={`chip ${type === k ? 'active' : ''}`} onClick={() => set({ type: type === k ? null : k })}>{v.icon} {v.label}</button>
          ))}
        </div>
        <Toggle checked={alerted} onChange={(v) => set({ alerted: v ? '1' : null })} label="Only what alerted me" />
      </div>
      {isLoading ? <Spinner /> : !data?.items.length ? (
        <Empty>No changes recorded yet. Changes appear after each store's first (silent) baseline check.</Empty>
      ) : (
        <>
          <ul className="event-list card">
            {data.items.map((e) => (
              <li key={e.id}>
                <ProductImage src={e.product_image ?? e.image} alt="" className="event-img" />
                <div className="event-main">
                  <div>
                    <span className="event-type">{EVENT_LABELS[e.type]?.icon} {EVENT_LABELS[e.type]?.label ?? e.type}</span>
                    {' · '}<span className="strong">{e.store_name}</span>
                    {e.alert_reason && <Badge tone="warn">{REASON_LABELS[e.alert_reason] ?? e.alert_reason}</Badge>}
                  </div>
                  <div>
                    {e.product_id
                      ? <Link to={`/product/${encodeURIComponent(e.product_id)}`}>{e.product_title ?? e.title}</Link>
                      : <span>{e.title}</span>}
                    {e.url && <a className="muted small" href={e.url} target="_blank" rel="noreferrer"> ↗</a>}
                  </div>
                </div>
                <div className="event-price">
                  <div className="strong">{money(e.price)}</div>
                  {e.old_price !== null && e.old_price !== e.price && <div className="muted small"><s>{money(e.old_price)}</s></div>}
                </div>
                <div className="muted small nowrap" title={dateTime(e.ts)}>{relTime(e.ts)}</div>
              </li>
            ))}
          </ul>
          <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={(p) => set({ page: String(p) })} />
        </>
      )}
    </>
  )
}

function Notifications() {
  const qc = useQueryClient()
  const [sp, setSp] = useSearchParams()
  const status = sp.get('status') ?? ''
  const page = Number(sp.get('page') ?? 1)
  const { data, isLoading } = useQuery({
    queryKey: ['notifications', status, page],
    queryFn: () => api.get<Paged<NotificationItem>>(`/notifications${qs({ status, page, page_size: 50 })}`),
    refetchInterval: 5000,
    placeholderData: keepPreviousData,
  })
  const { data: cfg } = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const who = (n: NotificationItem) =>
    n.target ? (cfg?.channels.telegram.recipients.find((r) => r.id === n.target)?.name ?? n.target) : null
  const retry = useMutation({
    mutationFn: (id: number) => api.post(`/notifications/${id}/retry`),
    onSuccess: () => { toast('Queued for retry'); qc.invalidateQueries({ queryKey: ['notifications'] }) },
  })
  const retryAll = useMutation({
    mutationFn: () => api.post<{ count: number }>('/notifications/retry-failed'),
    onSuccess: (d) => { toast(`${d.count} queued for retry`); qc.invalidateQueries({ queryKey: ['notifications'] }) },
  })
  return (
    <>
      <div className="filter-row">
        <div className="segmented">
          {[['', 'All'], ['sent', 'Sent'], ['pending', 'Pending'], ['failed', 'Failed']].map(([v, label]) => (
            <button key={v} className={status === v ? 'active' : ''} onClick={() => setSp({ tab: 'notifications', ...(v ? { status: v } : {}) }, { replace: true })}>{label}</button>
          ))}
        </div>
        <button className="btn btn-sm" onClick={() => retryAll.mutate()}>Retry all failed</button>
        <span className="muted small">Failed sends are retried automatically (15s → 30min backoff).</span>
      </div>
      {isLoading ? <Spinner /> : !data?.items.length ? <Empty>No notifications sent yet.</Empty> : (
        <>
          <div className="table-wrap card">
            <table className="table">
              <thead><tr><th>When</th><th>Channel</th><th>Status</th><th>Message</th><th /></tr></thead>
              <tbody>
                {data.items.map((n) => (
                  <tr key={n.id}>
                    <td className="small nowrap" title={dateTime(n.created_at)}>{relTime(n.created_at)}</td>
                    <td className="nowrap"><Badge tone="muted">{n.channel}</Badge>{who(n) && <span className="small"> → {who(n)}</span>}</td>
                    <td>
                      <Badge tone={n.status === 'sent' ? 'good' : n.status === 'failed' ? 'bad' : 'info'}>{n.status}</Badge>
                      {n.attempts > 1 && <span className="muted small"> {n.attempts} tries</span>}
                    </td>
                    <td className="small">
                      {n.summary}
                      {n.last_error && <div className="text-bad small">{n.last_error}</div>}
                    </td>
                    <td>{n.status !== 'sent' && <button className="btn btn-sm" onClick={() => retry.mutate(n.id)}>Retry</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} total={data.total} pageSize={data.page_size} onPage={(p) => setSp({ tab: 'notifications', ...(status ? { status } : {}), page: String(p) })} />
        </>
      )}
    </>
  )
}

export default function ActivityPage() {
  const [sp, setSp] = useSearchParams()
  const tab = sp.get('tab') ?? 'events'
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Activity</h1>
          <p className="muted">Every stock and price change detected, and every alert sent to your devices.</p>
        </div>
      </header>
      <div className="tabs">
        <button className={tab === 'events' ? 'active' : ''} onClick={() => setSp({}, { replace: true })}>Changes</button>
        <button className={tab === 'notifications' ? 'active' : ''} onClick={() => setSp({ tab: 'notifications' }, { replace: true })}>Alerts sent</button>
      </div>
      {tab === 'notifications' ? <Notifications /> : <Events />}
    </div>
  )
}
