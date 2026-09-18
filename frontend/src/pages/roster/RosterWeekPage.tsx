// Epic 2 — Kitchen Roster. A vertical, day-by-day list rather than a wide
// grid table: a 7-column grid can't work at 390px width (locked AC), so
// each day is its own card the chef scrolls through one-handed.

import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { addDays, format, startOfWeek } from 'date-fns'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { useCurrentServiceDay } from '../../hooks/useCurrentServiceDay'
import { Badge, Button, Card, Field, Input, Select, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import type { ShiftOut } from '../../api/types'

function shiftBadgeTone(status: ShiftOut['status']) {
  if (status === 'published') return 'success' as const
  if (status === 'cancelled') return 'danger' as const
  return 'neutral' as const
}

export function RosterWeekPage() {
  const { currentVenueId } = useAuth()
  const { data: currentDay } = useCurrentServiceDay()
  const [weekStart, setWeekStart] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const queryClient = useQueryClient()

  const resolvedWeekStart = weekStart ?? (currentDay ? format(startOfWeek(new Date(currentDay.business_date), { weekStartsOn: 1 }), 'yyyy-MM-dd') : null)

  const { data: shifts, isLoading, error, refetch } = useQuery({
    queryKey: ['shifts', currentVenueId, resolvedWeekStart],
    queryFn: () => api.roster.listShifts(currentVenueId!, { week_start: resolvedWeekStart! }),
    enabled: !!currentVenueId && !!resolvedWeekStart,
  })

  const { data: stations } = useQuery({
    queryKey: ['stations', currentVenueId],
    queryFn: () => api.staffing.listStations(currentVenueId!),
    enabled: !!currentVenueId,
  })
  const { data: staff } = useQuery({
    queryKey: ['staff', currentVenueId],
    queryFn: () => api.staffing.listStaff(currentVenueId!),
    enabled: !!currentVenueId,
  })

  const publishWeek = useMutation({
    mutationFn: () => api.roster.publishWeek(currentVenueId!, resolvedWeekStart!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shifts', currentVenueId, resolvedWeekStart] }),
  })

  const days = useMemo(() => {
    if (!resolvedWeekStart) return []
    const start = new Date(resolvedWeekStart)
    return Array.from({ length: 7 }, (_, i) => addDays(start, i))
  }, [resolvedWeekStart])

  const stationsById = useMemo(() => new Map((stations ?? []).map((s) => [s.id, s])), [stations])
  const staffById = useMemo(() => new Map((staff ?? []).map((s) => [s.id, s])), [staff])

  function goToWeek(delta: number) {
    if (!resolvedWeekStart) return
    setWeekStart(format(addDays(new Date(resolvedWeekStart), delta * 7), 'yyyy-MM-dd'))
  }

  return (
    <div className="space-y-4 pb-4">
      <PageHeader
        title="Roster"
        subtitle={resolvedWeekStart ? `Week of ${format(new Date(resolvedWeekStart), 'd MMM')}` : undefined}
        action={
          <RoleGate allow={MANAGEMENT_ROLES}>
            <Button onClick={() => setShowCreate((v) => !v)}>{showCreate ? 'Close' : '+ Shift'}</Button>
          </RoleGate>
        }
      />

      <div className="flex gap-2">
        <Button variant="secondary" fullWidth onClick={() => goToWeek(-1)}>← Prev week</Button>
        <Button variant="secondary" fullWidth onClick={() => goToWeek(1)}>Next week →</Button>
      </div>

      <RoleGate allow={MANAGEMENT_ROLES}>
        <Button variant="secondary" fullWidth onClick={() => publishWeek.mutate()} disabled={publishWeek.isPending || !resolvedWeekStart}>
          {publishWeek.isPending ? 'Publishing…' : 'Publish this week'}
        </Button>
        {publishWeek.isError && <ErrorBlock error={publishWeek.error} />}
        <Button
          variant="secondary"
          fullWidth
          disabled={!resolvedWeekStart}
          onClick={async () => {
            if (!resolvedWeekStart) return
            const blob = await api.roster.downloadRosterPdf(currentVenueId!, resolvedWeekStart)
            window.open(URL.createObjectURL(blob), '_blank')
          }}
        >
          Download roster PDF
        </Button>
      </RoleGate>

      {showCreate && resolvedWeekStart && (
        <CreateShiftForm
          venueId={currentVenueId!}
          stations={stations ?? []}
          staff={staff ?? []}
          onCreated={() => {
            setShowCreate(false)
            queryClient.invalidateQueries({ queryKey: ['shifts', currentVenueId, resolvedWeekStart] })
          }}
        />
      )}

      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} onRetry={() => refetch()} />}

      {days.map((day) => {
        const dayStr = format(day, 'yyyy-MM-dd')
        const dayShifts = (shifts ?? []).filter((s) => format(new Date(s.start_at), 'yyyy-MM-dd') === dayStr)
        return (
          <Card key={dayStr}>
            <SectionHeading>{format(day, 'EEEE d MMM')}</SectionHeading>
            {dayShifts.length === 0 ? (
              <p className="text-sm text-[var(--color-text-muted)] py-2">No shifts</p>
            ) : (
              <div className="space-y-2">
                {dayShifts.map((shift) => (
                  <Link
                    key={shift.id}
                    to={`/roster/shifts/${shift.id}`}
                    className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-0"
                  >
                    <div>
                      <p className="font-medium">{staffById.get(shift.staff_id)?.name ?? 'Staff'}</p>
                      <p className="text-sm text-[var(--color-text-muted)]">
                        {stationsById.get(shift.station_id)?.name ?? 'Station'} · {format(new Date(shift.start_at), 'h:mma')}–{format(new Date(shift.end_at), 'h:mma')}
                      </p>
                    </div>
                    <Badge tone={shiftBadgeTone(shift.status)}>{shift.status}</Badge>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

function CreateShiftForm({
  venueId,
  stations,
  staff,
  onCreated,
}: {
  venueId: string
  stations: { id: string; name: string }[]
  staff: { id: string; name: string }[]
  onCreated: () => void
}) {
  const [stationId, setStationId] = useState('')
  const [staffId, setStaffId] = useState('')
  const [startAt, setStartAt] = useState('')
  const [endAt, setEndAt] = useState('')

  // See OrdersPage's AddLineForm for why this can't be a plain useState
  // default: if this form mounts before stations/staff have loaded, the
  // state would stay '' even after the lists arrive, while the Select
  // visually showed the first option — a silent mismatch that fails
  // validation on submit.
  const effectiveStationId = stationId || stations[0]?.id || ''
  const effectiveStaffId = staffId || staff[0]?.id || ''

  const create = useMutation({
    mutationFn: () =>
      api.roster.createShift(venueId, {
        station_id: effectiveStationId,
        staff_id: effectiveStaffId,
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
      }),
    onSuccess: onCreated,
  })

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    create.mutate()
  }

  if (stations.length === 0 || staff.length === 0) {
    return <EmptyState title="Add a station and a staff member first" hint="Set these up under More → Staffing." />
  }

  return (
    <Card>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Station">
          <Select value={effectiveStationId} onChange={(e) => setStationId(e.target.value)}>
            {stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field label="Staff">
          <Select value={effectiveStaffId} onChange={(e) => setStaffId(e.target.value)}>
            {staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field label="Start">
          <Input type="datetime-local" required value={startAt} onChange={(e) => setStartAt(e.target.value)} />
        </Field>
        <Field label="End">
          <Input type="datetime-local" required value={endAt} onChange={(e) => setEndAt(e.target.value)} />
        </Field>
        {create.isError && <ErrorBlock error={create.error} />}
        <Button type="submit" fullWidth disabled={create.isPending}>{create.isPending ? 'Saving…' : 'Create shift'}</Button>
      </form>
    </Card>
  )
}
