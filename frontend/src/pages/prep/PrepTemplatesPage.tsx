// Epic 4 admin — reusable {station, item, quantity, priority} lists.
// MANAGEMENT_ROLES only (this is venue configuration, not floor
// execution).

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Field, Input, Select } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'

export function PrepTemplatesPage() {
  const { currentVenueId } = useAuth()
  const queryClient = useQueryClient()
  const [newTemplateName, setNewTemplateName] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: templates, isLoading, error } = useQuery({
    queryKey: ['prep-templates', currentVenueId],
    queryFn: () => api.prep.listTemplates(currentVenueId!),
    enabled: !!currentVenueId,
  })

  const createTemplate = useMutation({
    mutationFn: () => api.prep.createTemplate(currentVenueId!, newTemplateName),
    onSuccess: () => {
      setNewTemplateName('')
      queryClient.invalidateQueries({ queryKey: ['prep-templates', currentVenueId] })
    },
  })

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Prep templates" />

      <Card>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            createTemplate.mutate()
          }}
          className="flex gap-2"
        >
          <Input placeholder="New template name" value={newTemplateName} onChange={(e) => setNewTemplateName(e.target.value)} required />
          <Button type="submit" disabled={createTemplate.isPending}>Add</Button>
        </form>
        {createTemplate.isError && <ErrorBlock error={createTemplate.error} />}
      </Card>

      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} />}
      {templates && templates.length === 0 && <EmptyState title="No templates yet" />}

      {(templates ?? []).map((t) => (
        <Card key={t.id}>
          <button className="w-full text-left font-medium" onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}>
            {t.name}
          </button>
          {expandedId === t.id && <TemplateItems venueId={currentVenueId!} templateId={t.id} />}
        </Card>
      ))}
    </div>
  )
}

function TemplateItems({ venueId, templateId }: { venueId: string; templateId: string }) {
  const queryClient = useQueryClient()
  const [item, setItem] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState('')
  const [stationId, setStationId] = useState('')

  const { data: detail } = useQuery({
    queryKey: ['prep-template', venueId, templateId],
    queryFn: () => api.prep.getTemplate(venueId, templateId),
  })
  const { data: stations } = useQuery({
    queryKey: ['stations', venueId],
    queryFn: () => api.staffing.listStations(venueId),
  })

  // The Select falls back to displaying the first station before the user
  // has touched it — but a plain "value={stationId || stations[0].id}" is
  // display-only: state itself stays '' until onChange fires, so a submit
  // with the default option still selected sent station_id: '' (a 422 from
  // the backend). This is the single source of truth both the Select and
  // the mutation use, so what's shown is always what gets submitted.
  const effectiveStationId = stationId || stations?.[0]?.id || ''

  const addItem = useMutation({
    mutationFn: () => api.prep.addTemplateItem(venueId, templateId, { station_id: effectiveStationId, item, quantity, unit }),
    onSuccess: () => {
      setItem('')
      setQuantity('')
      setUnit('')
      queryClient.invalidateQueries({ queryKey: ['prep-template', venueId, templateId] })
    },
  })

  return (
    <div className="mt-3 pt-3 border-t border-[var(--color-border)] space-y-3">
      {(detail?.items ?? []).map((i) => (
        <p key={i.id} className="text-sm text-[var(--color-text-muted)]">{i.item} — {i.quantity} {i.unit}</p>
      ))}

      {(stations ?? []).length > 0 && (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            addItem.mutate()
          }}
          className="space-y-2"
        >
          <Field label="Station">
            <Select value={effectiveStationId} onChange={(e) => setStationId(e.target.value)}>
              {stations!.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Input placeholder="Item" value={item} onChange={(e) => setItem(e.target.value)} required />
          <div className="flex gap-2">
            <Input placeholder="Qty" value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
            <Input placeholder="Unit" value={unit} onChange={(e) => setUnit(e.target.value)} required />
          </div>
          <Button type="submit" fullWidth disabled={addItem.isPending}>Add item</Button>
          {addItem.isError && <ErrorBlock error={addItem.error} />}
        </form>
      )}
    </div>
  )
}
