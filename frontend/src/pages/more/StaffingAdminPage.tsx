// Epic 1 admin — Staffing: stations, staff, skills, and per-station
// coverage rules (the minimums Chef Brief's coverage-gap warnings are
// computed against). MANAGEMENT_ROLES only — gated by the route's parent
// (More hub only links here for management roles), not re-checked here.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Field, Input, Select } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import type { StationOut } from '../../api/types'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function StaffingAdminPage() {
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!
  const queryClient = useQueryClient()
  const [newStation, setNewStation] = useState('')
  const [newStaffName, setNewStaffName] = useState('')
  const [newStaffEmail, setNewStaffEmail] = useState('')
  const [expandedStation, setExpandedStation] = useState<string | null>(null)
  const [expandedStaff, setExpandedStaff] = useState<string | null>(null)

  const { data: stations, isLoading: stationsLoading, error: stationsError } = useQuery({
    queryKey: ['stations', venueId],
    queryFn: () => api.staffing.listStations(venueId),
  })
  const { data: staff, isLoading: staffLoading, error: staffError } = useQuery({
    queryKey: ['staff', venueId],
    queryFn: () => api.staffing.listStaff(venueId),
  })

  const createStation = useMutation({
    mutationFn: () => api.staffing.createStation(venueId, { name: newStation }),
    onSuccess: () => {
      setNewStation('')
      queryClient.invalidateQueries({ queryKey: ['stations', venueId] })
    },
  })
  const createStaff = useMutation({
    mutationFn: () => api.staffing.createStaff(venueId, { name: newStaffName, contact_email: newStaffEmail || undefined }),
    onSuccess: () => {
      setNewStaffName('')
      setNewStaffEmail('')
      queryClient.invalidateQueries({ queryKey: ['staff', venueId] })
    },
  })

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Staffing" />

      <Card>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-text-muted)] mb-2">Stations</p>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            createStation.mutate()
          }}
          className="flex gap-2 mb-3"
        >
          <Input placeholder="New station" value={newStation} onChange={(e) => setNewStation(e.target.value)} required />
          <Button type="submit" disabled={createStation.isPending}>Add</Button>
        </form>
        {createStation.isError && <ErrorBlock error={createStation.error} />}
        {stationsLoading && <LoadingBlock />}
        {stationsError && <ErrorBlock error={stationsError} />}
        {stations && stations.length === 0 && <EmptyState title="No stations yet" />}
        <div className="space-y-2">
          {(stations ?? []).map((station) => (
            <div key={station.id} className="border-b border-[var(--color-border)] last:border-0 pb-2">
              <button
                className="w-full text-left font-medium py-1"
                onClick={() => setExpandedStation(expandedStation === station.id ? null : station.id)}
              >
                {station.name}
              </button>
              {expandedStation === station.id && <CoverageRules venueId={venueId} stationId={station.id} />}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-text-muted)] mb-2">Staff</p>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            createStaff.mutate()
          }}
          className="space-y-2 mb-3"
        >
          <Input placeholder="Name" value={newStaffName} onChange={(e) => setNewStaffName(e.target.value)} required />
          <Input placeholder="Contact email (optional)" value={newStaffEmail} onChange={(e) => setNewStaffEmail(e.target.value)} />
          <Button type="submit" fullWidth disabled={createStaff.isPending}>Add staff</Button>
        </form>
        {createStaff.isError && <ErrorBlock error={createStaff.error} />}
        {staffLoading && <LoadingBlock />}
        {staffError && <ErrorBlock error={staffError} />}
        {staff && staff.length === 0 && <EmptyState title="No staff yet" />}
        <div className="space-y-2">
          {(staff ?? []).map((person) => (
            <div key={person.id} className="border-b border-[var(--color-border)] last:border-0 pb-2">
              <button
                className="w-full text-left font-medium py-1"
                onClick={() => setExpandedStaff(expandedStaff === person.id ? null : person.id)}
              >
                {person.name}
              </button>
              {expandedStaff === person.id && <StaffSkills venueId={venueId} staffId={person.id} stations={stations ?? []} />}
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function CoverageRules({ venueId, stationId }: { venueId: string; stationId: string }) {
  const queryClient = useQueryClient()
  const [dayOfWeek, setDayOfWeek] = useState(0)
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [minimumStaff, setMinimumStaff] = useState('1')

  const { data: rules } = useQuery({
    queryKey: ['coverage-rules', venueId, stationId],
    queryFn: () => api.staffing.listCoverageRules(venueId, stationId),
  })

  const createRule = useMutation({
    mutationFn: () =>
      api.staffing.createCoverageRule(venueId, stationId, {
        day_of_week: dayOfWeek,
        window_start: windowStart,
        window_end: windowEnd,
        minimum_staff: Number(minimumStaff) || 1,
      }),
    onSuccess: () => {
      setWindowStart('')
      setWindowEnd('')
      queryClient.invalidateQueries({ queryKey: ['coverage-rules', venueId, stationId] })
    },
  })

  return (
    <div className="mt-2 pl-2 space-y-2">
      {(rules ?? []).map((rule) => (
        <p key={rule.id} className="text-sm text-[var(--color-text-muted)]">
          {DAYS[rule.day_of_week]} {rule.window_start}–{rule.window_end} · min {rule.minimum_staff}
        </p>
      ))}
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          createRule.mutate()
        }}
        className="space-y-2"
      >
        <Field label="Day">
          <Select value={dayOfWeek} onChange={(e) => setDayOfWeek(Number(e.target.value))}>
            {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </Select>
        </Field>
        <div className="flex gap-2">
          <Input type="time" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} required />
          <Input type="time" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} required />
        </div>
        <Input placeholder="Minimum staff" value={minimumStaff} onChange={(e) => setMinimumStaff(e.target.value)} />
        {createRule.isError && <ErrorBlock error={createRule.error} />}
        <Button type="submit" fullWidth disabled={createRule.isPending}>Add rule</Button>
      </form>
    </div>
  )
}

function StaffSkills({ venueId, staffId, stations }: { venueId: string; staffId: string; stations: StationOut[] }) {
  const queryClient = useQueryClient()
  const [stationId, setStationId] = useState('')

  // See OrdersPage's AddLineForm for why a plain useState(stations[0]?.id)
  // default is unsafe here: this panel can expand before the stations
  // query has resolved, and a stale '' would then silently survive even
  // after stations arrive.
  const effectiveStationId = stationId || stations[0]?.id || ''

  const { data: detail } = useQuery({
    queryKey: ['staff-detail', venueId, staffId],
    queryFn: () => api.staffing.getStaff(venueId, staffId),
  })

  const addSkill = useMutation({
    mutationFn: () => api.staffing.addStaffSkill(venueId, staffId, { station_id: effectiveStationId, trained: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['staff-detail', venueId, staffId] }),
  })

  const stationsById = new Map(stations.map((s) => [s.id, s]))

  return (
    <div className="mt-2 pl-2 space-y-2">
      {(detail?.skills ?? []).map((skill) => (
        <p key={skill.id} className="text-sm text-[var(--color-text-muted)]">
          {stationsById.get(skill.station_id)?.name ?? 'Station'}{skill.trained ? ' · trained' : ''}
        </p>
      ))}
      {stations.length > 0 && (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            addSkill.mutate()
          }}
          className="flex gap-2"
        >
          <Select value={effectiveStationId} onChange={(e) => setStationId(e.target.value)} className="flex-1">
            {stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
          <Button type="submit" disabled={addSkill.isPending}>Add skill</Button>
        </form>
      )}
      {addSkill.isError && <ErrorBlock error={addSkill.error} />}
    </div>
  )
}
