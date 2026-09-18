// Epic 9 — a Recipe's version history. Each RecipeVersion is immutable
// once created (recipes are versioned, never edited in place) —
// "editing" a recipe here means creating version N+1.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { Button, Card, Field, Input, Select, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, PageHeader, EmptyState } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'

interface IngredientLine {
  ingredientId: string
  quantity: string
  unit: string
}

export function RecipeDetailPage() {
  const { recipeId = '' } = useParams()
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!
  const queryClient = useQueryClient()
  const [showNewVersion, setShowNewVersion] = useState(false)
  const [yieldQty, setYieldQty] = useState('')
  const [yieldUnit, setYieldUnit] = useState('')
  const [prepNotes, setPrepNotes] = useState('')
  const [lines, setLines] = useState<IngredientLine[]>([{ ingredientId: '', quantity: '', unit: '' }])

  const { data: recipe, isLoading, error } = useQuery({
    queryKey: ['recipe', venueId, recipeId],
    queryFn: () => api.kitchenMemory.getRecipe(venueId, recipeId),
  })
  const { data: versions } = useQuery({
    queryKey: ['recipe-versions', venueId, recipeId],
    queryFn: () => api.kitchenMemory.listVersions(venueId, recipeId),
  })
  const { data: ingredients } = useQuery({
    queryKey: ['ingredients', venueId],
    queryFn: () => api.catalog.listIngredients(venueId),
  })

  const createVersion = useMutation({
    mutationFn: () =>
      api.kitchenMemory.createVersion(venueId, recipeId, {
        yield_qty: yieldQty || undefined,
        yield_unit: yieldUnit || undefined,
        prep_notes: prepNotes || undefined,
        ingredients: lines
          .filter((l) => l.ingredientId && l.quantity)
          .map((l) => ({ ingredient_id: l.ingredientId, quantity: l.quantity, unit: l.unit })),
      }),
    onSuccess: () => {
      setShowNewVersion(false)
      setYieldQty('')
      setYieldUnit('')
      setPrepNotes('')
      setLines([{ ingredientId: '', quantity: '', unit: '' }])
      queryClient.invalidateQueries({ queryKey: ['recipe', venueId, recipeId] })
      queryClient.invalidateQueries({ queryKey: ['recipe-versions', venueId, recipeId] })
    },
  })

  function updateLine(index: number, patch: Partial<IngredientLine>) {
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)))
  }

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorBlock error={error} />
  if (!recipe) return null

  return (
    <div className="space-y-4 pb-4">
      <PageHeader
        title={recipe.name}
        subtitle={
          recipe.current_version
            ? `v${recipe.current_version.version_no} · ${recipe.version_count} version${recipe.version_count === 1 ? '' : 's'}`
            : 'No versions yet'
        }
      />

      {recipe.current_version && (
        <Card>
          <SectionHeading>Current version</SectionHeading>
          {recipe.current_version.yield_qty && (
            <p className="text-sm text-[var(--color-text-muted)] mb-2">
              Yields {recipe.current_version.yield_qty} {recipe.current_version.yield_unit}
            </p>
          )}
          <div className="space-y-1 mb-2">
            {recipe.current_version.ingredients.map((ing, i) => (
              <p key={i} className="text-sm">{ing.ingredient_name} — {ing.quantity} {ing.unit}</p>
            ))}
          </div>
          {recipe.current_version.prep_notes && <p className="text-sm text-[var(--color-text-muted)]">{recipe.current_version.prep_notes}</p>}
        </Card>
      )}

      <RoleGate allow={MANAGEMENT_ROLES}>
        <Button fullWidth variant="secondary" onClick={() => setShowNewVersion((v) => !v)}>
          {showNewVersion ? 'Cancel' : '+ New version'}
        </Button>

        {showNewVersion && (
          <Card>
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault()
                createVersion.mutate()
              }}
              className="space-y-3"
            >
              <div className="flex gap-2">
                <Input placeholder="Yield qty" value={yieldQty} onChange={(e) => setYieldQty(e.target.value)} />
                <Input placeholder="Yield unit" value={yieldUnit} onChange={(e) => setYieldUnit(e.target.value)} />
              </div>
              <div className="space-y-2">
                {lines.map((line, i) => (
                  <div key={i} className="flex gap-2">
                    <Select value={line.ingredientId} onChange={(e) => updateLine(i, { ingredientId: e.target.value })} className="flex-1">
                      <option value="">Ingredient…</option>
                      {(ingredients ?? []).map((ing) => <option key={ing.id} value={ing.id}>{ing.name}</option>)}
                    </Select>
                    <Input placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, { quantity: e.target.value })} className="w-16" />
                    <Input placeholder="Unit" value={line.unit} onChange={(e) => updateLine(i, { unit: e.target.value })} className="w-16" />
                  </div>
                ))}
                <Button type="button" variant="ghost" onClick={() => setLines((prev) => [...prev, { ingredientId: '', quantity: '', unit: '' }])}>
                  + Add ingredient
                </Button>
              </div>
              <Field label="Prep notes (optional)">
                <Input value={prepNotes} onChange={(e) => setPrepNotes(e.target.value)} />
              </Field>
              {createVersion.isError && <ErrorBlock error={createVersion.error} />}
              <Button type="submit" fullWidth disabled={createVersion.isPending}>
                {createVersion.isPending ? 'Saving…' : 'Save version'}
              </Button>
            </form>
          </Card>
        )}
      </RoleGate>

      <Card>
        <SectionHeading>Version history</SectionHeading>
        {(!versions || versions.length === 0) && <EmptyState title="No versions yet" />}
        <div className="space-y-1">
          {(versions ?? []).map((v) => (
            <p key={v.id} className="text-sm text-[var(--color-text-muted)] py-1 border-b border-[var(--color-border)] last:border-0">
              v{v.version_no}{v.yield_qty ? ` · ${v.yield_qty} ${v.yield_unit}` : ''}
            </p>
          ))}
        </div>
      </Card>
    </div>
  )
}
