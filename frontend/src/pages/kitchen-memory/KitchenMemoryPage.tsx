// Epic 9 — Kitchen Memory. A search box over recipes/versions/supplier
// notes/equipment issues/handover notes, plus a plain list of recipes to
// browse and create new ones from.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Input, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'

export function KitchenMemoryPage() {
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [newRecipeName, setNewRecipeName] = useState('')

  const { data: results, isLoading: searching } = useQuery({
    queryKey: ['kitchen-memory-search', venueId, searchTerm],
    queryFn: () => api.kitchenMemory.search(venueId, searchTerm),
    enabled: !!searchTerm,
  })

  const { data: recipes, isLoading, error } = useQuery({
    queryKey: ['recipes', venueId],
    queryFn: () => api.kitchenMemory.listRecipes(venueId),
  })

  const createRecipe = useMutation({
    mutationFn: () => api.kitchenMemory.createRecipe(venueId, newRecipeName),
    onSuccess: () => {
      setNewRecipeName('')
      queryClient.invalidateQueries({ queryKey: ['recipes', venueId] })
    },
  })

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Kitchen memory" />

      <Card>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            setSearchTerm(query)
          }}
          className="flex gap-2"
        >
          <Input placeholder="Search recipes, notes, issues…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <Button type="submit">Search</Button>
        </form>
        {searching && <LoadingBlock />}
        {results && results.length > 0 && (
          <div className="mt-3 space-y-2">
            {results.map((r, i) => (
              <div key={i} className="text-sm border-b border-[var(--color-border)] last:border-0 py-1.5">
                <p className="font-medium">
                  {r.title} <span className="text-[var(--color-text-muted)]">· {r.result_type.replace('_', ' ')}</span>
                </p>
                <p className="text-[var(--color-text-muted)]">{r.matched_text}</p>
              </div>
            ))}
          </div>
        )}
        {results && results.length === 0 && searchTerm && <p className="text-sm text-[var(--color-text-muted)] mt-2">No matches.</p>}
      </Card>

      <Card>
        <SectionHeading>Recipes</SectionHeading>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            createRecipe.mutate()
          }}
          className="flex gap-2 mb-3"
        >
          <Input placeholder="New recipe name" value={newRecipeName} onChange={(e) => setNewRecipeName(e.target.value)} required />
          <Button type="submit" disabled={createRecipe.isPending}>Add</Button>
        </form>
        {createRecipe.isError && <ErrorBlock error={createRecipe.error} />}
        {isLoading && <LoadingBlock />}
        {error && <ErrorBlock error={error} />}
        {recipes && recipes.length === 0 && <EmptyState title="No recipes yet" />}
        <div className="space-y-1">
          {(recipes ?? []).map((r) => (
            <Link key={r.id} to={`/kitchen-memory/recipes/${r.id}`} className="block py-1.5 border-b border-[var(--color-border)] last:border-0">
              {r.name}
            </Link>
          ))}
        </div>
      </Card>
    </div>
  )
}
