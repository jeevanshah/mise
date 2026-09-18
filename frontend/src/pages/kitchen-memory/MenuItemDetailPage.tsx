// Epic 9 — a Menu Item's linked recipes (a menu item can have more than
// one recipe attached — e.g. a dish plus its side).

import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES } from '../../auth/AuthContext'
import { Button, Card, Select, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, PageHeader, EmptyState } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'

export function MenuItemDetailPage() {
  const { menuItemId = '' } = useParams()
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!
  const queryClient = useQueryClient()
  const [recipeIdToLink, setRecipeIdToLink] = useState('')

  const { data: menuItem, isLoading, error } = useQuery({
    queryKey: ['menu-item', venueId, menuItemId],
    queryFn: () => api.kitchenMemory.getMenuItem(venueId, menuItemId),
  })
  const { data: allRecipes } = useQuery({
    queryKey: ['recipes', venueId],
    queryFn: () => api.kitchenMemory.listRecipes(venueId),
  })

  const linkRecipe = useMutation({
    mutationFn: () => api.kitchenMemory.linkRecipeToMenuItem(venueId, menuItemId, recipeIdToLink),
    onSuccess: () => {
      setRecipeIdToLink('')
      queryClient.invalidateQueries({ queryKey: ['menu-item', venueId, menuItemId] })
    },
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorBlock error={error} />
  if (!menuItem) return null

  const linkedIds = new Set(menuItem.recipes.map((r) => r.id))
  const linkable = (allRecipes ?? []).filter((r) => !linkedIds.has(r.id))

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title={menuItem.name} />

      <Card>
        <SectionHeading>Linked recipes</SectionHeading>
        {menuItem.recipes.length === 0 && <EmptyState title="No recipes linked" />}
        <div className="space-y-1">
          {menuItem.recipes.map((r) => (
            <Link key={r.id} to={`/kitchen-memory/recipes/${r.id}`} className="block py-1.5 border-b border-[var(--color-border)] last:border-0">
              {r.name}
            </Link>
          ))}
        </div>
      </Card>

      <RoleGate allow={MANAGEMENT_ROLES}>
        {linkable.length > 0 && (
          <Card>
            <SectionHeading>Link a recipe</SectionHeading>
            <div className="flex gap-2">
              <Select value={recipeIdToLink} onChange={(e) => setRecipeIdToLink(e.target.value)} className="flex-1">
                <option value="">Select recipe…</option>
                {linkable.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </Select>
              <Button onClick={() => linkRecipe.mutate()} disabled={!recipeIdToLink || linkRecipe.isPending}>Link</Button>
            </div>
            {linkRecipe.isError && <ErrorBlock error={linkRecipe.error} />}
          </Card>
        )}
      </RoleGate>
    </div>
  )
}
