import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, qs } from '../api'
import type { Paged, Product } from '../types'
import { useMeta, useSummary } from '../hooks'
import { money, pct, releaseDate } from '../format'
import { Badge, Empty, FavButton, Pagination, ProductImage, Spinner, TcgBadge } from '../components/ui'

const SORTS: [string, string][] = [
  ['stock', 'In stock first'],
  ['price', 'Price ↑'],
  ['price_desc', 'Price ↓'],
  ['stores', 'Most stores'],
  ['change', 'Biggest 30-day drop'],
  ['activity', 'Recently changed'],
  ['recent', 'Newest in catalogue'],
  ['release', 'Release date'],
  ['name', 'Name'],
]

const MAIN_TCGS = ['pokemon', 'onepiece', 'mtg', 'lorcana', 'riftbound', 'yugioh', 'dbs', 'digimon']

export function ProductCard({ p }: { p: Product }) {
  const inStock = p.in_stock_count > 0
  const price = inStock ? p.best_price : p.min_price
  return (
    <Link to={`/product/${encodeURIComponent(p.id)}`} className={`card product-card ${inStock ? '' : 'is-oos'}`}>
      <div className="product-img-wrap">
        <ProductImage src={p.image} alt={p.title} className="product-img" />
        <FavButton product={p} />
        <div className="card-flags">
          {p.focus && <span className="flag flag-focus" title="Focus release">🔥</span>}
          {p.preorder && <span className="flag flag-pre">Pre-order</span>}
          {p.lang && p.lang !== 'en' && <span className="flag">{p.lang.toUpperCase()}</span>}
        </div>
      </div>
      <div className="product-body">
        <div className="product-meta">
          <TcgBadge tcg={p.tcg} label={p.set_code ?? undefined} />
          {p.release_date && <span className="muted small">{releaseDate(p.release_date)}</span>}
        </div>
        <div className="product-title">{p.title}</div>
        <div className="product-foot">
          <div>
            <div className={`price ${inStock ? '' : 'price-oos'}`}>{money(price)}</div>
            <div className="small muted">
              {inStock ? (
                <>at {p.best_store_name}</>
              ) : (
                <span className="text-bad">sold out</span>
              )}
            </div>
          </div>
          <div className="right">
            <div className={`stock-pill ${inStock ? 'in' : 'out'}`}>
              {p.in_stock_count}/{p.store_count} {p.store_count === 1 ? 'store' : 'stores'}
            </div>
            {p.change_30d !== null && p.change_30d !== 0 && (
              <div className={`small ${p.change_30d < 0 ? 'text-good' : 'text-bad'}`} title="Cheapest price vs 30 days ago">
                {p.change_30d < 0 ? '▼' : '▲'} {pct(p.change_30d)}
              </div>
            )}
          </div>
        </div>
        {p.target_price !== null && p.favorite && (
          <div className="small muted">🎯 target {money(p.target_price)}</div>
        )}
      </div>
    </Link>
  )
}

export default function ProductsPage() {
  const [sp, setSp] = useSearchParams()
  const { data: meta } = useMeta()
  const { data: summary } = useSummary()
  const [q, setQ] = useState(sp.get('q') ?? '')

  const params = {
    q: sp.get('q') ?? '',
    tcg: sp.get('tcg') ?? '',
    type: sp.get('type') ?? '',
    lang: sp.get('lang') ?? '',
    set: sp.get('set') ?? '',
    store: sp.get('store') ?? '',
    stock: sp.get('stock') ?? 'all',
    focus: sp.get('focus') === '1',
    preorder: sp.get('preorder') === '1',
    sort: sp.get('sort') ?? 'stock',
    page: Number(sp.get('page') ?? 1),
    page_size: 48,
  }

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in patch)) next.delete('page')
    setSp(next, { replace: true })
  }

  // debounce the search box into the URL
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (q !== (sp.get('q') ?? '')) update({ q })
    }, 300)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['products', params],
    queryFn: () => api.get<Paged<Product>>(`/products${qs(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  })

  const tcgs = meta ? MAIN_TCGS.filter((t) => t in meta.tcgs) : []
  const activeFilters = ['tcg', 'type', 'lang', 'set', 'store', 'q', 'focus', 'preorder'].filter((k) => sp.get(k))
  const types = meta ? Object.entries(meta.types).filter(([k]) => k !== 'other') : []

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Products</h1>
          <p className="muted">
            {summary ? `${summary.products} sealed products across ${summary.stores.enabled} stores · ${summary.products_in_stock} in stock right now` : ' '}
          </p>
        </div>
      </header>

      <div className="filters">
        <input
          className="input search"
          placeholder="Search products… (e.g. Perfect Order ETB)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="chips">
          <button className={`chip ${!params.tcg ? 'active' : ''}`} onClick={() => update({ tcg: null })}>All games</button>
          {tcgs.map((t) => (
            <button key={t} className={`chip ${params.tcg === t ? 'active' : ''}`} onClick={() => update({ tcg: params.tcg === t ? null : t })}>
              {meta!.tcgs[t]}
            </button>
          ))}
        </div>
        <div className="filter-row">
          <select className="input" value={params.type} onChange={(e) => update({ type: e.target.value })}>
            <option value="">All formats</option>
            {types.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <select className="input" value={params.lang} onChange={(e) => update({ lang: e.target.value })}>
            <option value="">All languages</option>
            {meta && Object.entries(meta.langs).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <div className="segmented">
            {[['all', 'All'], ['in', 'In stock'], ['out', 'Sold out']].map(([v, label]) => (
              <button key={v} className={params.stock === v ? 'active' : ''} onClick={() => update({ stock: v === 'all' ? null : v })}>
                {label}
              </button>
            ))}
          </div>
          <button className={`chip ${params.focus ? 'active' : ''}`} onClick={() => update({ focus: params.focus ? null : '1' })} title="Only sets marked as focus in the release calendar">
            🔥 Focus releases
          </button>
          <button className={`chip ${params.preorder ? 'active' : ''}`} onClick={() => update({ preorder: params.preorder ? null : '1' })}>
            Pre-orders
          </button>
          <select className="input" value={params.sort} onChange={(e) => update({ sort: e.target.value })}>
            {SORTS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          {activeFilters.length > 0 && (
            <button className="btn-link" onClick={() => { setQ(''); setSp(new URLSearchParams(), { replace: true }) }}>
              Clear filters
            </button>
          )}
        </div>
        {(params.set || params.store) && (
          <div className="filter-row">
            {params.set && <Badge tone="info">Set: {params.set} <button className="btn-x" onClick={() => update({ set: null })}>✕</button></Badge>}
            {params.store && <Badge tone="info">Store: {params.store} <button className="btn-x" onClick={() => update({ store: null })}>✕</button></Badge>}
          </div>
        )}
      </div>

      <div className="result-bar muted small">
        {data ? `${data.total} product${data.total === 1 ? '' : 's'}` : ''} {isFetching && <span className="dot dot-running inline" />}
      </div>

      {isLoading ? (
        <Spinner />
      ) : data && data.items.length ? (
        <>
          <div className="grid">
            {data.items.map((p) => <ProductCard key={p.id} p={p} />)}
          </div>
          <Pagination page={params.page} total={data.total} pageSize={data.page_size} onPage={(p) => update({ page: String(p) })} />
        </>
      ) : (
        <Empty>
          No products match these filters.
          {summary && summary.stores.ok === 0 && <p>The first store checks are still running — products appear as stores are read.</p>}
        </Empty>
      )}
    </div>
  )
}
