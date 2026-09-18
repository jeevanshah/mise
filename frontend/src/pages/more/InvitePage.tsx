// Epic 1 admin — invite a user to this venue with a given role. The
// backend creates (or reuses) the user and a Membership directly; there's
// no separate accept-invite flow, mirroring the backend's own simplified
// invite endpoint.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Field, Input, Select } from '../../components/primitives'
import { ErrorBlock, PageHeader } from '../../components/feedback'
import type { MembershipRole } from '../../api/types'

const ROLES: MembershipRole[] = ['owner', 'ops_manager', 'head_chef', 'sous_chef', 'line_staff']

export function InvitePage() {
  const { currentVenueId } = useAuth()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<MembershipRole>('line_staff')

  const invite = useMutation({
    mutationFn: () => api.onboarding.invite(currentVenueId!, { email, role }),
    onSuccess: () => setEmail(''),
  })

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Invite" />
      <Card>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            invite.mutate()
          }}
          className="space-y-3"
        >
          <Field label="Email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Field label="Role">
            <Select value={role} onChange={(e) => setRole(e.target.value as MembershipRole)}>
              {ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}
            </Select>
          </Field>
          {invite.isError && <ErrorBlock error={invite.error} />}
          {invite.isSuccess && <p className="text-sm text-emerald-400">Invited.</p>}
          <Button type="submit" fullWidth disabled={invite.isPending}>{invite.isPending ? 'Inviting…' : 'Send invite'}</Button>
        </form>
      </Card>
    </div>
  )
}
