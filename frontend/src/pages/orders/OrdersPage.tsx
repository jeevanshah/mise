// Epic 5 — Supplier Orders. A purchase order accumulates lines by
// supplier via "add or merge line" (locked AC: adding the same
// ingredient+supplier again merges into the existing draft rather than
// creating a duplicate order) — so this page is a list of in-flight POs
// plus a quick "add line" form that lets that merge logic do its job.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { Badge, Button, Card, Field, Input, Select } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import type { DeliveryStatus, IngredientOut, PurchaseOrderStatus, SupplierOut } from '../../api/types'

function statusTone(status: PurchaseOrderStatus) {
  if (status === 'sent') return 'success' as const
  if (status === 'send_failed') return 'danger' as const
  if (status === 'sending') return 'info' as const
  return 'neutral' as const
}

function deliveryTone(status: DeliveryStatus) {
  if (status === 'received') return 'success' as const
  if (status === 'partially_received') return 'warning' as const
  return 'neutral' as const
}

export function OrdersPage() {
  const { currentVenueId } = useAuth()
  const [showAdd, setShowAdd] = useState(false)
  const queryClient = useQueryClient()

  const { data: orders, isLoading, error, refetch } = useQuery({
    queryKey: ['purchase-orders', currentVenueId],
    queryFn: () => api.purchaseOrders.list(currentVenueId!),
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
  const suppliersById = new Map((suppliers ?? []).map((s) => [s.id, s]))

  return (
    <div className="space-y-4 pb-4">
      <PageHeader
        title="Orders"
        action={
          <RoleGate allow={MANAGEMENT_ROLES}>
            <Button onClick={() => setShowAdd((v) => !v)}>{showAdd ? 'Close' : '+ Line'}</Button>
          </RoleGate>
        }
      />

      {showAdd && (
        <AddLineForm
          venueId={currentVenueId!}
          suppliers={suppliers ?? []}
          ingredients={ingredients ?? []}
          onAdded={() => {
            setShowAdd(false)
            queryClient.invalidateQueries({ queryKey: ['purchase-orders', currentVenueId] })
          }}
        />
      )}

      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} onRetry={() => refetch()} />}
      {orders && orders.length === 0 && <EmptyState title="No orders yet" hint="Add a line to start a draft order." />}

      {(orders ?? []).map((po) => (
        <Link key={po.id} to={`/orders/${po.id}`}>
          <Card className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="font-medium">{suppliersById.get(po.supplier_id)?.name ?? 'Supplier'}</p>
              <Badge tone={statusTone(po.status)}>{po.status.replace('_', ' ')}</Badge>
            </div>
            <div className="flex items-center justify-between text-sm text-[var(--color-text-muted)]">
              <span>
                {po.lines.length} line{po.lines.length === 1 ? '' : 's'}
                {po.required_delivery_date ? ` · due ${format(new Date(po.required_delivery_date), 'd MMM')}` : ''}
              </span>
              <Badge tone={deliveryTone(po.delivery_status)}>{po.delivery_status.replace('_', ' ')}</Badge>
            </div>
          </Card>
        </Link>
      ))}
    </div>
  )
}

function AddLineForm({
  venueId,
  suppliers,
  ingredients,
  onAdded,
}: {
  venueId: string
  suppliers: SupplierOut[]
  ingredients: IngredientOut[]
  onAdded: () => void
}) {
  const [supplierId, setSupplierId] = useState('')
  const [ingredientId, setIngredientId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [requiredDeliveryDate, setRequiredDeliveryDate] = useState('')
  const [orderCycle, setOrderCycle] = useState('')

  // If this form mounts before suppliers/ingredients have loaded (a quick
  // tap on "+ Line"), useState's initial value would have been stuck at ''
  // forever even once the lists arrived — the Select would visually show
  // the first option while state (and the submitted body) stayed empty,
  // failing backend validation. Deriving the effective id fresh on every
  // render instead keeps what's shown and what's submitted in sync.
  const effectiveSupplierId = supplierId || suppliers[0]?.id || ''
  const effectiveIngredientId = ingredientId || ingredients[0]?.id || ''

  const addLine = useMutation({
    mutationFn: () =>
      api.purchaseOrders.addOrMergeLine(venueId, {
        supplier_id: effectiveSupplierId,
        ingredient_id: effectiveIngredientId,
        quantity,
        required_delivery_date: requiredDeliveryDate || undefined,
        order_cycle: orderCycle || undefined,
      }),
    onSuccess: onAdded,
  })

  // Locked backend rule: a draft PO's identity is (venue, supplier,
  // required_delivery_date, order_cycle) — supplier alone isn't enough to
  // tell two concurrent draft orders to the same supplier apart, so the
  // API rejects a line with neither set. Mirrored here so the chef sees
  // this before submitting, not as a raw 422.
  const hasDeliveryIdentity = !!requiredDeliveryDate || !!orderCycle.trim()

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    addLine.mutate()
  }

  if (suppliers.length === 0 || ingredients.length === 0) {
    return <EmptyState title="Add a supplier and an ingredient first" hint="Set these up under More → Catalog." />
  }

  const selectedIngredient = ingredients.find((i) => i.id === effectiveIngredientId)

  return (
    <Card>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Supplier">
          <Select value={effectiveSupplierId} onChange={(e) => setSupplierId(e.target.value)}>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field label="Ingredient">
          <Select value={effectiveIngredientId} onChange={(e) => setIngredientId(e.target.value)}>
            {ingredients.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </Select>
        </Field>
        <Field label="Quantity">
          <Input
            placeholder={selectedIngredient ? `e.g. 10 ${selectedIngredient.ordering_unit}` : 'Quantity'}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </Field>
        <Field label="Required delivery date">
          <Input type="date" value={requiredDeliveryDate} onChange={(e) => setRequiredDeliveryDate(e.target.value)} />
        </Field>
        <Field label="Or order cycle (e.g. 'Tuesday delivery', 'weekly')">
          <Input value={orderCycle} onChange={(e) => setOrderCycle(e.target.value)} placeholder="Leave blank if you set a date above" />
        </Field>
        {!hasDeliveryIdentity && (
          <p className="text-sm text-[var(--color-text-muted)]">A delivery date or an order cycle is needed to identify this order.</p>
        )}
        {addLine.isError && <ErrorBlock error={addLine.error} />}
        <Button type="submit" fullWidth disabled={addLine.isPending || !hasDeliveryIdentity}>
          {addLine.isPending ? 'Adding…' : 'Add line'}
        </Button>
      </form>
    </Card>
  )
}
