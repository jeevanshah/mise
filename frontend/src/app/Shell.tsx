// Mobile-first app shell: a slim top bar (venue name + switcher) and a
// 5-item bottom nav sized for a thumb, one-handed, at 390px width (locked
// AC). Quick Capture gets its own floating action button rather than a
// 6th nav slot — it's the one action a chef needs mid-service from
// anywhere, not just from an "Orders" tab.

import { type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { HomeIcon, RosterIcon, PrepIcon, OrdersIcon, MoreIcon, PlusIcon } from '../components/icons'

const NAV_ITEMS = [
  { to: '/', label: 'Brief', Icon: HomeIcon, end: true },
  { to: '/roster', label: 'Roster', Icon: RosterIcon, end: false },
  { to: '/prep', label: 'Prep', Icon: PrepIcon, end: false },
  { to: '/orders', label: 'Orders', Icon: OrdersIcon, end: false },
  { to: '/more', label: 'More', Icon: MoreIcon, end: false },
]

export function Shell({ children }: { children: ReactNode }) {
  const { me, currentVenueId, setCurrentVenueId } = useAuth()
  const navigate = useNavigate()
  const memberships = me?.memberships ?? []

  return (
    <div className="flex flex-col min-h-dvh max-w-md mx-auto w-full bg-[var(--color-surface)]">
      <header className="flex items-center justify-between gap-2 px-4 h-14 border-b border-[var(--color-border)] shrink-0">
        <span className="font-semibold text-[var(--color-accent)]">Mise</span>
        {memberships.length > 1 ? (
          <select
            aria-label="Current venue"
            value={currentVenueId ?? ''}
            onChange={(e) => setCurrentVenueId(e.target.value)}
            className="bg-transparent text-sm text-[var(--color-text-muted)] border border-[var(--color-border)] rounded-lg px-2 py-1 max-w-[55%]"
          >
            {memberships.map((m) => (
              <option key={m.venue_id} value={m.venue_id}>
                {m.venue_id === currentVenueId ? 'This venue' : m.venue_id.slice(0, 8)}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-xs text-[var(--color-text-muted)]">{me?.email}</span>
        )}
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-24">{children}</main>

      {/* Mobile-first: the shell IS the viewport on a real phone, so a
          plain viewport-fixed position sits correctly bottom-right without
          extra centering math. On a wide desktop preview it floats near
          the right edge of the screen rather than the app column — an
          acceptable tradeoff for a tool built for a phone, not a desktop
          window. */}
      <button
        onClick={() => navigate('/capture')}
        aria-label="Quick capture"
        className="fixed bottom-20 right-4 h-14 w-14 rounded-full bg-[var(--color-accent)] text-[#111827] shadow-lg flex items-center justify-center active:scale-95 transition-transform"
      >
        <PlusIcon className="h-6 w-6" />
      </button>

      <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md border-t border-[var(--color-border)] bg-[var(--color-surface-raised)] grid grid-cols-5 pb-[env(safe-area-inset-bottom)]">
        {NAV_ITEMS.map(({ to, label, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex flex-col items-center justify-center gap-0.5 py-2.5 text-xs ${isActive ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-muted)]'}`
            }
          >
            <Icon className="h-5 w-5" />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
