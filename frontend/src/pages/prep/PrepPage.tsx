// Epic 4 — today's prep list, grouped by station. Status updates are
// gated to PREP_EXECUTION_ROLES (head_chef/sous_chef only — deliberately
// narrower than MANAGEMENT_ROLES, mirroring the backend's own gate).

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addDays, format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth, MANAGEMENT_ROLES, PREP_EXECUTION_ROLES } from '../../auth/AuthContext'
import { useCurrentServiceDay } from '../../hooks/useCurrentServiceDay'
import { Badge, Button, Card, Select, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, EmptyState, PageHeader } from '../../components/feedback'
import { RoleGate } from '../../components/RoleGate'
import { useHasRole } from '../../auth/AuthContext'
import type { PrepTaskOut, PrepTaskStatus } from '../../api/types'

const STATUS_OPTIONS: PrepTaskStatus[] = ['not_started', 'in_progress', 'done', 'blocked']

function statusTone(status: PrepTaskStatus) {
  if (status === 'done') return 'success' as const
  if (status === 'blocked') return 'danger' as const
  if (status === 'in_progress') return 'info' as const
  return 'neutral' as const
}

export function PrepPage() {
  const { currentVenueId } = useAuth()
  const { data: currentDay } = useCurrentServiceDay()
  const queryClient = useQueryClient()
  const [applying, setApplying] = useState(false)
  const canEditStatus = useHasRole(PREP_EXECUTION_ROLES)

  const businessDate = currentDay?.business_date ?? null

  const { data: tasks, isLoading, error, refetch } = useQuery({
    queryKey: ['prep-tasks', currentVenueId, businessDate],
    queryFn: () => api.prep.listTasks(currentVenueId!, businessDate!),
    enabled: !!currentVenueId && !!businessDate,
  })

  const { data: templates } = useQuery({
    queryKey: ['prep-templates', currentVenueId],
    queryFn: () => api.prep.listTemplates(currentVenueId!),
    enabled: !!currentVenueId,
  })

  const { data: stations } = useQuery({
    queryKey: ['stations', currentVenueId],
    queryFn: () => api.staffing.listStations(currentVenueId!),
    enabled: !!currentVenueId,
  })
  const stationsById = useMemo(() => new Map((stations ?? []).map((s) => [s.id, s])), [stations])

  const updateStatus = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: PrepTaskStatus }) => api.prep.updateTaskStatus(currentVenueId!, taskId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prep-tasks', currentVenueId, businessDate] })
      queryClient.invalidateQueries({ queryKey: ['chef-brief', currentVenueId] })
    },
  })

  const applyTemplate = useMutation({
    mutationFn: (templateId: string) => api.prep.applyTemplate(currentVenueId!, businessDate!, templateId),
    onSuccess: () => {
      setApplying(false)
      queryClient.invalidateQueries({ queryKey: ['prep-tasks', currentVenueId, businessDate] })
    },
  })

  const carryForward = useMutation({
    mutationFn: () => api.prep.carryForward(currentVenueId!, businessDate!, format(addDays(new Date(businessDate!), 1), 'yyyy-MM-dd')),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['prep-tasks', currentVenueId, businessDate] }),
  })

  const grouped = useMemo(() => {
    const map = new Map<string, PrepTaskOut[]>()
    for (const task of tasks ?? []) {
      const key = task.station_id
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(task)
    }
    return map
  }, [tasks])

  return (
    <div className="space-y-4 pb-4">
      <PageHeader
        title="Prep"
        subtitle={businessDate ? format(new Date(businessDate), 'EEEE d MMM') : undefined}
        action={<Link to="/prep/printable" className="text-xs text-[var(--color-accent)]">Printable</Link>}
      />

      <RoleGate allow={MANAGEMENT_ROLES}>
        <div className="flex gap-2">
          <Button variant="secondary" fullWidth onClick={() => setApplying((v) => !v)}>Apply template</Button>
          <Button variant="secondary" fullWidth onClick={() => carryForward.mutate()} disabled={carryForward.isPending}>
            Carry forward
          </Button>
        </div>
        {applying && (
          <Card className="space-y-2">
            {(templates ?? []).length === 0 ? (
              <EmptyState title="No templates yet" hint="Create one under Prep → Templates." />
            ) : (
              templates!.map((t) => (
                <Button key={t.id} variant="secondary" fullWidth onClick={() => applyTemplate.mutate(t.id)} disabled={applyTemplate.isPending}>
                  {t.name}
                </Button>
              ))
            )}
            <Link to="/prep/templates" className="block text-center text-sm text-[var(--color-accent)]">Manage templates</Link>
          </Card>
        )}
        {applyTemplate.isError && <ErrorBlock error={applyTemplate.error} />}
        {carryForward.isError && <ErrorBlock error={carryForward.error} />}
      </RoleGate>

      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} onRetry={() => refetch()} />}

      {tasks && tasks.length === 0 && <EmptyState title="No prep tasks yet" hint="Apply a template to get started." />}

      {Array.from(grouped.entries()).map(([stationId, stationTasks]) => (
        <Card key={stationId}>
          <SectionHeading>{stationsById.get(stationId)?.name ?? 'Station'}</SectionHeading>
          <div className="space-y-2">
            {stationTasks
              .sort((a, b) => b.priority - a.priority)
              .map((task) => (
                <div key={task.id} className="flex items-center justify-between gap-2 py-2 border-b border-[var(--color-border)] last:border-0">
                  <div className="min-w-0">
                    <p className="font-medium truncate">{task.item}</p>
                    <p className="text-sm text-[var(--color-text-muted)]">{task.quantity} {task.unit}{task.carry_count > 0 ? ` · carried x${task.carry_count}` : ''}</p>
                  </div>
                  {canEditStatus ? (
                    <Select
                      className="w-auto min-w-0"
                      value={task.status}
                      onChange={(e) => updateStatus.mutate({ taskId: task.id, status: e.target.value as PrepTaskStatus })}
                    >
                      {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                    </Select>
                  ) : (
                    <Badge tone={statusTone(task.status)}>{task.status.replace('_', ' ')}</Badge>
                  )}
                </div>
              ))}
          </div>
        </Card>
      ))}
      {updateStatus.isError && <ErrorBlock error={updateStatus.error} />}
    </div>
  )
}
