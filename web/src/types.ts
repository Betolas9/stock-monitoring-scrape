export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Meta {
  app: string
  version: string
  tcgs: Record<string, string>
  types: Record<string, string>
  langs: Record<string, string>
  platforms: string[]
}

export interface Summary {
  stores: {
    total: number
    enabled: number
    ok: number
    error: number
    pending: number
    running: number
    last_success: string | null
  }
  products: number
  products_in_stock: number
  listings: number
  unmatched: number
  favorites: number
  focus_sets: number
  events_24h: number
  alerts_24h: number
  notifications_failed: number
  notifications_pending: number
  paused: boolean
  channels: string[]
  started_at: string | null
}

export interface Product {
  id: string
  tcg: string | null
  set_id: string | null
  type: string | null
  lang: string | null
  variant: string | null
  title: string
  image: string | null
  manual: boolean
  hidden: boolean
  created_at: string
  best_price: number | null
  best_store: string | null
  best_store_name: string | null
  min_price: number | null
  store_count: number
  in_stock_count: number
  change_30d: number | null
  last_change: string | null
  set_name: string | null
  set_code: string | null
  release_date: string | null
  focus: boolean
  favorite: boolean
  target_price: number | null
  preorder: boolean
}

export interface Listing {
  id: number
  store_id: string
  store_name: string
  store_platform?: string
  external_id: string
  name: string
  url: string | null
  image: string | null
  price: number | null
  original_price: number | null
  in_stock: boolean
  present: boolean
  preorder: boolean
  first_seen: string
  last_seen: string
  last_change: string | null
  kind: string | null
  tcg: string | null
  lang: string | null
  ptype: string | null
  set_id: string | null
  product_id: string | null
  product_title?: string | null
  match_mode: 'auto' | 'manual' | 'none'
}

export interface FavoriteSettings {
  target_price: number | null
  notify_restock: boolean
  notify_price: boolean
  notify_new_store: boolean
  note: string | null
  created_at?: string
}

export interface EventItem {
  id: number
  ts: string
  type: string
  store_id: string | null
  store_name: string | null
  listing_id: number | null
  product_id: string | null
  product_title?: string | null
  product_image?: string | null
  title: string | null
  url: string | null
  image: string | null
  price: number | null
  old_price: number | null
  in_stock: boolean | null
  alert_reason: string | null
}

export interface SetInfo {
  id: string
  tcg: string
  code: string | null
  name: string
  aliases: string[]
  release_date: string | null
  date_confirmed: boolean
  focus: boolean
  auto_created: boolean
  notes: string | null
  product_count: number
  listing_count: number
  in_stock_count: number
  preorder_count: number
  min_best_price: number | null
}

export interface ProductDetail extends Product {
  listings: Listing[]
  favorite_settings: FavoriteSettings | null
  events: EventItem[]
  set: SetInfo | null
}

export interface HistoryPoint {
  ts: string
  best: number | null
  best_store: string | null
  min: number | null
}

export interface HistoryResp {
  points: HistoryPoint[]
  series: { listing_id: number; store_id: string; store_name: string; points: { ts: string; price: number | null; in_stock: boolean }[] }[]
  stats: {
    low: number
    low_ts: string
    low_store: string | null
    high: number
    high_ts: string
    usual: number
    changes: number
  } | null
}

export interface Store {
  id: string
  name: string
  platform: string
  url: string
  urls: string[]
  options: Record<string, unknown>
  enabled: boolean
  interval_min: number | null
  interval_max: number | null
  notes: string | null
  status: 'pending' | 'running' | 'ok' | 'error'
  last_check_at: string | null
  last_success_at: string | null
  last_error: string | null
  last_error_at: string | null
  last_duration_ms: number | null
  last_raw_count: number | null
  consecutive_failures: number
  next_check_at: string | null
  baseline_done: boolean
  listing_count: number
  in_stock_count: number
  matched_count: number
}

export interface StoreTestResult {
  ok: boolean
  error?: string
  scraped?: number
  kept?: number
  in_stock?: number
  seconds: number
  kinds?: Record<string, number>
  sample?: { name: string; price: string | null; in_stock: boolean; url: string; kind: string; tcg: string | null; type: string | null; set_id: string | null }[]
}

export interface NotificationItem {
  id: number
  created_at: string
  channel: string
  target: string | null
  status: 'pending' | 'sent' | 'failed'
  attempts: number
  next_attempt_at: string | null
  sent_at: string | null
  last_error: string | null
  summary: string | null
}

export interface TelegramRecipient {
  id: string
  name: string
  enabled: boolean
}

export interface Settings {
  scheduler: { interval_min: number; interval_max: number; concurrency: number; paused: boolean }
  ignore_keywords: string[]
  channels: {
    telegram: { enabled: boolean; bot_token: string; recipients: TelegramRecipient[] }
    discord: { enabled: boolean; webhook_url: string; mention: string }
    windows: { enabled: boolean }
  }
  alerts: {
    favorites: { restock: boolean; price_drop: boolean; new_store: boolean }
    focus: { new_listing: boolean; restock: boolean; price_drop: boolean }
    general: {
      new_listing: boolean; restock: boolean; price_drop: boolean; tcgs: string[]
      include_accessories: boolean; include_other: boolean
    }
    out_of_stock: boolean
    min_drop_pct: number
    group_threshold: number
    store_health: { enabled: boolean; after_failures: number; notify_recovered: boolean }
  }
}
