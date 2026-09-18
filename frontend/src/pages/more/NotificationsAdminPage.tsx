// Epic 10 — Notifications admin. run-checks is the only endpoint the
// backend exposes for this epic (a manual trigger for the same checks a
// scheduled job would run) — this page is a button plus the resulting
// list of what got sent.

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, SectionHeading } from '../../components/primitives'
import { ErrorBlock, EmptyState, PageHeader } from '../../components/feedback'
import type { SentNotificationOut } from '../../api/types'

export function NotificationsAdminPage() {
  const { currentVenueId } = useAuth()
  const [lastRun, setLastRun] = useState<SentNotificationOut[] | null>(null)

  const runChecks = useMutation({
    mutationFn: () => api.notifications.runChecks(currentVenueId!),
    onSuccess: (sent) => setLastRun(sent),
  })

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Notifications" />
      <Card>
        <SectionHeading>Run checks now</SectionHeading>
        <p className="text-sm text-[var(--color-text-muted)] mb-3">
          Checks coverage gaps, approaching order cutoffs, and open equipment issues, and sends any notifications that are due.
        </p>
        <Button fullWidth onClick={() => runChecks.mutate()} disabled={runChecks.isPending}>
          {runChecks.isPending ? 'Running…' : 'Run checks'}
        </Button>
        {runChecks.isError && <ErrorBlock error={runChecks.error} />}
      </Card>

      {lastRun && (
        <Card>
          <SectionHeading>Sent this run</SectionHeading>
          {lastRun.length === 0 && <EmptyState title="Nothing needed sending" />}
          <div className="space-y-2">
            {lastRun.map((n, i) => (
              <div key={i} className="text-sm border-b border-[var(--color-border)] last:border-0 py-1.5">
                <p className="font-medium">{n.subject}</p>
                <p className="text-[var(--color-text-muted)]">{n.action} · to {n.recipients.join(', ')}</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
