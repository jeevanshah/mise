// Epic 1 admin — Catalog: suppliers, ingredients, menu items, and
// equipment items. MANAGEMENT_ROLES only.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Field, Input, Select, SectionHeading, Textarea } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'

export function CatalogAdminPage() {
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Catalog" />
      <SuppliersSection venueId={venueId} />
      <IngredientsSection venueId={venueId} />
      <MenuItemsSection venueId={venueId} />
      <EquipmentSection venueId={venueId} />
    </div>
  )
}

function SuppliersSection({ venueId }: { venueId: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [notes, setNotes] = useState('')

  const { data: suppliers, isLoading, error } = useQuery({
    queryKey: ['suppliers', venueId],
    queryFn: () => api.catalog.listSuppliers(venueId),
  })

  const create = useMutation({
    mutationFn: () => api.catalog.createSupplier(venueId, { name, contact_email: contactEmail || undefined }),
    onSuccess: () => {
      setName('')
      setContactEmail('')
      queryClient.invalidateQueries({ queryKey: ['suppliers', venueId] })
    },
  })
  const updateNotes = useMutation({
    mutationFn: (supplierId: string) => api.catalog.updateSupplierNotes(venueId, supplierId, notes || null),
    onSuccess: () => {
      setExpandedId(null)
      queryClient.invalidateQueries({ queryKey: ['suppliers', venueId] })
    },
  })

  return (
    <Card>
      <SectionHeading>Suppliers</SectionHeading>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          create.mutate()
        }}
        className="space-y-2 mb-3"
      >
        <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <Input placeholder="Contact email (optional)" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
        <Button type="submit" fullWidth disabled={create.isPending}>Add supplier</Button>
      </form>
      {create.isError && <ErrorBlock error={create.error} />}
      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} />}
      {suppliers && suppliers.length === 0 && <EmptyState title="No suppliers yet" />}
      <div className="space-y-2">
        {(suppliers ?? []).map((s) => (
          <div key={s.id} className="border-b border-[var(--color-border)] last:border-0 pb-2">
            <button
              className="w-full text-left font-medium py-1"
              onClick={() => {
                setExpandedId(expandedId === s.id ? null : s.id)
                setNotes(s.notes ?? '')
              }}
            >
              {s.name}
            </button>
            {expandedId === s.id && (
              <div className="pl-2 space-y-2">
                <Textarea placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
                <Button fullWidth onClick={() => updateNotes.mutate(s.id)} disabled={updateNotes.isPending}>Save notes</Button>
                {updateNotes.isError && <ErrorBlock error={updateNotes.error} />}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function IngredientsSection({ venueId }: { venueId: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [unit, setUnit] = useState('')
  const [orderingUnit, setOrderingUnit] = useState('')
  const [preferredSupplierId, setPreferredSupplierId] = useState('')

  const { data: ingredients, isLoading, error } = useQuery({
    queryKey: ['ingredients', venueId],
    queryFn: () => api.catalog.listIngredients(venueId),
  })
  const { data: suppliers } = useQuery({
    queryKey: ['suppliers', venueId],
    queryFn: () => api.catalog.listSuppliers(venueId),
  })

  const create = useMutation({
    mutationFn: () =>
      api.catalog.createIngredient(venueId, {
        name,
        unit,
        ordering_unit: orderingUnit,
        preferred_supplier_id: preferredSupplierId || undefined,
      }),
    onSuccess: () => {
      setName('')
      setUnit('')
      setOrderingUnit('')
      queryClient.invalidateQueries({ queryKey: ['ingredients', venueId] })
    },
  })

  return (
    <Card>
      <SectionHeading>Ingredients</SectionHeading>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          create.mutate()
        }}
        className="space-y-2 mb-3"
      >
        <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <div className="flex gap-2">
          <Input placeholder="Usage unit (e.g. g)" value={unit} onChange={(e) => setUnit(e.target.value)} required />
          <Input placeholder="Ordering unit (e.g. box)" value={orderingUnit} onChange={(e) => setOrderingUnit(e.target.value)} required />
        </div>
        {suppliers && suppliers.length > 0 && (
          <Field label="Preferred supplier (optional)">
            <Select value={preferredSupplierId} onChange={(e) => setPreferredSupplierId(e.target.value)}>
              <option value="">None</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
        )}
        {create.isError && <ErrorBlock error={create.error} />}
        <Button type="submit" fullWidth disabled={create.isPending}>Add ingredient</Button>
      </form>
      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} />}
      {ingredients && ingredients.length === 0 && <EmptyState title="No ingredients yet" />}
      <div className="space-y-1">
        {(ingredients ?? []).map((i) => (
          <p key={i.id} className="text-sm text-[var(--color-text-muted)] py-1 border-b border-[var(--color-border)] last:border-0">
            {i.name} · {i.unit} / {i.ordering_unit}
          </p>
        ))}
      </div>
    </Card>
  )
}

function MenuItemsSection({ venueId }: { venueId: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')

  const { data: menuItems, isLoading, error } = useQuery({
    queryKey: ['menu-items', venueId],
    queryFn: () => api.catalog.listMenuItems(venueId),
  })

  const create = useMutation({
    mutationFn: () => api.catalog.createMenuItem(venueId, name),
    onSuccess: () => {
      setName('')
      queryClient.invalidateQueries({ queryKey: ['menu-items', venueId] })
    },
  })

  return (
    <Card>
      <SectionHeading>Menu items</SectionHeading>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          create.mutate()
        }}
        className="flex gap-2 mb-3"
      >
        <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <Button type="submit" disabled={create.isPending}>Add</Button>
      </form>
      {create.isError && <ErrorBlock error={create.error} />}
      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} />}
      {menuItems && menuItems.length === 0 && <EmptyState title="No menu items yet" />}
      <div className="space-y-1">
        {(menuItems ?? []).map((m) => (
          <Link
            key={m.id}
            to={`/kitchen-memory/menu-items/${m.id}`}
            className="block text-sm py-1 border-b border-[var(--color-border)] last:border-0"
          >
            {m.name}
          </Link>
        ))}
      </div>
    </Card>
  )
}

function EquipmentSection({ venueId }: { venueId: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [location, setLocation] = useState('')
  const [repairContact, setRepairContact] = useState('')

  const { data: equipmentItems, isLoading, error } = useQuery({
    queryKey: ['equipment-items', venueId],
    queryFn: () => api.catalog.listEquipmentItems(venueId),
  })

  const create = useMutation({
    mutationFn: () =>
      api.catalog.createEquipmentItem(venueId, { name, location: location || undefined, repair_contact: repairContact || undefined }),
    onSuccess: () => {
      setName('')
      setLocation('')
      setRepairContact('')
      queryClient.invalidateQueries({ queryKey: ['equipment-items', venueId] })
    },
  })

  return (
    <Card>
      <SectionHeading>Equipment</SectionHeading>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          create.mutate()
        }}
        className="space-y-2 mb-3"
      >
        <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <Input placeholder="Location (optional)" value={location} onChange={(e) => setLocation(e.target.value)} />
        <Input placeholder="Repair contact (optional)" value={repairContact} onChange={(e) => setRepairContact(e.target.value)} />
        {create.isError && <ErrorBlock error={create.error} />}
        <Button type="submit" fullWidth disabled={create.isPending}>Add equipment</Button>
      </form>
      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} />}
      {equipmentItems && equipmentItems.length === 0 && <EmptyState title="No equipment yet" />}
      <div className="space-y-1">
        {(equipmentItems ?? []).map((eq) => (
          <Link
            key={eq.id}
            to={`/kitchen-memory/equipment/${eq.id}`}
            className="block text-sm py-1 border-b border-[var(--color-border)] last:border-0"
          >
            {eq.name}
          </Link>
        ))}
      </div>
    </Card>
  )
}
