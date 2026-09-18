// Epic 8 — the default landing view (locked AC). Every section below is a
// read-only aggregation the backend already computed; this page's only
// job is laying it out as tiles that each link into their own module
// (locked AC: "every tile links into its underlying module") with color
// always paired with an icon/glyph, never alone (see Badge in primitives).

import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { useCurrentServiceDay } from '../../hooks/useCurrentServiceDay'
import { PageHeader, LoadingBlock, ErrorBlock, EmptyState } from '../../components/feedback'
import { Card, Badge, Button, SectionHeading } from '../../components/primitives'
import { ChevronRightIcon } from '../../components/icons'
import { RoleGate } from '../../components/RoleGate'

function Tile({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="flex items-center justify-between gap-2 py-2.5 border-b border-[var(--color-border)] last:border-0 active:opacity-70">
      <div className="min-w-0">{children}</div>
      <ChevronRightIcon className="h-4 w-4 text-[var(--color-text-muted)] shrink-0" />
    </Link>
  )
}

export function ChefBriefPage() {
  const { currentVenueId } = useAuth()
  const queryClient = useQueryClient()
  const { data: currentDay } = useCurrentServiceDay()
  const { data: brief, isLoading, error, refetch } = useQuery({
    queryKey: ['chef-brief', currentVenueId],
    queryFn: () => api.chefBrief.get(currentVenueId!),
    enabled: !!currentVenueId,
  })

  // A ServiceDay is lazily created as "planned" the moment anything
  // references it, but stays planned — never open — until this explicit,
  // audited step (locked AC: opening is a deliberate action, not a side
  // effect). Closing a day into a Handover requires it to be open first,
  // so without this the whole Handover flow would be unreachable.
  const startService = useMutation({
    mutationFn: () => api.serviceDays.start(currentVenueId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service-day', 'current', currentVenueId] })
      queryClient.invalidateQueries({ queryKey: ['chef-brief', currentVenueId] })
    },
  })

  if (isLoading) return <LoadingBlock label="Loading today's brief…" />
  if (error) return <ErrorBlock error={error} onRetry={() => refetch()} />
  if (!brief) return null

  const understaffedGaps = brief.coverage_gaps.filter((g) => g.scheduled_staff < g.minimum_staff)

  return (
    <div className="space-y-5 pb-4">
      <PageHeader title="Chef Brief" subtitle={format(new Date(brief.business_date), 'EEEE d MMMM')} />

      {currentDay?.status === 'planned' && (
        <RoleGate allow={MANAGEMENT_ROLES}>
          <Card className="space-y-2">
            <p className="text-sm text-[var(--color-text-muted)]">Today's service hasn't started yet.</p>
            {startService.isError && <ErrorBlock error={startService.error} />}
            <Button fullWidth onClick={() => startService.mutate()} disabled={startService.isPending}>
              {startService.isPending ? 'Starting…' : 'Start today\'s service'}
            </Button>
          </Card>
        </RoleGate>
      )}

      {understaffedGaps.length > 0 && (
        <Card>
          <SectionHeading>Coverage gaps</SectionHeading>
          {understaffedGaps.map((gap) => (
            <Tile key={gap.coverage_rule_id} to="/roster">
              <p className="font-medium">Short {gap.minimum_staff - gap.scheduled_staff} staff</p>
              <p className="text-sm text-[var(--color-text-muted)]">
                {gap.window_start}–{gap.window_end}, {gap.scheduled_staff}/{gap.minimum_staff} scheduled
              </p>
            </Tile>
          ))}
        </Card>
      )}

      <Card>
        <SectionHeading>Rostered today ({brief.rostered_staff.length})</SectionHeading>
        {brief.rostered_staff.length === 0 ? (
          <EmptyState title="Nobody rostered yet" hint="Add shifts from the Roster tab." />
        ) : (
          brief.rostered_staff.map((s) => (
            <Tile key={s.shift_id} to={`/roster/shifts/${s.shift_id}`}>
              <div className="flex items-center gap-2">
                <p className="font-medium">{s.staff_name}</p>
                <Badge tone={s.attendance_status === 'present' ? 'success' : s.attendance_status === 'absent' ? 'danger' : s.attendance_status ? 'warning' : 'neutral'}>
                  {s.attendance_status ?? 'expected'}
                </Badge>
              </div>
              <p className="text-sm text-[var(--color-text-muted)]">
                {format(new Date(s.start_at), 'h:mma')}–{format(new Date(s.end_at), 'h:mma')}
              </p>
            </Tile>
          ))
        )}
      </Card>

      <Card>
        <SectionHeading action={<Link to="/prep" className="text-xs text-[var(--color-accent)]">View all</Link>}>
          Priority prep ({brief.priority_open_prep_tasks.length})
        </SectionHeading>
        {brief.priority_open_prep_tasks.length === 0 ? (
          <EmptyState icon="✓" title="Nothing outstanding" />
        ) : (
          brief.priority_open_prep_tasks.slice(0, 5).map((task) => (
            <Tile key={task.id} to="/prep">
              <p className="font-medium">{task.item}</p>
              <p className="text-sm text-[var(--color-text-muted)]">{task.quantity} {task.unit} · {task.status.replace('_', ' ')}</p>
            </Tile>
          ))
        )}
      </Card>

      {brief.carried_forward_tasks.length > 0 && (
        <Card>
          <SectionHeading>Carried forward from yesterday ({brief.carried_forward_tasks.length})</SectionHeading>
          {brief.carried_forward_tasks.map((task) => (
            <Tile key={task.id} to="/prep">
              <p className="font-medium">{task.item}</p>
              <p className="text-sm text-[var(--color-text-muted)]">{task.quantity} {task.unit}</p>
            </Tile>
          ))}
        </Card>
      )}

      {brief.approaching_order_cutoffs.length > 0 && (
        <Card>
          <SectionHeading>Approaching order cutoffs</SectionHeading>
          {brief.approaching_order_cutoffs.map((c) => (
            <Tile key={c.purchase_order_id} to={`/orders/${c.purchase_order_id}`}>
              <p className="font-medium">{c.supplier_name}</p>
              <p className="text-sm text-[var(--color-text-muted)]">Cuts off {format(new Date(c.cutoff_at), "EEE h:mma")}</p>
            </Tile>
          ))}
        </Card>
      )}

      {brief.open_equipment_issues.length > 0 && (
        <Card>
          <SectionHeading>Open equipment issues</SectionHeading>
          {brief.open_equipment_issues.map((issue) => (
            <Tile key={issue.id} to={`/kitchen-memory/equipment/${issue.equipment_item_id}`}>
              <div className="flex items-center gap-2">
                <Badge tone={issue.priority === 'high' ? 'danger' : issue.priority === 'medium' ? 'warning' : 'neutral'}>{issue.priority}</Badge>
              </div>
              <p className="text-sm text-[var(--color-text-muted)]">Opened {format(new Date(issue.opened_at), 'd MMM')}</p>
            </Tile>
          ))}
        </Card>
      )}

      {brief.unavailable_or_low_menu_items.length > 0 && (
        <Card>
          <SectionHeading>Menu availability</SectionHeading>
          {brief.unavailable_or_low_menu_items.map((m) => (
            <Tile key={m.menu_item_id} to={`/kitchen-memory/menu-items/${m.menu_item_id}`}>
              <p className="font-medium">{m.menu_item_name}</p>
              <Badge tone={m.status === 'unavailable' ? 'danger' : 'warning'}>{m.status.replace('_', ' ')}</Badge>
            </Tile>
          ))}
        </Card>
      )}

      {brief.yesterdays_handover && (
        <Card>
          <SectionHeading action={<Link to="/handover" className="text-xs text-[var(--color-accent)]">Open</Link>}>
            Yesterday's handover
          </SectionHeading>
          <p className="text-sm">{brief.yesterdays_handover.note || 'No note left.'}</p>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">{brief.yesterdays_handover.items.filter((i) => i.included).length} items</p>
        </Card>
      )}
    </div>
  )
}
