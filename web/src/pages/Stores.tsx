import { Fragment, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { Store, StoreTestResult } from '../types'
import { useMeta, useSummary } from '../hooks'
import { dateTime, relTime } from '../format'
import { Badge, Empty, Field, Modal, Spinner, StatusDot, Toggle } from '../components/ui'
import { toast } from '../components/Toaster'

const PLATFORM_HELP: Record<string, string> = {
  shopify: 'Shopify public API. URL = store root, or /collections/… pages to narrow a generalist shop.',
  woocommerce: 'WooCommerce Store API. URL = store root; add ?category=ID (or &category_operator=not_in) to narrow.',
  woocommerce_html: 'WooCommerce shop pages (for shops with the Store API disabled). URL = /shop/ or a category page.',
  wix: 'Wix Stores (reads the store catalogue API). URL = site root.',
  conbini: 'Conbini listing pages (products embedded as JSON).',
  prestashop: 'PrestaShop category pages (paged with ?page=N). URL = category page(s).',
  jumpseller: 'Jumpseller category/listing page(s), parsed from HTML. Options can override selectors.',
  shopkit: 'Shopkit /catalog, /category/… or /brand/… page(s), parsed from HTML.',
  html: 'Generic HTML listing page. Needs selector options (tile, name, price, …).',
  toysrus: 'Toys R Us search API — URL = a toysrus.pt search URL (?query=…).',
  continente: 'Continente search page.',
  elcorteingles: 'El Corte Inglés (currently blocked by the site).',
}

function StoreForm({ store, onClose }: { store: Store | null; onClose: () => void }) {
  const qc = useQueryClient()
  const { data: meta } = useMeta()
  const isNew = !store
  const [f, setF] = useState({
    name: store?.name ?? '',
    platform: store?.platform ?? 'shopify',
    url: store?.url ?? '',
    urls: store && !(store.urls.length === 1 && store.urls[0] === store.url) ? store.urls.join('\n') : '',
    options: store && Object.keys(store.options).length ? JSON.stringify(store.options, null, 2) : '',
    interval_min: store?.interval_min?.toString() ?? '',
    interval_max: store?.interval_max?.toString() ?? '',
    notes: store?.notes ?? '',
    enabled: store?.enabled ?? true,
  })
  const [test, setTest] = useState<StoreTestResult | null>(null)

  const body = () => {
    let options: Record<string, unknown> | null = null
    if (f.options.trim()) options = JSON.parse(f.options)
    return {
      name: f.name.trim(), platform: f.platform, url: f.url.trim(),
      urls: f.urls.split('\n').map((u) => u.trim()).filter(Boolean),
      options, enabled: f.enabled, notes: f.notes || null,
      interval_min: f.interval_min ? Number(f.interval_min) : null,
      interval_max: f.interval_max ? Number(f.interval_max) : null,
    }
  }
  const runTest = useMutation({
    mutationFn: () => {
      const b = body()
      return isNew
        ? api.post<StoreTestResult>('/stores/test', { platform: b.platform, url: b.url, urls: b.urls.length ? b.urls : null, options: b.options })
        : api.post<StoreTestResult>(`/stores/${store!.id}/test`, { platform: b.platform, url: b.url, urls: b.urls, options: b.options ?? {} })
    },
    onSuccess: setTest,
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const save = useMutation({
    mutationFn: () => (isNew ? api.post('/stores', body()) : api.patch(`/stores/${store!.id}`, body())),
    onSuccess: () => { toast(isNew ? 'Store added — first check starts now (silent baseline)' : 'Store saved'); qc.invalidateQueries({ queryKey: ['stores'] }); onClose() },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const del = useMutation({
    mutationFn: () => api.del(`/stores/${store!.id}`),
    onSuccess: () => { toast('Store deleted'); qc.invalidateQueries({ queryKey: ['stores'] }); onClose() },
  })
  const optionsValid = (() => { try { if (f.options.trim()) JSON.parse(f.options); return true } catch { return false } })()

  return (
    <Modal open wide onClose={onClose} title={isNew ? 'Add store' : `Edit ${store!.name}`} footer={
      <>
        {!isNew && <button className="btn btn-danger" onClick={() => { if (window.confirm(`Delete ${store!.name} and all its history?`)) del.mutate() }}>Delete</button>}
        <span className="spacer" />
        <button className="btn" disabled={!f.url || !optionsValid || runTest.isPending} onClick={() => runTest.mutate()}>
          {runTest.isPending ? 'Testing…' : 'Test scrape'}
        </button>
        <button className="btn btn-primary" disabled={!f.name || !f.url || !optionsValid || save.isPending} onClick={() => save.mutate()}>Save</button>
      </>
    }>
      <div className="form-grid">
        <Field label="Name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Platform" hint={PLATFORM_HELP[f.platform]}>
          <select className="input" value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value })}>
            {meta?.platforms.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Store URL"><input className="input" value={f.url} placeholder="https://store.pt" onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>
      <Field label="Pages to scrape (optional, one per line)" hint="Leave empty to scrape the store URL. Use category/collection pages to limit big generalist shops to TCG.">
        <textarea className="input mono" rows={3} value={f.urls} onChange={(e) => setF({ ...f, urls: e.target.value })} />
      </Field>
      <Field label="Scraper options (JSON, optional)" hint={optionsValid ? 'Any platform: "impersonate": true (browser-like requests for sites that block bots), "require_tcg": true (generalist shops). HTML platforms: tile, name, price, old_price, oos_selector, oos_class, pagination ("query"|"next"|"path")…' : <span className="text-bad">Invalid JSON</span>}>
        <textarea className="input mono" rows={3} value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })} placeholder='{"tile": "div.product"}' />
      </Field>
      <div className="form-grid three">
        <Field label="Min interval (s)" hint="Blank = global"><input className="input" inputMode="numeric" value={f.interval_min} onChange={(e) => setF({ ...f, interval_min: e.target.value })} /></Field>
        <Field label="Max interval (s)"><input className="input" inputMode="numeric" value={f.interval_max} onChange={(e) => setF({ ...f, interval_max: e.target.value })} /></Field>
        <div className="pad-top"><Toggle checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} label="Enabled" /></div>
      </div>
      <Field label="Notes"><input className="input" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      {test && (
        <div className={`test-result ${test.ok ? 'ok' : 'bad'}`}>
          {test.ok ? (
            <>
              <p><b>{test.scraped}</b> products read in {test.seconds}s → <b>{test.kept}</b> TCG products tracked ({test.in_stock} in stock).</p>
              <p className="muted small">{Object.entries(test.kinds ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
              <ul className="test-sample">
                {test.sample?.map((s, i) => (
                  <li key={i}><span className={s.in_stock ? 'text-good' : 'text-bad'}>{s.in_stock ? '●' : '○'}</span> {s.price ?? '?'}€ — {s.name} <span className="muted small">[{s.type ?? s.kind}{s.set_id ? ` · ${s.set_id}` : ''}]</span></li>
                ))}
              </ul>
            </>
          ) : <p className="text-bad">{test.error}</p>}
        </div>
      )}
    </Modal>
  )
}

export default function StoresPage() {
  const qc = useQueryClient()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<Store | null | undefined>(undefined)
  const [expanded, setExpanded] = useState<string | null>(null)
  const status = sp.get('status') ?? ''
  const { data: summary } = useSummary()
  const { data: stores, isLoading } = useQuery({
    queryKey: ['stores'],
    queryFn: () => api.get<Store[]>('/stores'),
    refetchInterval: 4000,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['stores'] })
  const toggle = useMutation({
    mutationFn: (s: Store) => api.patch(`/stores/${s.id}`, { enabled: !s.enabled }),
    onSuccess: (_d, s) => { toast(`${s.name} ${s.enabled ? 'disabled' : 'enabled'}`); refresh() },
  })
  const check = useMutation({
    mutationFn: (s: Store) => api.post(`/stores/${s.id}/check`),
    onSuccess: (_d, s) => { toast(`Checking ${s.name}…`); refresh() },
  })
  const checkAll = useMutation({
    mutationFn: () => api.post('/stores/check-all'),
    onSuccess: () => { toast('All enabled stores queued'); refresh() },
  })
  const pause = useMutation({
    mutationFn: (paused: boolean) => api.put('/settings', { scheduler: { paused } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['summary'] }),
  })

  const filtered = useMemo(() => (stores ?? []).filter((s) => {
    if (q && !`${s.name} ${s.url} ${s.platform}`.toLowerCase().includes(q.toLowerCase())) return false
    if (status === 'disabled') return !s.enabled
    if (status && (!s.enabled || s.status !== status)) return false
    return true
  }), [stores, q, status])

  const counts = useMemo(() => {
    const c = { ok: 0, error: 0, running: 0, pending: 0, disabled: 0 }
    for (const s of stores ?? []) {
      if (!s.enabled) c.disabled++
      else c[s.status]++
    }
    return c
  }, [stores])

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Stores</h1>
          <p className="muted">Each enabled store is checked every few minutes, at a random interval. A store's first check is a silent baseline: it records what's there without sending alerts.</p>
        </div>
        <div className="btn-group">
          <button className="btn" onClick={() => pause.mutate(!summary?.paused)}>{summary?.paused ? '▶ Resume' : '⏸ Pause'} monitoring</button>
          <button className="btn" onClick={() => checkAll.mutate()}>↻ Check all now</button>
          <button className="btn btn-primary" onClick={() => setEditing(null)}>+ Add store</button>
        </div>
      </header>

      <div className="filter-row">
        <input className="input search" placeholder="Filter stores…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="segmented">
          {([['', `All ${stores?.length ?? ''}`], ['ok', `OK ${counts.ok}`], ['error', `Failing ${counts.error}`], ['running', `Running ${counts.running}`], ['pending', `Waiting ${counts.pending}`], ['disabled', `Off ${counts.disabled}`]] as const).map(([v, label]) => (
            <button key={v} className={status === v ? 'active' : ''} onClick={() => setSp(v ? { status: v } : {}, { replace: true })}>{label}</button>
          ))}
        </div>
      </div>

      {isLoading ? <Spinner /> : !filtered.length ? <Empty>No stores match.</Empty> : (
        <div className="table-wrap card">
          <table className="table stores-table">
            <thead>
              <tr>
                <th /><th>Store</th><th>On</th><th className="num">Tracked</th><th className="hide-sm">Last check</th><th className="hide-sm">Next</th><th className="hide-md">Result</th><th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <Fragment key={s.id}>
                  <tr className={!s.enabled ? 'row-dim' : ''}>
                    <td><StatusDot status={s.status} enabled={s.enabled} /></td>
                    <td>
                      <div className="strong"><Link to={`/?store=${encodeURIComponent(s.id)}`}>{s.name}</Link></div>
                      <div className="muted small">
                        <Badge tone="muted">{s.platform}</Badge>{' '}
                        <a href={s.url} target="_blank" rel="noreferrer">{s.url.replace(/^https?:\/\/(www\.)?/, '')} ↗</a>
                        {s.urls.length > 1 && <> · {s.urls.length} pages</>}
                        {!s.baseline_done && s.enabled && <> · <span className="text-info">baseline pending</span></>}
                      </div>
                    </td>
                    <td><Toggle checked={s.enabled} onChange={() => toggle.mutate(s)} title={s.enabled ? 'Disable' : 'Enable'} /></td>
                    <td className="num nowrap">
                      <span className="text-good" title="in stock">{s.in_stock_count}</span>
                      <span className="muted"> / {s.listing_count}</span>
                      <div className="muted small" title="linked to a catalogue product">{s.matched_count} matched</div>
                    </td>
                    <td className="hide-sm small nowrap" title={dateTime(s.last_check_at)}>
                      {relTime(s.last_check_at)}
                      {s.last_duration_ms !== null && <div className="muted">{(s.last_duration_ms / 1000).toFixed(1)}s</div>}
                    </td>
                    <td className="hide-sm small muted nowrap">{s.enabled ? (s.status === 'running' ? 'now' : relTime(s.next_check_at)) : '—'}</td>
                    <td className="hide-md small result-cell">
                      {s.status === 'error' && s.enabled ? (
                        <button className="btn-link text-bad" onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
                          ✕ {s.consecutive_failures}× failed{expanded === s.id ? ' ▾' : ' ▸'}
                        </button>
                      ) : s.status === 'ok' && !s.last_raw_count ? (
                        <span className="text-bad" title="The page loaded but no products were found — the URL or selectors probably need fixing">⚠ 0 products read</span>
                      ) : s.status === 'ok' ? (
                        <span className="muted">read {s.last_raw_count} products</span>
                      ) : s.notes ? <span className="muted">{s.notes}</span> : null}
                    </td>
                    <td className="nowrap">
                      <button className="btn btn-sm" disabled={!s.enabled || s.status === 'running'} onClick={() => check.mutate(s)}>Check</button>
                      <button className="btn-icon" title="Edit" onClick={() => setEditing(s)}>✎</button>
                    </td>
                  </tr>
                  {(expanded === s.id || (s.status === 'error' && s.enabled && status === 'error')) && s.last_error && (
                    <tr className="err-row">
                      <td />
                      <td colSpan={7}>
                        <code className="err">{s.last_error}</code>
                        <div className="muted small">Last success {relTime(s.last_success_at)} · retrying with backoff</div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing !== undefined && <StoreForm store={editing} onClose={() => setEditing(undefined)} />}
    </div>
  )
}
