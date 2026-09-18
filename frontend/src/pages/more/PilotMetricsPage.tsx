// Epic 11 — Pilot metrics. The three inputs the pilot ROI conversation
// needs: minutes saved per week, incidents Mise should have prevented,
// and the owner's own willingness-to-pay decision — plus a plain feed of
// everything logged so far.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth, OWNER_ONLY } from '../../auth/AuthContext'
import { Button, Card, Field, Input, Select, SectionHeading, Textarea } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import type { PilotMetricAction } from '../../api/types'

function actionLabel(action: PilotMetricAction) {
  if (action === 'metrics.minutes_saved_reported') return 'Minutes saved'
  if (action === 'metrics.incident_logged') return 'Incident'
  return 'Pilot decision'
}

export function PilotMetricsPage() {
  const { currentVenueId } = useAuth()
  const venueId = currentVenueId!
  const queryClient = useQueryClient()

  const [weekStart, setWeekStart] = useState('')
  const [minutesSaved, setMinutesSaved] = useState('')
  const [incidentDate, setIncidentDate] = useState('')
  const [incidentType, setIncidentType] = useState<'missed_order' | 'handover_failure'>('missed_order')
  const [incidentDescription, setIncidentDescription] = useState('')
  const [willPay, setWillPay] = useState(true)
  const [decisionNotes, setDecisionNotes] = useState('')

  const { data: events, isLoading, error } = useQuery({
    queryKey: ['pilot-metrics', venueId],
    queryFn: () => api.pilotMetrics.list(venueId),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['pilot-metrics', venueId] })

  const recordMinutes = useMutation({
    mutationFn: () => api.pilotMetrics.recordMinutesSaved(venueId, weekStart, Number(minutesSaved)),
    onSuccess: () => {
      setWeekStart('')
      setMinutesSaved('')
      invalidate()
    },
  })
  const logIncident = useMutation({
    mutationFn: () =>
      api.pilotMetrics.logIncident(venueId, { business_date: incidentDate, incident_type: incidentType, description: incidentDescription }),
    onSuccess: () => {
      setIncidentDate('')
      setIncidentDescription('')
      invalidate()
    },
  })
  const recordDecision = useMutation({
    mutationFn: () => api.pilotMetrics.recordDecision(venueId, willPay, decisionNotes || undefined),
    onSuccess: () => {
      setDecisionNotes('')
      invalidate()
    },
  })

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title="Pilot metrics" />

      <Card>
        <SectionHeading>Minutes saved this week</SectionHeading>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            recordMinutes.mutate()
          }}
          className="space-y-2"
        >
          <Field label="Week starting">
            <Input type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} required />
          </Field>
          <Field label="Minutes saved">
            <Input type="number" value={minutesSaved} onChange={(e) => setMinutesSaved(e.target.value)} required />
          </Field>
          {recordMinutes.isError && <ErrorBlock error={recordMinutes.error} />}
          <Button type="submit" fullWidth disabled={recordMinutes.isPending}>Record</Button>
        </form>
      </Card>

      <Card>
        <SectionHeading>Log an incident</SectionHeading>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            logIncident.mutate()
          }}
          className="space-y-2"
        >
          <Field label="Date">
            <Input type="date" value={incidentDate} onChange={(e) => setIncidentDate(e.target.value)} required />
          </Field>
          <Field label="Type">
            <Select value={incidentType} onChange={(e) => setIncidentType(e.target.value as 'missed_order' | 'handover_failure')}>
              <option value="missed_order">Missed order</option>
              <option value="handover_failure">Handover failure</option>
            </Select>
          </Field>
          <Field label="Description">
            <Textarea value={incidentDescription} onChange={(e) => setIncidentDescription(e.target.value)} required />
          </Field>
          {logIncident.isError && <ErrorBlock error={logIncident.error} />}
          <Button type="submit" fullWidth disabled={logIncident.isPending}>Log incident</Button>
        </form>
      </Card>

      <RoleGate allow={OWNER_ONLY}>
        <Card>
          <SectionHeading>Pilot decision</SectionHeading>
          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              recordDecision.mutate()
            }}
            className="space-y-2"
          >
            <Field label="Will you pay at the proposed price?">
              <Select value={willPay ? 'yes' : 'no'} onChange={(e) => setWillPay(e.target.value === 'yes')}>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </Select>
            </Field>
            <Field label="Notes (optional)">
              <Textarea value={decisionNotes} onChange={(e) => setDecisionNotes(e.target.value)} />
            </Field>
            {recordDecision.isError && <ErrorBlock error={recordDecision.error} />}
            <Button type="submit" fullWidth disabled={recordDecision.isPending}>Record decision</Button>
          </form>
        </Card>
      </RoleGate>

      <Card>
        <SectionHeading>All events</SectionHeading>
        {isLoading && <LoadingBlock />}
        {error && <ErrorBlock error={error} />}
        {events && events.length === 0 && <EmptyState title="No events yet" />}
        <div className="space-y-2">
          {(events ?? []).map((e) => (
            <div key={e.id} className="text-sm border-b border-[var(--color-border)] last:border-0 py-1.5">
              <p className="font-medium">{actionLabel(e.action)}</p>
              <p className="text-[var(--color-text-muted)]">{format(new Date(e.recorded_at), "d MMM, h:mma")}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
