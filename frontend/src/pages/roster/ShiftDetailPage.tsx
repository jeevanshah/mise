// Epic 2 (publish/cancel) + Epic 3 (attendance) — a shift's detail lives
// in one place since attendance is always logged against a specific
// Shift.

import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { Badge, Button, Card, Select, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, PageHeader, EmptyState } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import type { AttendanceStatus } from '../../api/types'

const ATTENDANCE_OPTIONS: AttendanceStatus[] = ['present', 'late', 'absent', 'sick']

export function ShiftDetailPage() {
  const { shiftId = '' } = useParams()
  const { currentVenueId } = useAuth()
  const queryClient = useQueryClient()
  const [attendanceStatus, setAttendanceStatus] = useState<AttendanceStatus>('present')

  const { data: shift, isLoading, error } = useQuery({
    queryKey: ['shift', currentVenueId, shiftId],
    queryFn: () => api.roster.getShift(currentVenueId!, shiftId),
    enabled: !!currentVenueId,
  })

  const { data: events } = useQuery({
    queryKey: ['attendance-events', currentVenueId, shiftId],
    queryFn: () => api.attendance.listEvents(currentVenueId!, shiftId),
    enabled: !!currentVenueId,
  })

  const publish = useMutation({
    mutationFn: () => api.roster.publishShift(currentVenueId!, shiftId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shift', currentVenueId, shiftId] }),
  })
  const cancel = useMutation({
    mutationFn: () => api.roster.cancelShift(currentVenueId!, shiftId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shift', currentVenueId, shiftId] }),
  })
  const logAttendance = useMutation({
    mutationFn: () => api.attendance.logEvent(currentVenueId!, shiftId, { status: attendanceStatus }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attendance-events', currentVenueId, shiftId] })
      queryClient.invalidateQueries({ queryKey: ['chef-brief', currentVenueId] })
    },
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorBlock error={error} />
  if (!shift) return null

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title={format(new Date(shift.start_at), 'EEEE d MMM')} subtitle={`${format(new Date(shift.start_at), 'h:mma')}–${format(new Date(shift.end_at), 'h:mma')}`} />

      <Card className="flex items-center gap-2 flex-wrap">
        <Badge tone={shift.status === 'published' ? 'success' : shift.status === 'cancelled' ? 'danger' : 'neutral'}>{shift.status}</Badge>
        {shift.response && (
          <Badge tone={shift.response.status === 'confirmed' ? 'success' : shift.response.status === 'declined' ? 'danger' : 'warning'}>
            staff {shift.response.status}
          </Badge>
        )}
      </Card>

      <RoleGate allow={MANAGEMENT_ROLES}>
        <div className="flex gap-2">
          {shift.status === 'draft' && (
            <Button fullWidth onClick={() => publish.mutate()} disabled={publish.isPending}>
              {publish.isPending ? 'Publishing…' : 'Publish'}
            </Button>
          )}
          {shift.status !== 'cancelled' && (
            <Button fullWidth variant="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              {cancel.isPending ? 'Cancelling…' : 'Cancel shift'}
            </Button>
          )}
        </div>
        {publish.isError && <ErrorBlock error={publish.error} />}
        {cancel.isError && <ErrorBlock error={cancel.error} />}
      </RoleGate>

      <Card>
        <SectionHeading>Log attendance</SectionHeading>
        <div className="flex gap-2">
          <Select value={attendanceStatus} onChange={(e) => setAttendanceStatus(e.target.value as AttendanceStatus)} className="flex-1">
            {ATTENDANCE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Button onClick={() => logAttendance.mutate()} disabled={logAttendance.isPending}>Log</Button>
        </div>
        {logAttendance.isError && <ErrorBlock error={logAttendance.error} />}
      </Card>

      <Card>
        <SectionHeading>Attendance history</SectionHeading>
        {!events || events.length === 0 ? (
          <EmptyState title="No events logged yet" />
        ) : (
          <div className="space-y-2">
            {events.map((e) => (
              <div key={e.id} className="flex items-center justify-between text-sm border-b border-[var(--color-border)] last:border-0 py-1.5">
                <Badge tone={e.status === 'present' ? 'success' : e.status === 'absent' ? 'danger' : 'warning'}>{e.status}</Badge>
                <span className="text-[var(--color-text-muted)]">{format(new Date(e.recorded_at), "d MMM, h:mma")} · {e.source}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
