// The signed-link view a line-staff member with no login opens from their
// shift notification — purpose-scoped to exactly this one Shift (locked
// AC: "roster view/respond/check-in only, nothing else"). No Shell, no
// auth — this route works entirely off the URL token.

import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { Badge, Button, Card } from '../../components/primitives'
import { ErrorBlock, LoadingBlock } from '../../components/feedback'
import { format } from 'date-fns'

export function StaffLinkPage() {
  const { token = '' } = useParams()
  const queryClient = useQueryClient()
  const [checkedIn, setCheckedIn] = useState(false)

  const { data: view, isLoading, error } = useQuery({
    queryKey: ['staff-link', token],
    queryFn: () => api.roster.viewStaffLink(token),
  })

  const respond = useMutation({
    mutationFn: (response: 'confirmed' | 'declined') => api.roster.respondViaLink(token, response),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['staff-link', token] }),
  })

  const checkIn = useMutation({
    mutationFn: () => api.attendance.checkInViaLink(token, 'present'),
    onSuccess: () => setCheckedIn(true),
  })

  return (
    <div className="min-h-dvh flex items-center justify-center px-6 bg-[var(--color-surface)]">
      <div className="w-full max-w-sm">
        <h1 className="text-center text-xl font-semibold mb-4">
          <span className="text-[var(--color-accent)]">Mise</span> — Your shift
        </h1>

        {isLoading && <LoadingBlock />}
        {error && <ErrorBlock error={error} />}

        {view && (
          <Card className="space-y-4">
            <div>
              <p className="text-lg font-medium">
                {format(new Date(view.start_at), 'EEEE d MMM')}
              </p>
              <p className="text-[var(--color-text-muted)]">
                {format(new Date(view.start_at), 'h:mma')} – {format(new Date(view.end_at), 'h:mma')}
              </p>
            </div>

            <div className="flex gap-2 flex-wrap">
              <Badge tone={view.shift_status === 'cancelled' ? 'danger' : 'neutral'}>Shift {view.shift_status}</Badge>
              <Badge tone={view.response_status === 'confirmed' ? 'success' : view.response_status === 'declined' ? 'danger' : 'warning'}>
                {view.response_status}
              </Badge>
            </div>

            {view.shift_status !== 'cancelled' && view.response_status === 'pending' && (
              <div className="flex gap-2">
                <Button fullWidth onClick={() => respond.mutate('confirmed')} disabled={respond.isPending}>
                  Confirm
                </Button>
                <Button fullWidth variant="secondary" onClick={() => respond.mutate('declined')} disabled={respond.isPending}>
                  Decline
                </Button>
              </div>
            )}

            {view.shift_status !== 'cancelled' && (
              <Button fullWidth variant="secondary" onClick={() => checkIn.mutate()} disabled={checkIn.isPending || checkedIn}>
                {checkedIn ? '✓ Checked in' : "I'm here — check in"}
              </Button>
            )}

            {respond.isError && <ErrorBlock error={respond.error} />}
            {checkIn.isError && <ErrorBlock error={checkIn.error} />}
          </Card>
        )}
      </div>
    </div>
  )
}
