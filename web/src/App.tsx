import { NavLink, Route, Routes } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useSummary } from './hooks'
import { relTime } from './format'
import { Toaster } from './components/Toaster'
import ProductsPage from './pages/Products'
import ProductPage from './pages/Product'
import FavoritesPage from './pages/Favorites'
import CalendarPage from './pages/Calendar'
import StoresPage from './pages/Stores'
import ActivityPage from './pages/Activity'
import ListingsPage from './pages/Listings'
import SettingsPage from './pages/Settings'

const NAV = [
  { to: '/', label: 'Products', icon: '🗂️', end: true },
  { to: '/favorites', label: 'Favourites', icon: '★' },
  { to: '/calendar', label: 'Releases', icon: '📅' },
  { to: '/stores', label: 'Stores', icon: '🏪' },
  { to: '/activity', label: 'Activity', icon: '🔔' },
  { to: '/listings', label: 'Matching', icon: '🧩' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

function StatusPanel() {
  const { data: s, isError } = useSummary()
  const qc = useQueryClient()
  const pause = useMutation({
    mutationFn: (paused: boolean) => api.put('/settings', { scheduler: { paused } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['summary'] }),
  })
  if (isError) return <div className="status-panel"><span className="dot dot-error" /> Server offline</div>
  if (!s) return <div className="status-panel muted">…</div>
  return (
    <div className="status-panel">
      <div className="status-line">
        <span className={`dot ${s.paused ? 'dot-disabled' : s.stores.running ? 'dot-running' : 'dot-ok'}`} />
        <span>{s.paused ? 'Paused' : s.stores.running ? `Checking ${s.stores.running} store(s)` : 'Monitoring'}</span>
        <button className="btn-link" onClick={() => pause.mutate(!s.paused)}>{s.paused ? 'Resume' : 'Pause'}</button>
      </div>
      <div className="status-line muted">
        <NavLink to="/stores?status=ok">{s.stores.ok} ok</NavLink>
        {s.stores.error > 0 && <NavLink to="/stores?status=error" className="text-bad">· {s.stores.error} failing</NavLink>}
        <span>· of {s.stores.enabled}</span>
      </div>
      <div className="status-line muted">Last sync {relTime(s.stores.last_success)}</div>
      {s.channels.length === 0 || (s.channels.length === 1 && s.channels[0] === 'windows') ? (
        <NavLink to="/settings" className="status-line warn-link">📱 Set up phone alerts</NavLink>
      ) : (
        <div className="status-line muted">Alerts: {s.channels.join(', ')}</div>
      )}
      {s.notifications_failed > 0 && (
        <NavLink to="/activity?tab=notifications&status=failed" className="status-line text-bad">
          ⚠ {s.notifications_failed} alert(s) failed to send
        </NavLink>
      )}
    </div>
  )
}

export default function App() {
  const { data: s } = useSummary()
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span className="brand-name">restock<span className="brand-dim">-monitoring</span></span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon" aria-hidden>{n.icon}</span>
              <span>{n.label}</span>
              {n.to === '/favorites' && s && s.favorites > 0 && <span className="nav-count">{s.favorites}</span>}
              {n.to === '/stores' && s && s.stores.error > 0 && <span className="nav-count bad">{s.stores.error}</span>}
              {n.to === '/listings' && s && s.unmatched > 0 && <span className="nav-count dim">{s.unmatched}</span>}
            </NavLink>
          ))}
        </nav>
        <StatusPanel />
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<ProductsPage />} />
          <Route path="/product/:id" element={<ProductPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/stores" element={<StoresPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/listings" element={<ListingsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<div className="page"><h1>Not found</h1></div>} />
        </Routes>
      </main>
      <Toaster />
    </div>
  )
}
