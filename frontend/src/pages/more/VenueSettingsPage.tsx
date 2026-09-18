// Epic 1 admin — venue-level settings: timezone and the business-day
// boundary that resolve_business_date uses to decide when "today" rolls
// over (a service ending 1am is still yesterday's business_date).

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Field, Input } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, PageHeader } from '../../components/feedback'

export function VenueSettingsPage() {
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!
  const queryClient = useQueryClient()
  const [timezone, setTimezone] = useState('')
  const [boundary, setBoundary] = useState('')

  const { data: venue, isLoading, error } = useQuery({
    queryKey: ['venue', venueId],
    queryFn: () => api.onboarding.getVenue(venueId),
  })

  useEffect(() => {
    if (venue) {
      setTimezone(venue.timezone)
      setBoundary(venue.business_day_boundary)
    }
  }, [venue])

  const update = useMutation({
    mutationFn: () => api.onboarding.updateVenue(venueId, { timezone, business_day_boundary: boundary }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['venue', venueId] }),
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorBlock error={error} />

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Venue settings" subtitle={venue?.name} />
      <Card>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            update.mutate()
          }}
          className="space-y-3"
        >
          <Field label="Timezone (IANA, e.g. Australia/Melbourne)">
            <Input value={timezone} onChange={(e) => setTimezone(e.target.value)} required />
          </Field>
          <Field label="Business day boundary (HH:MM:SS, e.g. 04:00:00)">
            <Input value={boundary} onChange={(e) => setBoundary(e.target.value)} required />
          </Field>
          {update.isError && <ErrorBlock error={update.error} />}
          {update.isSuccess && <p className="text-sm text-emerald-400">Saved.</p>}
          <Button type="submit" fullWidth disabled={update.isPending}>{update.isPending ? 'Saving…' : 'Save'}</Button>
        </form>
      </Card>
    </div>
  )
}
