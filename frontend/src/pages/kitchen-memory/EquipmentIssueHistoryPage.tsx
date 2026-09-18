// Epic 9 — an Equipment Item's full issue history (open + resolved),
// reached from the Quick Capture flow or Catalog admin.

import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { Badge, Card, SectionHeading } from '../../components/primitives'
import { ErrorBlock, LoadingBlock, PageHeader, EmptyState } from '../../components/feedback'

export function EquipmentIssueHistoryPage() {
  const { equipmentItemId = '' } = useParams()
  const { currentVenueId } = useAuth()

  const { data, isLoading, error } = useQuery({
    queryKey: ['equipment-issue-history', currentVenueId, equipmentItemId],
    queryFn: () => api.kitchenMemory.equipmentIssueHistory(currentVenueId!, equipmentItemId),
    enabled: !!currentVenueId,
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorBlock error={error} />
  if (!data) return null

  return (
    <div className="space-y-4 pb-4">
      <PageHeader title={data.equipment_item.name} subtitle={data.equipment_item.location ?? undefined} />

      <Card>
        <SectionHeading>Issue history</SectionHeading>
        {data.issues.length === 0 && <EmptyState title="No issues logged" />}
        <div className="space-y-2">
          {data.issues.map((issue) => (
            <div key={issue.id} className="border-b border-[var(--color-border)] last:border-0 py-2">
              <div className="flex items-center gap-2 mb-1">
                <Badge tone={issue.status === 'open' ? 'warning' : 'success'}>{issue.status}</Badge>
                <Badge tone={issue.priority === 'high' ? 'danger' : issue.priority === 'medium' ? 'warning' : 'neutral'}>{issue.priority}</Badge>
              </div>
              <p className="text-sm text-[var(--color-text-muted)]">Opened {format(new Date(issue.opened_at), 'd MMM yyyy')}</p>
              {issue.resolution_notes && <p className="text-sm mt-1">{issue.resolution_notes}</p>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
