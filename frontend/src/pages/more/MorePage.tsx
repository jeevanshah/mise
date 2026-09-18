// The "More" hub — admin/settings screens that don't need a bottom-nav
// tab of their own live here, plus venue switching and sign-out.

import { Link } from 'react-router-dom'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { Button, Card } from '../../components/primitives'
import { PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import { ChevronRightIcon } from '../../components/icons'

function MoreLink({ to, label, hint }: { to: string; label: string; hint?: string }) {
  return (
    <Link to={to} className="flex items-center justify-between py-3 border-b border-[var(--color-border)] last:border-0">
      <div>
        <p className="font-medium">{label}</p>
        {hint && <p className="text-sm text-[var(--color-text-muted)]">{hint}</p>}
      </div>
      <ChevronRightIcon className="w-5 h-5 text-[var(--color-text-muted)]" />
    </Link>
  )
}

export function MorePage() {
  const { me, currentVenueId, currentRole, setCurrentVenueId, logout } = useAuth()

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="More" subtitle={me?.email} />

      {me && me.memberships.length > 1 && (
        <Card>
          <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-text-muted)] mb-2">Venue</p>
          <div className="space-y-1">
            {me.memberships.map((m) => (
              <button
                key={m.venue_id}
                onClick={() => setCurrentVenueId(m.venue_id)}
                className={`block w-full text-left py-2 px-3 rounded-lg ${m.venue_id === currentVenueId ? 'bg-[var(--color-surface-raised)]' : ''}`}
              >
                {m.venue_id === currentVenueId ? '✓ ' : ''}
                {m.role.replace('_', ' ')} — {m.venue_id.slice(0, 8)}
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <MoreLink to="/kitchen-memory" label="Kitchen memory" hint="Recipes, search" />
        <RoleGate allow={MANAGEMENT_ROLES}>
          <MoreLink to="/more/venue" label="Venue settings" hint="Timezone, business day boundary" />
          <MoreLink to="/more/invite" label="Invite" hint="Add a team member" />
          <MoreLink to="/more/staffing" label="Staffing" hint="Stations, staff, coverage rules" />
          <MoreLink to="/more/catalog" label="Catalog" hint="Suppliers, ingredients, menu, equipment" />
          <MoreLink to="/more/notifications" label="Notifications" hint="Run checks manually" />
          <MoreLink to="/more/pilot-metrics" label="Pilot metrics" hint="Minutes saved, incidents, decision" />
        </RoleGate>
      </Card>

      <Card>
        <p className="text-sm text-[var(--color-text-muted)] mb-3">
          Signed in as {me?.email} · {currentRole?.replace('_', ' ')}
        </p>
        <Button fullWidth variant="secondary" onClick={logout}>Sign out</Button>
      </Card>
    </div>
  )
}
