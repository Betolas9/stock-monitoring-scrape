import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { Settings, TelegramRecipient } from '../types'
import { useMeta } from '../hooks'
import { Field, Spinner, Toggle } from '../components/ui'
import { toast } from '../components/Toaster'

type Chat = { id: string; name: string; type: string }

function ChannelTest({ channel, settings, target, label = 'Send test' }: {
  channel: string; settings?: Record<string, unknown>; target?: string; label?: string
}) {
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; error?: string; sent?: number }>('/settings/test', { channel, settings, target }),
    onSuccess: (r) => (r.ok
      ? toast(`Test sent via ${channel}${r.sent && r.sent > 1 ? ` to ${r.sent} people` : ''} ✔`)
      : toast(`${channel}: ${r.error}`, 'error')),
    onError: (e: Error) => toast(e.message, 'error'),
  })
  return <button className="btn btn-sm" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? 'Sending…' : label}</button>
}

function TransferSection() {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const exportFile = async () => {
    setBusy(true)
    try {
      const data = await api.get<Record<string, unknown>>('/backup/export')
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `restock-monitoring-settings-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(a.href)
      toast('Settings exported')
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const importFile = async (file: File) => {
    if (!window.confirm('Import these settings? They replace your current settings, favourites, calendar and store changes.')) return
    setBusy(true)
    try {
      const data = JSON.parse(await file.text())
      const r = await api.post<Record<string, number>>('/backup/import', data)
      toast(`Imported: ${r.stores_added} stores added, ${r.stores_updated} updated, ${r.favorites} favourites, ` +
        `${r.sets_added + r.sets_updated} calendar entries`)
      qc.invalidateQueries()
    } catch (e) {
      toast(e instanceof SyntaxError ? 'That file is not a settings export' : (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card section">
      <h2>Move to another computer</h2>
      <p className="muted small">
        <b>Export</b> downloads one file with your settings (alert channels incl. the Telegram token and recipients,
        alert rules, intervals, ignored keywords), favourites and target prices, release calendar (focus, dates) and
        store list (on/off, stores you added or edited). <b>Import</b> it on the other computer. Price history isn’t
        included — copy <code>data/restock.db</code> for that. Keep the file private: it contains your bot token.
      </p>
      <div className="btn-group">
        <button className="btn" disabled={busy} onClick={exportFile}>⬇ Export settings</button>
        <label className={`btn ${busy ? 'is-disabled' : ''}`}>
          ⬆ Import settings…
          <input type="file" accept="application/json,.json" hidden disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) importFile(f) }} />
        </label>
      </div>
    </section>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data: meta } = useMeta()
  const { data: saved, isLoading } = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  const [s, setS] = useState<Settings | null>(null)
  const [keywords, setKeywords] = useState('')
  const [chats, setChats] = useState<Chat[] | null>(null)
  const [botName, setBotName] = useState<string | null>(null)

  useEffect(() => {
    if (saved && !s) {
      setS(structuredClone(saved))
      setKeywords(saved.ignore_keywords.join('\n'))
    }
  }, [saved, s])

  const save = useMutation({
    mutationFn: () => api.put<Settings>('/settings', { ...s, ignore_keywords: keywords.split('\n').map((k) => k.trim()).filter(Boolean) }),
    onSuccess: (next) => {
      toast('Settings saved')
      qc.setQueryData(['settings'], next)
      setS(structuredClone(next))
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const detect = useMutation({
    mutationFn: () => api.post<{ ok: boolean; error?: string; bot?: { username: string }; chats?: Chat[] }>(
      '/settings/telegram/detect', { bot_token: s?.channels.telegram.bot_token }),
    onSuccess: (r) => {
      if (!r.ok) return toast(r.error ?? 'Failed', 'error')
      setBotName(r.bot?.username ?? null)
      const known = new Set((s?.channels.telegram.recipients ?? []).map((x) => x.id))
      const fresh = (r.chats ?? []).filter((c) => !known.has(c.id))
      setChats(fresh)
      if (!r.chats?.length) {
        toast(`Bot @${r.bot?.username} found, but nobody has messaged it yet: open it in Telegram, press Start, then detect again`, 'error')
      } else if (!fresh.length) {
        toast('Everyone who messaged the bot is already a recipient')
      }
    },
  })
  // Recipients are saved immediately on every change (no Save button needed)
  const saveRecipients = useMutation({
    mutationFn: (recipients: TelegramRecipient[]) => api.put<Settings>('/settings', {
      channels: { telegram: {
        recipients,
        bot_token: s?.channels.telegram.bot_token ?? '',
        enabled: recipients.length ? true : s?.channels.telegram.enabled ?? false,
      } },
    }),
    onSuccess: (next) => {
      qc.setQueryData(['settings'], next)
      setS((prev) => prev && ({ ...prev, channels: { ...prev.channels, telegram: structuredClone(next.channels.telegram) } }))
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const recipientsNow = () => structuredClone(s?.channels.telegram.recipients ?? [])
  const addRecipients = (people: Chat[]) => {
    const list = recipientsNow()
    const known = new Set(list.map((r) => r.id))
    const added = people.filter((c) => !known.has(c.id))
    if (!added.length) return
    saveRecipients.mutate([...list, ...added.map((c) => ({ id: c.id, name: c.name, enabled: true }))], {
      onSuccess: () => toast(`Added ${added.map((c) => c.name).join(', ')} — they now get every alert`),
    })
    setChats((xs) => (xs ?? []).filter((x) => !added.some((a) => a.id === x.id)))
  }
  const updateRecipient = (id: string, patch: Partial<TelegramRecipient>) =>
    saveRecipients.mutate(recipientsNow().map((r) => (r.id === id ? { ...r, ...patch } : r)))
  const removeRecipient = (r: TelegramRecipient) => {
    if (!window.confirm(`Stop sending alerts to ${r.name}?`)) return
    saveRecipients.mutate(recipientsNow().filter((x) => x.id !== r.id), { onSuccess: () => toast(`${r.name} removed`) })
  }
  const [manual, setManual] = useState({ name: '', id: '' })

  if (isLoading || !s) return <div className="page"><Spinner /></div>
  const set = (fn: (d: Settings) => void) => setS((prev) => { const d = structuredClone(prev!); fn(d); return d })
  const tg = s.channels.telegram
  const dc = s.channels.discord
  const dirty = JSON.stringify({ ...s, ignore_keywords: [] }) !== JSON.stringify({ ...saved, ignore_keywords: [] })
    || keywords.split('\n').map((k) => k.trim()).filter(Boolean).join('\n') !== saved!.ignore_keywords.join('\n')

  return (
    <div className="page settings">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Everything is stored locally in <code>data/restock.db</code>.</p>
        </div>
        <button className="btn btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{dirty ? 'Save changes' : 'Saved'}</button>
      </header>

      <section className="card section">
        <h2>📱 Phone alerts — Telegram <span className="muted small">(recommended)</span></h2>
        <ol className="steps small">
          <li>In Telegram, open <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a>, send <code>/newbot</code> and follow the prompts. Copy the <b>token</b> it gives you and paste it below.</li>
          <li>Everyone who should get alerts (you, your girlfriend…) opens the bot in Telegram{botName ? <> — <a href={`https://t.me/${botName}`} target="_blank" rel="noreferrer">t.me/{botName}</a> — </> : ' '}and presses <b>Start</b> (or sends any message).</li>
          <li>Press <b>Detect people</b> and <b>Add</b> the people it finds (saved right away), then <b>Test</b>.</li>
        </ol>
        <div className="form-grid">
          <Field label="Bot token" hint={tg.bot_token === saved?.channels.telegram.bot_token ? undefined : 'Not saved yet — press Save changes at the top'}>
            <input className="input mono" type="password" autoComplete="off" value={tg.bot_token} placeholder="123456789:AA…"
              onChange={(e) => set((d) => { d.channels.telegram.bot_token = e.target.value.trim() })} />
          </Field>
          <div className="pad-top">
            <button className="btn" disabled={!tg.bot_token || detect.isPending} onClick={() => detect.mutate()}>
              {detect.isPending ? 'Looking…' : '🔍 Detect people'}
            </button>
            {botName && <span className="muted small"> bot: @{botName}</span>}
          </div>
        </div>

        {chats && chats.length > 0 && (
          <div className="card section detected">
            <div className="row-between">
              <b>Found {chats.length} new {chats.length === 1 ? 'person' : 'people'} who messaged the bot</b>
              {chats.length > 1 && <button className="btn btn-sm btn-primary" onClick={() => addRecipients(chats)}>Add all</button>}
            </div>
            {chats.map((c) => (
              <div key={c.id} className="row-between">
                <span>{c.name} <span className="muted small">{c.type} · {c.id}</span></span>
                <button className="btn btn-sm btn-primary" disabled={saveRecipients.isPending} onClick={() => addRecipients([c])}>➕ Add</button>
              </div>
            ))}
          </div>
        )}

        <div>
          <div className="field-label">Recipients ({tg.recipients.length}) — everyone switched on gets every alert</div>
          {tg.recipients.length === 0 ? (
            <p className="muted small">Nobody yet — use “Detect people”, or add a chat id below.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {tg.recipients.map((r) => (
                    <tr key={r.id}>
                      <td><Toggle checked={r.enabled} onChange={(v) => updateRecipient(r.id, { enabled: v })} title="Receives alerts" /></td>
                      <td>
                        <input className="input" defaultValue={r.name} aria-label="Name"
                          onBlur={(e) => { const name = e.target.value.trim(); if (name && name !== r.name) updateRecipient(r.id, { name }) }} />
                      </td>
                      <td className="muted small mono hide-sm">{r.id}</td>
                      <td className="nowrap">
                        <ChannelTest channel="telegram" settings={tg} target={r.id} label="Test" />
                        <button className="btn btn-sm btn-danger" onClick={() => removeRecipient(r)}>Remove</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="input-row add-row">
            <input className="input" placeholder="Name" value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} />
            <input className="input mono" placeholder="Chat id (e.g. 123456789)" value={manual.id}
              onChange={(e) => setManual({ ...manual, id: e.target.value.trim() })} />
            <button className="btn" disabled={!/^-?\d+$/.test(manual.id) || saveRecipients.isPending}
              onClick={() => { addRecipients([{ id: manual.id, name: manual.name.trim() || manual.id, type: 'private' }]); setManual({ name: '', id: '' }) }}>
              ➕ Add
            </button>
          </div>
        </div>
        <div className="row-between">
          <Toggle checked={tg.enabled} onChange={(v) => set((d) => { d.channels.telegram.enabled = v })} label="Send alerts to Telegram" />
          <ChannelTest channel="telegram" settings={tg} label="Send test to everyone" />
        </div>
      </section>

      <section className="card section">
        <h2>Discord</h2>
        <p className="muted small">Server settings → Integrations → Webhooks → New webhook → Copy URL.</p>
        <div className="form-grid">
          <Field label="Webhook URL">
            <input className="input mono" type="password" autoComplete="off" value={dc.webhook_url}
              onChange={(e) => set((d) => { d.channels.discord.webhook_url = e.target.value.trim() })} />
          </Field>
          <Field label="Mention (optional)" hint="e.g. <@your-user-id> or @here, to get a push ping">
            <input className="input" value={dc.mention} onChange={(e) => set((d) => { d.channels.discord.mention = e.target.value })} />
          </Field>
        </div>
        <div className="row-between">
          <Toggle checked={dc.enabled} onChange={(v) => set((d) => { d.channels.discord.enabled = v })} label="Send alerts to Discord" />
          <ChannelTest channel="discord" settings={dc} />
        </div>
      </section>

      <section className="card section">
        <h2>Windows notifications</h2>
        <div className="row-between">
          <Toggle checked={s.channels.windows.enabled} onChange={(v) => set((d) => { d.channels.windows.enabled = v })} label="Also show a Windows toast on this PC" />
          <ChannelTest channel="windows" />
        </div>
      </section>

      <section className="card section">
        <h2>What alerts you</h2>
        <div className="rules">
          <div>
            <h3>★ Favourites</h3>
            <Toggle checked={s.alerts.favorites.restock} onChange={(v) => set((d) => { d.alerts.favorites.restock = v })} label="Restocks" />
            <Toggle checked={s.alerts.favorites.price_drop} onChange={(v) => set((d) => { d.alerts.favorites.price_drop = v })} label="Price drops" />
            <Toggle checked={s.alerts.favorites.new_store} onChange={(v) => set((d) => { d.alerts.favorites.new_store = v })} label="Listed by a new store" />
            <Toggle checked={s.alerts.out_of_stock} onChange={(v) => set((d) => { d.alerts.out_of_stock = v })} label="Sold out" />
            <p className="muted small">Target prices are set per product and always alert.</p>
          </div>
          <div>
            <h3>🔥 Focus releases</h3>
            <Toggle checked={s.alerts.focus.new_listing} onChange={(v) => set((d) => { d.alerts.focus.new_listing = v })} label="New listings & pre-orders" />
            <Toggle checked={s.alerts.focus.restock} onChange={(v) => set((d) => { d.alerts.focus.restock = v })} label="Restocks" />
            <Toggle checked={s.alerts.focus.price_drop} onChange={(v) => set((d) => { d.alerts.focus.price_drop = v })} label="Price drops" />
            <p className="muted small">Mark sets as focus in the Releases calendar.</p>
          </div>
          <div>
            <h3>🔔 Everything else</h3>
            <Toggle checked={s.alerts.general.new_listing} onChange={(v) => set((d) => { d.alerts.general.new_listing = v })} label="New products (in stock / pre-order)" />
            <Toggle checked={s.alerts.general.restock} onChange={(v) => set((d) => { d.alerts.general.restock = v })} label="Restocks" />
            <Toggle checked={s.alerts.general.price_drop} onChange={(v) => set((d) => { d.alerts.general.price_drop = v })} label="Price drops" />
            <Toggle checked={s.alerts.general.include_accessories} onChange={(v) => set((d) => { d.alerts.general.include_accessories = v })} label="Also for accessories (sleeves, binders…)" />
            <Toggle checked={s.alerts.general.include_other} onChange={(v) => set((d) => { d.alerts.general.include_other = v })} label="Also for unrecognised products (“other”: merch, unknown formats)" />
            <div className="chips small-chips">
              {meta && Object.entries(meta.tcgs).map(([k, label]) => {
                const on = s.alerts.general.tcgs.includes(k)
                return (
                  <button key={k} className={`chip ${on ? 'active' : ''}`}
                    onClick={() => set((d) => { d.alerts.general.tcgs = on ? d.alerts.general.tcgs.filter((t) => t !== k) : [...d.alerts.general.tcgs, k] })}>
                    {label}
                  </button>
                )
              })}
            </div>
            <p className="muted small">Only these games alert here. With 70+ stores, restocks of everything can be noisy.</p>
          </div>
        </div>
        <div className="form-grid three">
          <Field label="Ignore price drops smaller than (%)">
            <input className="input" type="number" min={0} value={s.alerts.min_drop_pct} onChange={(e) => set((d) => { d.alerts.min_drop_pct = Number(e.target.value) })} />
          </Field>
          <Field label="Group into one message from" hint="alerts from one store check">
            <input className="input" type="number" min={2} value={s.alerts.group_threshold} onChange={(e) => set((d) => { d.alerts.group_threshold = Number(e.target.value) })} />
          </Field>
        </div>
      </section>

      <section className="card section">
        <h2>Store health alerts</h2>
        <p className="muted small">
          Tells you when stores stop being read (site down, blocked, layout changed, or no internet on this PC).
          Changes are grouped: everything that happens within a minute arrives as <b>one</b> message
          (e.g. “⚠️ 58 stores failing — probably a network problem”), and a store that fails and recovers
          within that minute isn’t reported.
        </p>
        <Toggle checked={s.alerts.store_health.enabled} onChange={(v) => set((d) => { d.alerts.store_health.enabled = v })} label="Alert me when stores keep failing" />
        <div className="form-grid three">
          <Field label="Failing after" hint="consecutive failed checks of a store">
            <input className="input" type="number" min={1} disabled={!s.alerts.store_health.enabled} value={s.alerts.store_health.after_failures}
              onChange={(e) => set((d) => { d.alerts.store_health.after_failures = Math.max(1, Number(e.target.value)) })} />
          </Field>
          <div className="pad-top">
            <Toggle checked={s.alerts.store_health.notify_recovered} disabled={!s.alerts.store_health.enabled}
              onChange={(v) => set((d) => { d.alerts.store_health.notify_recovered = v })} label="Also tell me when they work again" />
          </div>
        </div>
      </section>

      <section className="card section">
        <h2>Checking</h2>
        <div className="form-grid three">
          <Field label="Min seconds between checks of a store">
            <input className="input" type="number" min={30} value={s.scheduler.interval_min} onChange={(e) => set((d) => { d.scheduler.interval_min = Number(e.target.value) })} />
          </Field>
          <Field label="Max seconds" hint="Each check waits a random time between min and max">
            <input className="input" type="number" min={30} value={s.scheduler.interval_max} onChange={(e) => set((d) => { d.scheduler.interval_max = Number(e.target.value) })} />
          </Field>
          <Field label="Stores checked in parallel">
            <input className="input" type="number" min={1} max={12} value={s.scheduler.concurrency} onChange={(e) => set((d) => { d.scheduler.concurrency = Number(e.target.value) })} />
          </Field>
        </div>
        <Toggle checked={s.scheduler.paused} onChange={(v) => set((d) => { d.scheduler.paused = v })} label="Paused" />
      </section>

      <section className="card section">
        <h2>Ignored products</h2>
        <Field label="Keywords (one per line)" hint="Case-insensitive; any product whose name contains one of these is ignored everywhere.">
          <textarea className="input mono" rows={8} value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </Field>
      </section>

      <TransferSection />

      {dirty && (
        <div className="sticky-save">
          <button className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>Save changes</button>
        </div>
      )}
    </div>
  )
}
