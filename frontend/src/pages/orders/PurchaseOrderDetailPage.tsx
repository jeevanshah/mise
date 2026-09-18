// Epic 5 — a single purchase order: its lines, send state, delivery
// status, and any delivery issues logged against it.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES, useHasRole } from '../../auth/AuthContext'
import { Badge, Button, Card, Field, Input, Select, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import type { DeliveryIssueType } from '../../api/types'

const ISSUE_TYPES: DeliveryIssueType[] = ['short_delivery', 'damaged', 'wrong_item', 'late', 'quality', 'other']

export function PurchaseOrderDetailPage() {
  const { purchaseOrderId = '' } = useParams()
  const { currentVenueId } = useAuth()
  const queryClient = useQueryClient()
  const canEditLines = useHasRole(MANAGEMENT_ROLES)
  const [editingLineId, setEditingLineId] = useState<string | null>(null)
  const [editQuantity, setEditQuantity] = useState('')
  const [showIssueForm, setShowIssueForm] = useState(false)
  const [issueType, setIssueType] = useState<DeliveryIssueType>('short_delivery')
  const [issueEvidence, setIssueEvidence] = useState('')

  const { data: po, isLoading, error } = useQuery({
    queryKey: ['purchase-order', currentVenueId, purchaseOrderId],
    queryFn: () => api.purchaseOrders.get(currentVenueId!, purchaseOrderId),
    enabled: !!currentVenueId,
  })
  const { data: suppliers } = useQuery({
    queryKey: ['suppliers', currentVenueId],
    queryFn: () => api.catalog.listSuppliers(currentVenueId!),
    enabled: !!currentVenueId,
  })
  const { data: ingredients } = useQuery({
    queryKey: ['ingredients', currentVenueId],
    queryFn: () => api.catalog.listIngredients(currentVenueId!),
    enabled: !!currentVenueId,
  })
  const ingredientsById = new Map((ingredients ?? []).map((i) => [i.id, i]))
  const supplier = (suppliers ?? []).find((s) => s.id === po?.supplier_id)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['purchase-order', currentVenueId, purchaseOrderId] })

  const send = useMutation({
    mutationFn: () => api.purchaseOrders.send(currentVenueId!, purchaseOrderId),
    onSuccess: invalidate,
  })
  const updateLine = useMutation({
    mutationFn: ({ lineId, quantity }: { lineId: string; quantity: string }) =>
      api.purchaseOrders.updateLineQuantity(currentVenueId!, purchaseOrderId, lineId, quantity),
    onSuccess: () => {
      setEditingLineId(null)
      invalidate()
    },
  })
  const markDelivery = useMutation({
    mutationFn: (partial: boolean) => api.purchaseOrders.markDelivery(currentVenueId!, purchaseOrderId, { partial }),
    onSuccess: invalidate,
  })
  const logIssue = useMutation({
    mutationFn: () =>
      api.purchaseOrders.logDeliveryIssue(currentVenueId!, purchaseOrderId, { issue_type: issueType, evidence: issueEvidence || undefined }),
    onSuccess: () => {
      setShowIssueForm(false)
      setIssueEvidence('')
      invalidate()
    },
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorBlock error={error} />
  if (!po) return null

  return (
    <div className="space-y-4 pb-4">
      <PageHeader
        title={supplier?.name ?? 'Order'}
        subtitle={po.required_delivery_date ? `Due ${format(new Date(po.required_delivery_date), 'd MMM yyyy')}` : undefined}
      />

      <Card className="flex flex-wrap items-center gap-2">
        <Badge tone={po.status === 'sent' ? 'success' : po.status === 'send_failed' ? 'danger' : po.status === 'sending' ? 'info' : 'neutral'}>
          {po.status.replace('_', ' ')}
        </Badge>
        <Badge tone={po.delivery_status === 'received' ? 'success' : po.delivery_status === 'partially_received' ? 'warning' : 'neutral'}>
          {po.delivery_status.replace('_', ' ')}
        </Badge>
        {po.last_error && <span className="text-sm text-red-300">{po.last_error}</span>}
      </Card>

      <Card>
        <SectionHeading>Lines</SectionHeading>
        <div className="space-y-2">
          {po.lines.map((line) => (
            <div key={line.id} className="flex items-center justify-between gap-2 py-2 border-b border-[var(--color-border)] last:border-0">
              <div className="min-w-0">
                <p className="font-medium truncate">{ingredientsById.get(line.ingredient_id)?.name ?? 'Ingredient'}</p>
                {line.delivery_note && <p className="text-sm text-[var(--color-text-muted)]">{line.delivery_note}</p>}
              </div>
              {canEditLines && editingLineId === line.id ? (
                <form
                  className="flex gap-1"
                  onSubmit={(e: FormEvent) => {
                    e.preventDefault()
                    updateLine.mutate({ lineId: line.id, quantity: editQuantity })
                  }}
                >
                  <Input className="w-20" value={editQuantity} onChange={(e) => setEditQuantity(e.target.value)} autoFocus />
                  <Button type="submit" disabled={updateLine.isPending}>Save</Button>
                </form>
              ) : (
                <button
                  className="text-sm text-[var(--color-text-muted)] disabled:opacity-50"
                  disabled={!canEditLines}
                  onClick={() => {
                    setEditingLineId(line.id)
                    setEditQuantity(line.quantity)
                  }}
                >
                  {line.quantity} {line.unit}
                </button>
              )}
            </div>
          ))}
        </div>
        {updateLine.isError && <ErrorBlock error={updateLine.error} />}
      </Card>

      <RoleGate allow={MANAGEMENT_ROLES}>
        {po.status === 'draft' && (
          <Button fullWidth onClick={() => send.mutate()} disabled={send.isPending}>
            {send.isPending ? 'Sending…' : 'Send order'}
          </Button>
        )}
        {send.isError && <ErrorBlock error={send.error} />}

        {po.status === 'sent' && po.delivery_status !== 'received' && (
          <div className="flex gap-2">
            <Button fullWidth variant="secondary" onClick={() => markDelivery.mutate(true)} disabled={markDelivery.isPending}>
              Mark partial delivery
            </Button>
            <Button fullWidth onClick={() => markDelivery.mutate(false)} disabled={markDelivery.isPending}>
              Mark delivered
            </Button>
          </div>
        )}
        {markDelivery.isError && <ErrorBlock error={markDelivery.error} />}
      </RoleGate>

      <Card>
        <SectionHeading
          action={
            <button className="text-sm text-[var(--color-accent)]" onClick={() => setShowIssueForm((v) => !v)}>
              {showIssueForm ? 'Cancel' : '+ Issue'}
            </button>
          }
        >
          Delivery issues
        </SectionHeading>
        {po.delivery_issues.length === 0 && !showIssueForm && <p className="text-sm text-[var(--color-text-muted)]">None logged</p>}
        <div className="space-y-2">
          {po.delivery_issues.map((issue) => (
            <div key={issue.id} className="text-sm border-b border-[var(--color-border)] last:border-0 py-1.5">
              <Badge tone="warning">{issue.issue_type.replace('_', ' ')}</Badge>
              {issue.evidence && <p className="text-[var(--color-text-muted)] mt-1">{issue.evidence}</p>}
            </div>
          ))}
        </div>
        {showIssueForm && (
          <form
            className="space-y-2 mt-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              logIssue.mutate()
            }}
          >
            <Field label="Issue type">
              <Select value={issueType} onChange={(e) => setIssueType(e.target.value as DeliveryIssueType)}>
                {ISSUE_TYPES.map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </Select>
            </Field>
            <Field label="Evidence / notes (optional)">
              <Input value={issueEvidence} onChange={(e) => setIssueEvidence(e.target.value)} />
            </Field>
            {logIssue.isError && <ErrorBlock error={logIssue.error} />}
            <Button type="submit" fullWidth disabled={logIssue.isPending}>Log issue</Button>
          </form>
        )}
      </Card>
    </div>
  )
}
