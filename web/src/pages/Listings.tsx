import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, qs } from '../api'
import type { Listing, Paged, Product, Store } from '../types'
import { useMeta } from '../hooks'
import { money } from '../format'
import { Badge, Empty, Field, Modal, Pagination, ProductImage, Spinner } from '../components/ui'
import { toast } from '../components/Toaster'

function LinkDialog({ listing, onClose }: { listing: Listing; onClose: () => void }) {
  const qc = useQueryClient()
  const { data: meta } = useMeta()
  const [q, setQ] = useState(listing.name.replace(/pok[eé]mon|tcg|[-–:|()]/gi, ' ').replace(/\s+/g, ' ').trim().split(' ').slice(0, 4).join(' '))
  const [title, setTitle] = useState(listing.name)
  const { data: results } = useQuery({
    queryKey: ['products', 'link', q],
    queryFn: () => api.get<Paged<Product>>(`/products${qs({ q, page_size: 12 })}`),
    enabled: q.trim().length >= 2,
  })
  const done = (msg: string) => {
    toast(msg)
    qc.invalidateQueries({ queryKey: ['listings'] })
    qc.invalidateQueries({ queryKey: ['products'] })
    qc.invalidateQueries({ queryKey: ['summary'] })
    onClose()
  }
  const link = useMutation({
    mutationFn: (pid: string) => api.patch(`/listings/${listing.id}`, { product_id: pid }),
    onSuccess: () => done('Linked'),
  })
  const create = useMutation({
    mutationFn: () => api.post<Product>('/products', {
      title, tcg: listing.tcg, set_id: listing.set_id, type: listing.ptype, lang: listing.lang ?? 'en', listing_ids: [listing.id],
    }),
    onSuccess: () => done('Product created'),
    onError: (e: Error) => toast(e.message, 'error'),
  })
  return (
    <Modal open wide onClose={onClose} title="Link listing to a product">
      <p className="muted small">
        <b>{listing.store_name}</b>: {listing.name} — {money(listing.price)}
        {listing.ptype && <> · {meta?.types[listing.ptype] ?? listing.ptype}</>}
      </p>
      <Field label="Find the product">
        <input className="input" autoFocus value={q} onChange={(e) => setQ(e.target.value)} />
      </Field>
      <div className="pick-list">
        {results?.items.map((p) => (
          <button key={p.id} className="pick" onClick={() => link.mutate(p.id)}>
            <ProductImage src={p.image} alt="" className="pick-img" />
            <span>{p.title}</span>
            <span className="muted small">{p.store_count} stores · {money(p.best_price ?? p.min_price)}</span>
          </button>
        ))}
        {results && !results.items.length && <p className="muted small">No match — create it below.</p>}
      </div>
      <hr />
      <Field label="…or create a new product from this listing">
        <div className="input-row">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          <button className="btn btn-primary" disabled={!title.trim()} onClick={() => create.mutate()}>Create</button>
        </div>
      </Field>
    </Modal>
  )
}

export default function ListingsPage() {
  const qc = useQueryClient()
  const { data: meta } = useMeta()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState(sp.get('q') ?? '')
  const [linking, setLinking] = useState<Listing | null>(null)
  const params = {
    q: sp.get('q') ?? '',
    store: sp.get('store') ?? '',
    matched: sp.get('matched') ?? 'no',
    kind: sp.get('kind') ?? 'sealed',
    tcg: sp.get('tcg') ?? '',
    stock: sp.get('stock') ?? 'all',
    sort: sp.get('sort') ?? 'recent',
    page: Number(sp.get('page') ?? 1),
    page_size: 50,
  }
  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) (v !== null ? next.set(k, v) : next.delete(k))
    if (!('page' in patch)) next.delete('page')
    setSp(next, { replace: true })
  }
  useEffect(() => {
    const t = window.setTimeout(() => { if (q !== params.q) update({ q: q || null }) }, 300)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const { data: stores } = useQuery({ queryKey: ['stores'], queryFn: () => api.get<Store[]>('/stores') })
  const { data, isLoading } = useQuery({
    queryKey: ['listings', params],
    queryFn: () => api.get<Paged<Listing>>(`/listings${qs(params)}`),
    placeholderData: keepPreviousData,
  })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.patch(`/listings/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['listings'] }); qc.invalidateQueries({ queryKey: ['summary'] }) },
  })
  const rerun = useMutation({
    mutationFn: (only_unmatched: boolean) => api.post<{ listings: number; products: number }>('/matching/rerun', { only_unmatched }),
    onSuccess: (d) => { toast(`Re-matched ${d.listings} listings`); qc.invalidateQueries() },
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Matching</h1>
          <p className="muted">
            Raw store listings. Listings are grouped into products automatically by set + format + language;
            here you can fix the ones it couldn't place. Tip: adding a set in the <Link to="/calendar">calendar</Link> re-matches automatically.
          </p>
        </div>
        <div className="btn-group">
          <button className="btn" onClick={() => rerun.mutate(true)} disabled={rerun.isPending}>Re-match unmatched</button>
          <button className="btn" onClick={() => { if (window.confirm('Re-run matching for every automatic listing? Manual links are kept.')) rerun.mutate(false) }} disabled={rerun.isPending}>Re-match all</button>
        </div>
      </header>
      <div className="filters">
        <div className="filter-row">
          <input className="input search" placeholder="Search listings…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" value={params.store} onChange={(e) => update({ store: e.target.value || null })}>
            <option value="">All stores</option>
            {stores?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <div className="segmented">
            {[['no', 'Unmatched'], ['yes', 'Matched'], ['all', 'All']].map(([v, label]) => (
              <button key={v} className={params.matched === v ? 'active' : ''} onClick={() => update({ matched: v })}>{label}</button>
            ))}
          </div>
          <select className="input" value={params.kind} onChange={(e) => update({ kind: e.target.value })}>
            <option value="sealed">Sealed products</option>
            <option value="accessory">Accessories</option>
            <option value="other">Other / unrecognised</option>
            <option value="">Everything</option>
          </select>
          <select className="input" value={params.tcg} onChange={(e) => update({ tcg: e.target.value || null })}>
            <option value="">All games</option>
            {meta && Object.entries(meta.tcgs).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
      {isLoading ? <Spinner /> : !data?.items.length ? <Empty>Nothing here 🎉</Empty> : (
        <>
          <div className="result-bar muted small">{data.total} listings</div>
          <div className="table-wrap card">
            <table className="table">
              <thead><tr><th>Listing</th><th>Price</th><th className="hide-sm">Detected</th><th>Product</th><th /></tr></thead>
              <tbody>
                {data.items.map((l) => (
                  <tr key={l.id}>
                    <td>
                      <div className="small muted">{l.store_name}</div>
                      {l.url ? <a href={l.url} target="_blank" rel="noreferrer">{l.name} ↗</a> : l.name}
                    </td>
                    <td className="nowrap">
                      {money(l.price)} {l.in_stock ? <Badge tone="good">in</Badge> : <Badge tone="bad">out</Badge>}
                    </td>
                    <td className="hide-sm small muted">
                      {[l.tcg && (meta?.tcgs[l.tcg] ?? l.tcg), l.ptype && (meta?.types[l.ptype] ?? l.ptype), l.set_id, l.lang !== 'en' ? l.lang : null].filter(Boolean).join(' · ') || l.kind}
                    </td>
                    <td className="small">
                      {l.product_id
                        ? <Link to={`/product/${encodeURIComponent(l.product_id)}`}>{l.product_title}</Link>
                        : <span className="muted">{l.match_mode === 'none' ? 'kept unmatched' : 'unmatched'}</span>}
                      {l.match_mode === 'manual' && <Badge tone="muted">manual</Badge>}
                    </td>
                    <td className="nowrap">
                      <button className="btn btn-sm" onClick={() => setLinking(l)}>{l.product_id ? 'Relink' : 'Link…'}</button>
                      {l.product_id && <button className="btn-icon" title="Unlink" onClick={() => patch.mutate({ id: l.id, body: { product_id: null } })}>⛓️‍💥</button>}
                      {l.match_mode !== 'auto' && <button className="btn-icon" title="Back to automatic matching" onClick={() => patch.mutate({ id: l.id, body: { mode: 'auto' } })}>↺</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={params.page} total={data.total} pageSize={data.page_size} onPage={(p) => update({ page: String(p) })} />
        </>
      )}
      {linking && <LinkDialog listing={linking} onClose={() => setLinking(null)} />}
    </div>
  )
}
