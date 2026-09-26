import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, qs } from '../api'
import type { FavoriteSettings, HistoryResp, Listing, Paged, Product, ProductDetail } from '../types'
import { useMeta } from '../hooks'
import { EVENT_LABELS, REASON_LABELS, dateTime, money, releaseDate, relTime, shortDate } from '../format'
import { Badge, Empty, FavButton, Field, Modal, ProductImage, Spinner, TcgBadge, Toggle } from '../components/ui'
import { toast } from '../components/Toaster'

const RANGES: [number, string][] = [[7, '7d'], [30, '30d'], [90, '90d'], [180, '180d'], [365, '1y'], [0, 'All']]

function PriceChart({ productId }: { productId: string }) {
  const [days, setDays] = useState(90)
  const [hideListed, setHideListed] = useState(false)
  const { data } = useQuery({
    queryKey: ['history', productId, days],
    queryFn: () => api.get<HistoryResp>(`/products/${encodeURIComponent(productId)}/history?days=${days}`),
  })
  const chartData = useMemo(
    () => (data?.points ?? []).map((p) => ({ t: Date.parse(p.ts), best: p.best, min: p.min, store: p.best_store })),
    [data],
  )
  const stats = data?.stats
  const current = chartData.length ? chartData[chartData.length - 1].best : null

  return (
    <section className="card section">
      <div className="section-head">
        <h2>Price history</h2>
        <div className="segmented small">
          {RANGES.map(([d, label]) => (
            <button key={d} className={days === d ? 'active' : ''} onClick={() => setDays(d)}>{label}</button>
          ))}
        </div>
      </div>
      {chartData.length < 2 ? (
        <Empty>Not enough history yet — the chart fills in as stores are checked.</Empty>
      ) : (
        <div className="chart">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']}
                tickFormatter={(t: number) => new Date(t).toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit' })}
                stroke="var(--muted)" fontSize={12}
              />
              <YAxis stroke="var(--muted)" fontSize={12} width={56} domain={['auto', 'auto']}
                tickFormatter={(v: number) => `${v.toFixed(0)}€`} />
              <Tooltip
                contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8 }}
                labelFormatter={(t) => dateTime(new Date(Number(t)).toISOString())}
                formatter={(value, name, item) => {
                  const v = typeof value === 'number' ? money(value) : '—'
                  if (name === 'best') return [`${v}${item?.payload?.store ? ` · ${item.payload.store}` : ''}`, 'Cheapest in stock']
                  return [v, 'Cheapest listed (any stock)']
                }}
              />
              <Line type="stepAfter" dataKey="best" stroke="var(--accent)" strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={false} />
              {!hideListed && <Line type="stepAfter" dataKey="min" stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {stats && (
        <p className="insight">
          {current !== null && current !== undefined && Math.abs(current - stats.usual) < 0.01
            ? <><b>{money(current)}</b> is the usual price. </>
            : <>The usual price is <b>{money(stats.usual)}</b>{current !== null && current !== undefined ? <> — now <b>{money(current)}</b>{current < stats.usual ? ' 👍 below usual' : ' (above usual)'}</> : null}. </>}
          {stats.low < stats.usual && (
            <>The lowest was <b>{money(stats.low)}</b> ({(((stats.usual - stats.low) / stats.usual) * 100).toFixed(0)}% below) on {shortDate(stats.low_ts)}{stats.low_store ? <> at {stats.low_store}</> : null}. </>
          )}
          <span className="muted">{stats.changes} price change{stats.changes === 1 ? '' : 's'} in this period.</span>
        </p>
      )}
      <div className="muted small">
        <span className="legend-swatch accent" /> cheapest in stock &nbsp; <span className="legend-swatch dashed" /> cheapest listed incl. sold out
        {' '}<button className="btn-link" onClick={() => setHideListed((v) => !v)}>{hideListed ? 'show dashed line' : 'hide dashed line'}</button>
      </div>
    </section>
  )
}

function FavoritePanel({ p }: { p: ProductDetail }) {
  const qc = useQueryClient()
  const init: FavoriteSettings = p.favorite_settings ?? {
    target_price: null, notify_restock: true, notify_price: true, notify_new_store: true, note: null,
  }
  const [f, setF] = useState(init)
  const [target, setTarget] = useState(init.target_price?.toString() ?? '')
  useEffect(() => {
    setF(init)
    setTarget(init.target_price?.toString() ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.id, p.favorite])

  const save = useMutation({
    mutationFn: () => api.put(`/favorites/${encodeURIComponent(p.id)}`, {
      ...f, target_price: target.trim() ? Number(target.replace(',', '.')) : null,
    }),
    onSuccess: () => {
      toast(p.favorite ? 'Alert settings saved' : 'Added to favourites')
      qc.invalidateQueries({ queryKey: ['product', p.id] })
      qc.invalidateQueries({ queryKey: ['favorites'] })
      qc.invalidateQueries({ queryKey: ['products'] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <section className="card section fav-panel">
      <div className="section-head">
        <h2>{p.favorite ? '★ Watching' : 'Watch this product'}</h2>
        <FavButton product={p} size="lg" />
      </div>
      <Field label="Target price (€)" hint="Alert as soon as any store sells it at or below this price">
        <input className="input" inputMode="decimal" placeholder={p.best_price ? `e.g. ${Math.floor(p.best_price * 0.9)}` : 'e.g. 60'}
          value={target} onChange={(e) => setTarget(e.target.value)} />
      </Field>
      <div className="stack-sm">
        <Toggle checked={f.notify_restock} onChange={(v) => setF({ ...f, notify_restock: v })} label="Alert on restock" />
        <Toggle checked={f.notify_price} onChange={(v) => setF({ ...f, notify_price: v })} label="Alert on price drops" />
        <Toggle checked={f.notify_new_store} onChange={(v) => setF({ ...f, notify_new_store: v })} label="Alert when a new store lists it" />
      </div>
      <button className="btn btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
        {p.favorite ? 'Save alert settings' : 'Watch & save'}
      </button>
    </section>
  )
}

function OffersTable({ p }: { p: ProductDetail }) {
  const qc = useQueryClient()
  const [hideOos, setHideOos] = useState(false)
  const unlink = useMutation({
    mutationFn: (l: Listing) => api.patch(`/listings/${l.id}`, { product_id: null }),
    onSuccess: () => {
      toast('Listing unlinked — find it under Matching')
      qc.invalidateQueries({ queryKey: ['product', p.id] })
    },
  })
  const rows = p.listings.filter((l) => (hideOos ? l.in_stock : true))
  const cheapest = p.best_price
  return (
    <section className="card section">
      <div className="section-head">
        <h2>Stores <span className="muted">({p.in_stock_count} of {p.store_count} in stock)</span></h2>
        <Toggle checked={hideOos} onChange={setHideOos} label="Hide sold out" />
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>Store</th><th>Price</th><th>Stock</th><th className="hide-sm">Listing</th><th className="hide-sm">Updated</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((l) => (
              <tr key={l.id} className={!l.present ? 'row-dim' : ''}>
                <td>
                  <Link to={`/?store=${encodeURIComponent(l.store_id)}`} className="strong">{l.store_name}</Link>
                  {l.in_stock && l.price === cheapest && <Badge tone="good">cheapest</Badge>}
                </td>
                <td className="nowrap">
                  <b>{money(l.price)}</b>
                  {l.original_price && <s className="muted small"> {money(l.original_price)}</s>}
                </td>
                <td>
                  {!l.present ? <Badge tone="muted">removed</Badge>
                    : l.in_stock ? <Badge tone="good">in stock</Badge> : <Badge tone="bad">sold out</Badge>}
                  {l.preorder && <Badge tone="info">pre-order</Badge>}
                </td>
                <td className="hide-sm small">
                  {l.url ? <a href={l.url} target="_blank" rel="noreferrer">{l.name} ↗</a> : l.name}
                  {l.match_mode === 'manual' && <span className="muted"> · linked by hand</span>}
                </td>
                <td className="hide-sm muted small nowrap" title={dateTime(l.last_seen)}>{relTime(l.last_change ?? l.first_seen)}</td>
                <td className="nowrap">
                  {l.url && <a className="btn btn-sm" href={l.url} target="_blank" rel="noreferrer">Buy ↗</a>}
                  <button className="btn-icon" title="Not this product — unlink" onClick={() => unlink.mutate(l)}>⛓️‍💥</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function EditProduct({ p, open, onClose }: { p: ProductDetail; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data: meta } = useMeta()
  const [title, setTitle] = useState(p.title)
  const [image, setImage] = useState(p.image ?? '')
  const [mergeQ, setMergeQ] = useState('')
  const { data: candidates } = useQuery({
    queryKey: ['products', 'merge', mergeQ],
    queryFn: () => api.get<Paged<Product>>(`/products${qs({ q: mergeQ, page_size: 8 })}`),
    enabled: mergeQ.length >= 2,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['product'] })
    qc.invalidateQueries({ queryKey: ['products'] })
  }
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch(`/products/${encodeURIComponent(p.id)}`, body),
    onSuccess: () => { toast('Saved'); refresh(); onClose() },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const merge = useMutation({
    mutationFn: (into: string) => api.post(`/products/${encodeURIComponent(p.id)}/merge`, { into }),
    onSuccess: (_d, into) => { toast('Merged'); refresh(); onClose(); nav(`/product/${encodeURIComponent(into)}`) },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const del = useMutation({
    mutationFn: () => api.del(`/products/${encodeURIComponent(p.id)}`),
    onSuccess: () => { toast('Product deleted; its listings are now unmatched'); refresh(); nav('/') },
  })
  return (
    <Modal open={open} onClose={onClose} title="Edit product" footer={
      <>
        <button className="btn btn-danger" onClick={() => { if (window.confirm('Delete this product? Its store listings become unmatched.')) del.mutate() }}>Delete</button>
        <span className="spacer" />
        <button className="btn" onClick={() => save.mutate({ hidden: !p.hidden })}>{p.hidden ? 'Unhide' : 'Hide from catalogue'}</button>
        <button className="btn btn-primary" onClick={() => save.mutate({ title, image: image || null })}>Save</button>
      </>
    }>
      <Field label="Title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Image URL"><input className="input" value={image} onChange={(e) => setImage(e.target.value)} /></Field>
      <p className="muted small">
        {meta?.types[p.type ?? ''] ?? p.type} · {meta?.langs[p.lang ?? ''] ?? p.lang} · id <code>{p.id}</code>
        {p.manual && ' · edited by hand (the matcher won’t rename it)'}
      </p>
      <hr />
      <Field label="Duplicate? Merge into another product" hint="All store listings move to the chosen product and this one is deleted.">
        <input className="input" placeholder="Search the product to keep…" value={mergeQ} onChange={(e) => setMergeQ(e.target.value)} />
      </Field>
      <div className="pick-list">
        {candidates?.items.filter((c) => c.id !== p.id).map((c) => (
          <button key={c.id} className="pick" onClick={() => merge.mutate(c.id)}>
            <ProductImage src={c.image} alt="" className="pick-img" />
            <span>{c.title}</span><span className="muted small">{c.store_count} stores</span>
          </button>
        ))}
      </div>
    </Modal>
  )
}

export default function ProductPage() {
  const { id = '' } = useParams()
  const [editing, setEditing] = useState(false)
  const { data: meta } = useMeta()
  const { data: p, isLoading, isError } = useQuery({
    queryKey: ['product', id],
    queryFn: () => api.get<ProductDetail>(`/products/${encodeURIComponent(id)}`),
    refetchInterval: 30_000,
  })
  if (isLoading) return <div className="page"><Spinner /></div>
  if (isError || !p) return <div className="page"><Empty>Product not found. <Link to="/">Back to products</Link></Empty></div>

  const inStock = p.in_stock_count > 0
  return (
    <div className="page">
      <Link to="/" className="back">← Products</Link>
      <div className="product-hero">
        <div className="hero-img card"><ProductImage src={p.image} alt={p.title} /></div>
        <div className="hero-info">
          <div className="product-meta">
            <TcgBadge tcg={p.tcg} label={meta?.tcgs[p.tcg ?? ''] ?? p.tcg ?? undefined} />
            {p.type && <Badge>{meta?.types[p.type] ?? p.type}</Badge>}
            {p.lang && <Badge>{meta?.langs[p.lang] ?? p.lang}</Badge>}
            {p.preorder && <Badge tone="info">pre-order</Badge>}
            {p.focus && <Badge tone="warn">🔥 focus release</Badge>}
          </div>
          <h1 className="hero-title">{p.title}</h1>
          {p.set && (
            <p className="muted">
              Set <Link to={`/?set=${encodeURIComponent(p.set.id)}`}>{p.set.code ? `${p.set.code} · ` : ''}{p.set.name}</Link>
              {' · '}released {releaseDate(p.set.release_date)}{p.set.release_date && !p.set.date_confirmed ? ' (unconfirmed)' : ''}
              {' · '}<Link to="/calendar">calendar</Link>
            </p>
          )}
          <div className="stat-row">
            <div className="stat">
              <div className={`stat-value ${inStock ? '' : 'price-oos'}`}>{money(inStock ? p.best_price : p.min_price)}</div>
              <div className="stat-label">{inStock ? `cheapest in stock · ${p.best_store_name}` : 'last known price · sold out everywhere'}</div>
            </div>
            <div className="stat">
              <div className="stat-value">{p.in_stock_count}<span className="muted">/{p.store_count}</span></div>
              <div className="stat-label">stores in stock</div>
            </div>
            <div className="stat">
              <div className="stat-value small-value">{shortDate(p.created_at)}</div>
              <div className="stat-label">tracked since</div>
            </div>
            <div className="stat">
              <div className="stat-value small-value">{relTime(p.last_change)}</div>
              <div className="stat-label">last change</div>
            </div>
          </div>
          <div className="hero-actions">
            {inStock && p.listings.find((l) => l.in_stock && l.price === p.best_price)?.url && (
              <a className="btn btn-primary" target="_blank" rel="noreferrer"
                href={p.listings.find((l) => l.in_stock && l.price === p.best_price)!.url!}>
                Buy cheapest ↗
              </a>
            )}
            <a className="btn" target="_blank" rel="noreferrer"
              href={`https://www.cardmarket.com/en/${p.tcg === 'onepiece' ? 'OnePiece' : p.tcg === 'mtg' ? 'Magic' : p.tcg === 'lorcana' ? 'Lorcana' : 'Pokemon'}/Products/Search?searchString=${encodeURIComponent(p.set_name ?? p.title)}`}>
              Cardmarket ↗
            </a>
            <button className="btn" onClick={() => setEditing(true)}>Edit / merge</button>
          </div>
        </div>
      </div>

      <div className="two-col">
        <div className="col-main">
          <PriceChart productId={p.id} />
          <OffersTable p={p} />
        </div>
        <div className="col-side">
          <FavoritePanel p={p} />
          <section className="card section">
            <h2>Recent changes</h2>
            {p.events.length === 0 ? <p className="muted small">Nothing yet.</p> : (
              <ul className="event-list compact">
                {p.events.slice(0, 20).map((e) => (
                  <li key={e.id}>
                    <span>{EVENT_LABELS[e.type]?.icon ?? '•'}</span>
                    <div>
                      <div className="small"><b>{EVENT_LABELS[e.type]?.label ?? e.type}</b> · {e.store_name} · {money(e.price)}
                        {e.old_price !== null && e.old_price !== e.price && <span className="muted"> (was {money(e.old_price)})</span>}
                      </div>
                      <div className="muted small">{relTime(e.ts)}{e.alert_reason && <> · {REASON_LABELS[e.alert_reason] ?? e.alert_reason}</>}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
      {editing && <EditProduct p={p} open={editing} onClose={() => setEditing(false)} />}
    </div>
  )
}
