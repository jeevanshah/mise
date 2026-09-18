// Epic 6 — Quick Capture. A head chef speaks/types a quick note ("we're
// out of salmon", "3 pans down for repair") and the backend's parser
// proposes a match; this screen is where that proposal gets confirmed
// into a real record (an order line, an eighty-six event, an equipment
// issue) or rejected. Nothing here mutates catalog/order/menu state
// until the chef explicitly confirms it — a capture starts life inert.

import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Badge, Button, Card, Field, Input, Select, Textarea } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import type { CaptureOut, CaptureType, EquipmentIssuePriority, MenuAvailabilityStatus } from '../../api/types'

function captureTone(status: CaptureOut['status']) {
  if (status === 'confirmed') return 'success' as const
  if (status === 'rejected') return 'danger' as const
  return 'warning' as const
}

function typeLabel(type: CaptureType) {
  if (type === 'restock') return 'Restock'
  if (type === 'eighty_six') return '86'
  if (type === 'equipment_issue') return 'Equipment issue'
  return 'Unparsed'
}

export function CapturePage() {
  const { currentVenueId } = useAuth()
  const queryClient = useQueryClient()
  const [rawText, setRawText] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: captures, isLoading, error, refetch } = useQuery({
    queryKey: ['captures', currentVenueId],
    queryFn: () => api.capture.list(currentVenueId!),
    enabled: !!currentVenueId,
  })

  const create = useMutation({
    mutationFn: () => api.capture.create(currentVenueId!, { raw_text: rawText }),
    onSuccess: (created) => {
      setRawText('')
      queryClient.invalidateQueries({ queryKey: ['captures', currentVenueId] })
      setExpandedId(created.id)
    },
  })

  const sorted = useMemo(() => {
    const rank = (c: CaptureOut) => (c.status === 'proposed' ? 0 : 1)
    return [...(captures ?? [])].sort((a, b) => rank(a) - rank(b))
  }, [captures])

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Quick capture" />

      <Card>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            create.mutate()
          }}
          className="space-y-2"
        >
          <Textarea
            placeholder="e.g. we're out of salmon, or 3 pans down for repair"
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            required
          />
          <Button type="submit" fullWidth disabled={create.isPending}>{create.isPending ? 'Capturing…' : 'Capture'}</Button>
        </form>
        {create.isError && <ErrorBlock error={create.error} />}
      </Card>

      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} onRetry={() => refetch()} />}
      {sorted.length === 0 && <EmptyState title="No captures yet" />}

      {sorted.map((capture) => (
        <Card key={capture.id}>
          <button className="w-full text-left" onClick={() => setExpandedId(expandedId === capture.id ? null : capture.id)}>
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium truncate">{capture.raw_text}</p>
              <Badge tone={captureTone(capture.status)}>{capture.status}</Badge>
            </div>
            <p className="text-sm text-[var(--color-text-muted)] mt-1">
              {typeLabel(capture.capture_type)}
              {capture.extracted_quantity ? ` · ${capture.extracted_quantity} ${capture.extracted_unit ?? ''}` : ''}
            </p>
          </button>
          {expandedId === capture.id && capture.status === 'proposed' && (
            <CaptureResolveForm
              venueId={currentVenueId!}
              capture={capture}
              onDone={() => {
                setExpandedId(null)
                queryClient.invalidateQueries({ queryKey: ['captures', currentVenueId] })
              }}
            />
          )}
        </Card>
      ))}
    </div>
  )
}

function CaptureResolveForm({ venueId, capture, onDone }: { venueId: string; capture: CaptureOut; onDone: () => void }) {
  const [entityId, setEntityId] = useState(capture.matched_entity_id ?? '')
  const [quantity, setQuantity] = useState(capture.extracted_quantity ?? '')
  const [unit, setUnit] = useState(capture.extracted_unit ?? '')
  const [supplierId, setSupplierId] = useState('')
  const [requiredDeliveryDate, setRequiredDeliveryDate] = useState('')
  const [availabilityStatus, setAvailabilityStatus] = useState<MenuAvailabilityStatus>('unavailable')
  const [quantityRemaining, setQuantityRemaining] = useState('')
  const [priority, setPriority] = useState<EquipmentIssuePriority>('medium')
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)

  const { data: ingredients } = useQuery({
    queryKey: ['ingredients', venueId],
    queryFn: () => api.catalog.listIngredients(venueId),
    enabled: capture.capture_type === 'restock',
  })
  const { data: suppliers } = useQuery({
    queryKey: ['suppliers', venueId],
    queryFn: () => api.catalog.listSuppliers(venueId),
    enabled: capture.capture_type === 'restock',
  })
  const { data: menuItems } = useQuery({
    queryKey: ['menu-items', venueId],
    queryFn: () => api.catalog.listMenuItems(venueId),
    enabled: capture.capture_type === 'eighty_six',
  })
  const { data: equipmentItems } = useQuery({
    queryKey: ['equipment-items', venueId],
    queryFn: () => api.catalog.listEquipmentItems(venueId),
    enabled: capture.capture_type === 'equipment_issue',
  })

  const confirm = useMutation({
    mutationFn: () => {
      if (capture.capture_type === 'restock') {
        return api.capture.confirm(venueId, capture.id, {
          entity_type: 'ingredient',
          entity_id: entityId,
          quantity,
          unit: unit || undefined,
          supplier_id: supplierId || undefined,
          required_delivery_date: requiredDeliveryDate || undefined,
        })
      }
      if (capture.capture_type === 'eighty_six') {
        return api.capture.confirm(venueId, capture.id, {
          entity_type: 'menu_item',
          entity_id: entityId,
          availability_status: availabilityStatus,
          quantity_remaining: quantityRemaining || undefined,
        })
      }
      if (capture.capture_type === 'equipment_issue') {
        return api.capture.confirm(venueId, capture.id, {
          entity_type: 'equipment_item',
          entity_id: entityId,
          priority,
        })
      }
      return api.capture.confirm(venueId, capture.id, {})
    },
    onSuccess: onDone,
  })

  const reject = useMutation({
    mutationFn: () => api.capture.reject(venueId, capture.id, rejectReason || undefined),
    onSuccess: onDone,
  })

  const needsEntity = capture.capture_type !== 'unparsed'

  return (
    <div className="mt-3 pt-3 border-t border-[var(--color-border)] space-y-3">
      {capture.capture_type === 'restock' && (
        <>
          <Field label="Ingredient">
            <Select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
              <option value="">Select…</option>
              {(ingredients ?? []).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </Select>
          </Field>
          <Field label="Supplier">
            <Select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Select…</option>
              {(suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <div className="flex gap-2">
            <Input placeholder="Qty" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            <Input placeholder="Unit" value={unit} onChange={(e) => setUnit(e.target.value)} />
          </div>
          <Field label="Required delivery date (optional)">
            <Input type="date" value={requiredDeliveryDate} onChange={(e) => setRequiredDeliveryDate(e.target.value)} />
          </Field>
        </>
      )}

      {capture.capture_type === 'eighty_six' && (
        <>
          <Field label="Menu item">
            <Select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
              <option value="">Select…</option>
              {(menuItems ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </Select>
          </Field>
          <Field label="Availability">
            <Select value={availabilityStatus} onChange={(e) => setAvailabilityStatus(e.target.value as MenuAvailabilityStatus)}>
              <option value="unavailable">Unavailable (86'd)</option>
              <option value="low">Low</option>
              <option value="available">Available</option>
            </Select>
          </Field>
          <Field label="Quantity remaining (optional)">
            <Input value={quantityRemaining} onChange={(e) => setQuantityRemaining(e.target.value)} />
          </Field>
        </>
      )}

      {capture.capture_type === 'equipment_issue' && (
        <>
          <Field label="Equipment">
            <Select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
              <option value="">Select…</option>
              {(equipmentItems ?? []).map((eq) => <option key={eq.id} value={eq.id}>{eq.name}</option>)}
            </Select>
          </Field>
          <Field label="Priority">
            <Select value={priority} onChange={(e) => setPriority(e.target.value as EquipmentIssuePriority)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </Select>
          </Field>
        </>
      )}

      {capture.capture_type === 'unparsed' && (
        <p className="text-sm text-[var(--color-text-muted)]">Couldn't be matched automatically — confirm as-is or reject.</p>
      )}

      {confirm.isError && <ErrorBlock error={confirm.error} />}
      <div className="flex gap-2">
        <Button fullWidth onClick={() => confirm.mutate()} disabled={confirm.isPending || (needsEntity && !entityId)}>
          {confirm.isPending ? 'Confirming…' : 'Confirm'}
        </Button>
        <Button fullWidth variant="danger" onClick={() => setShowReject((v) => !v)}>Reject</Button>
      </div>

      {showReject && (
        <form
          className="flex gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            reject.mutate()
          }}
        >
          <Input placeholder="Reason (optional)" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} className="flex-1" />
          <Button type="submit" variant="secondary" disabled={reject.isPending}>Confirm reject</Button>
        </form>
      )}
      {reject.isError && <ErrorBlock error={reject.error} />}
    </div>
  )
}
