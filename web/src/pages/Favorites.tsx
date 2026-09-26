import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { FavoriteSettings, Product } from '../types'
import { money, relTime } from '../format'
import { Badge, Empty, FavButton, ProductImage, Spinner, TcgBadge } from '../components/ui'

type Fav = Product & { favorite_settings: FavoriteSettings }

export default function FavoritesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['favorites'],
    queryFn: () => api.get<Fav[]>('/favorites'),
    refetchInterval: 15_000,
  })
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Favourites</h1>
          <p className="muted">Products you watch. You get an alert when they restock, drop in price, reach your target price or appear in a new store.</p>
        </div>
      </header>
      {isLoading ? <Spinner /> : !data?.length ? (
        <Empty>
          No favourites yet. Open any product and press ☆ — or set a target price to be alerted when it gets cheap.
          <p><Link to="/" className="btn btn-primary">Browse products</Link></p>
        </Empty>
      ) : (
        <div className="fav-list">
          {data.map((p) => {
            const inStock = p.in_stock_count > 0
            const target = p.favorite_settings.target_price
            const price = inStock ? p.best_price : p.min_price
            const hit = target !== null && inStock && p.best_price !== null && p.best_price <= target
            const progress = target && price ? Math.min(100, Math.max(0, (target / price) * 100)) : null
            return (
              <Link key={p.id} to={`/product/${encodeURIComponent(p.id)}`} className={`card fav-row ${hit ? 'is-hit' : ''}`}>
                <ProductImage src={p.image} alt={p.title} className="fav-img" />
                <div className="fav-main">
                  <div className="product-meta">
                    <TcgBadge tcg={p.tcg} label={p.set_code ?? undefined} />
                    {p.focus && <Badge tone="warn">🔥</Badge>}
                    {p.preorder && <Badge tone="info">pre-order</Badge>}
                  </div>
                  <div className="strong">{p.title}</div>
                  <div className="muted small">
                    {inStock ? `In stock at ${p.in_stock_count} of ${p.store_count} stores` : p.store_count ? `Sold out at all ${p.store_count} stores` : 'Not listed anywhere right now'}
                    {' · '}changed {relTime(p.last_change)}
                  </div>
                  {progress !== null && (
                    <div className="target-bar" title="How close the cheapest price is to your target">
                      <div className="target-fill" style={{ width: `${progress}%` }} />
                    </div>
                  )}
                </div>
                <div className="fav-price">
                  <div className={`price ${inStock ? '' : 'price-oos'}`}>{money(price)}</div>
                  {inStock && <div className="muted small">{p.best_store_name}</div>}
                  {target !== null && (
                    <div className={`small ${hit ? 'text-good strong' : 'muted'}`}>{hit ? '🎯 at target!' : `🎯 ${money(target)}`}</div>
                  )}
                </div>
                <FavButton product={p} />
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
