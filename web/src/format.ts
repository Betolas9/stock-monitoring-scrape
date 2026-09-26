const eur = new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' })

export function money(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : eur.format(v)
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return ''
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}%`
}

export function relTime(ts: string | null | undefined): string {
  if (!ts) return 'never'
  const diff = (Date.now() - Date.parse(ts)) / 1000
  const future = diff < 0
  const s = Math.abs(diff)
  let out: string
  if (s < 45) out = `${Math.round(s)}s`
  else if (s < 3600) out = `${Math.round(s / 60)} min`
  else if (s < 86400) out = `${Math.round(s / 3600)} h`
  else if (s < 86400 * 30) out = `${Math.round(s / 86400)} d`
  else return shortDate(ts)
  if (s < 10 && !future) return 'just now'
  return future ? `in ${out}` : `${out} ago`
}

export function shortDate(ts: string | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function dateTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('pt-PT', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/** "2026-11-13" → "13 Nov 2026" (release dates have no time zone) */
export function releaseDate(d: string | null | undefined): string {
  if (!d) return 'TBA'
  const [y, m, day] = d.split('-').map(Number)
  return new Date(y, m - 1, day).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function daysUntil(d: string | null | undefined): number | null {
  if (!d) return null
  const [y, m, day] = d.split('-').map(Number)
  const target = new Date(y, m - 1, day).getTime()
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((target - today.getTime()) / 86400000)
}

export const EVENT_LABELS: Record<string, { icon: string; label: string }> = {
  new_listing: { icon: '🆕', label: 'New' },
  back_in_stock: { icon: '✅', label: 'Back in stock' },
  out_of_stock: { icon: '❌', label: 'Sold out' },
  price_drop: { icon: '📉', label: 'Price drop' },
  price_rise: { icon: '📈', label: 'Price up' },
}

export const REASON_LABELS: Record<string, string> = {
  target: '🎯 Target',
  favorite: '⭐ Favourite',
  focus: '🔥 Focus',
  general: '🔔 Alert',
}

export const TCG_COLORS: Record<string, string> = {
  pokemon: '#f5c518',
  onepiece: '#e5484d',
  mtg: '#a78bfa',
  lorcana: '#60a5fa',
  yugioh: '#f97316',
  digimon: '#22d3ee',
  dbs: '#fb923c',
  riftbound: '#34d399',
}

export function tcgColor(tcg: string | null | undefined): string {
  return (tcg && TCG_COLORS[tcg]) || '#94a3b8'
}
