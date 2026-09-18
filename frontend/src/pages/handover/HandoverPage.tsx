// Epic 7 — Handover. Closing a service day snapshots everything a chef
// needs to know for tomorrow's early crew into one Handover; items that
// don't matter can be excluded (never deleted — a handover keeps a full
// record) via the "included" toggle.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api, ApiError } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { useCurrentServiceDay } from '../../hooks/useCurrentServiceDay'
import { Badge, Button, Card, Input, Textarea, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import type { HandoverItemType } from '../../api/types'

const ITEM_TYPE_LABELS: Record<HandoverItemType, string> = {
  prep_task: 'Prep task',
  capture: 'Capture',
  equipment_issue: 'Equipment issue',
  purchase_order: 'Purchase order',
  menu_availability_event: 'Menu availability',
  delivery_issue: 'Delivery issue',
}

export function HandoverPage() {
  const { businessDate: routeDate } = useParams()
  const { currentVenueId } = useAuth()
  const { data: currentDay } = useCurrentServiceDay()
  const businessDate = routeDate ?? currentDay?.business_date ?? null
  const queryClient = useQueryClient()
  const [note, setNote] = useState('')
  const [showReopen, setShowReopen] = useState(false)
  const [reopenReason, setReopenReason] = useState('')

  const { data: handover, isLoading, error } = useQuery({
    queryKey: ['handover', currentVenueId, businessDate],
    queryFn: () => api.handover.get(currentVenueId!, businessDate!),
    enabled: !!currentVenueId && !!businessDate,
    retry: false,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['handover', currentVenueId, businessDate] })

  const close = useMutation({
    mutationFn: () => api.handover.close(currentVenueId!, businessDate!, note || undefined),
    onSuccess: invalidate,
  })
  const reopen = useMutation({
    mutationFn: () => api.handover.reopen(currentVenueId!, businessDate!, reopenReason),
    onSuccess: () => {
      setShowReopen(false)
      invalidate()
    },
  })
  const toggleItem = useMutation({
    mutationFn: ({ itemId, included }: { itemId: string; included: boolean }) =>
      api.handover.setItemIncluded(currentVenueId!, itemId, included),
    onSuccess: invalidate,
  })

  async function downloadPdf() {
    const blob = await api.handover.downloadPdf(currentVenueId!, businessDate!)
    window.open(URL.createObjectURL(blob), '_blank')
  }

  const notFound = error instanceof ApiError && error.status === 404

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Handover" subtitle={businessDate ? format(new Date(businessDate), 'EEEE d MMM') : undefined} />

      {isLoading && <LoadingBlock />}
      {error && !notFound && <ErrorBlock error={error} />}

      {notFound && (
        <>
          <RoleGate allow={MANAGEMENT_ROLES}>
            <Card className="space-y-3">
              <SectionHeading>Close service day</SectionHeading>
              <Textarea placeholder="Handover note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              {close.isError && <ErrorBlock error={close.error} />}
              <Button fullWidth onClick={() => close.mutate()} disabled={close.isPending}>
                {close.isPending ? 'Closing…' : 'Close & create handover'}
              </Button>
            </Card>
          </RoleGate>
          <EmptyState title="No handover for this day yet" />
        </>
      )}

      {handover && (
        <>
          <Card className="space-y-1">
            <p className="text-sm text-[var(--color-text-muted)]">
              Closed {format(new Date(handover.closed_at), "d MMM, h:mma")} · took {Math.round(handover.time_to_close_seconds / 60)} min
            </p>
            {handover.note && <p>{handover.note}</p>}
          </Card>

          <Card>
            <SectionHeading>Items</SectionHeading>
            <div className="space-y-2">
              {handover.items.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-2 py-1.5 border-b border-[var(--color-border)] last:border-0">
                  <Badge tone="neutral">{ITEM_TYPE_LABELS[item.item_type]}</Badge>
                  <RoleGate allow={MANAGEMENT_ROLES}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={item.included}
                        onChange={(e) => toggleItem.mutate({ itemId: item.id, included: e.target.checked })}
                      />
                      Include
                    </label>
                  </RoleGate>
                </div>
              ))}
            </div>
          </Card>

          <div className="flex gap-2">
            <Button fullWidth variant="secondary" onClick={downloadPdf}>Download PDF</Button>
            <RoleGate allow={MANAGEMENT_ROLES}>
              <Button fullWidth variant="secondary" onClick={() => setShowReopen((v) => !v)}>Reopen</Button>
            </RoleGate>
          </div>

          {showReopen && (
            <Card>
              <form
                className="flex gap-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault()
                  reopen.mutate()
                }}
              >
                <Input
                  placeholder="Reason for reopening"
                  value={reopenReason}
                  onChange={(e) => setReopenReason(e.target.value)}
                  className="flex-1"
                  required
                />
                <Button type="submit" disabled={reopen.isPending}>Reopen</Button>
              </form>
              {reopen.isError && <ErrorBlock error={reopen.error} />}
            </Card>
          )}
        </>
      )}
    </div>
  )
}
