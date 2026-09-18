// "Sign up" is really "create your first Organisation + Venue" — there's
// no separate registration step (locked design decision). Shown whenever
// a signed-in User has zero Memberships yet.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../../api/client'
import { Button, Card, Field, Input } from '../../components/primitives'
import { ErrorBlock } from '../../components/feedback'
import { useAuth } from '../../auth/AuthContext'

export function CreateOrganisationPage() {
  const { refreshMe, setCurrentVenueId } = useAuth()
  const navigate = useNavigate()
  const [organisationName, setOrganisationName] = useState('')
  const [venueName, setVenueName] = useState('')
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'Australia/Sydney')

  const createOrg = useMutation({
    mutationFn: () => api.onboarding.createOrganisation({ organisation_name: organisationName, venue_name: venueName, timezone }),
    onSuccess: async (created) => {
      // Make the just-created venue current before navigating — otherwise
      // the Gate's default-to-first-membership logic in refreshMe() would
      // still pick the right one for a brand-new user, but an existing
      // owner adding a second venue would stay on their old one.
      setCurrentVenueId(created.venue.id)
      await refreshMe()
      navigate('/', { replace: true })
    },
  })

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    createOrg.mutate()
  }

  return (
    <div className="min-h-dvh flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-1">Set up your kitchen</h1>
        <p className="text-[var(--color-text-muted)] mb-6 text-sm">
          One organisation, one venue to start — you can invite your team once this is created.
        </p>
        <Card>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Organisation name">
              <Input required value={organisationName} onChange={(e) => setOrganisationName(e.target.value)} placeholder="e.g. Harbourside Diner Pty Ltd" />
            </Field>
            <Field label="Venue name">
              <Input required value={venueName} onChange={(e) => setVenueName(e.target.value)} placeholder="e.g. Harbourside Diner" />
            </Field>
            <Field label="Timezone">
              <Input required value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Australia/Sydney" />
            </Field>
            {createOrg.isError && <ErrorBlock error={createOrg.error} />}
            <Button type="submit" fullWidth disabled={createOrg.isPending}>
              {createOrg.isPending ? 'Creating…' : 'Create venue'}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}
