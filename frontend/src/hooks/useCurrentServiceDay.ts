// "Today" for kitchen ops purposes is never new Date() on the client — the
// backend resolves business_date from the venue's own timezone +
// business_day_boundary (a dinner service ending 1am is still the prior
// business_date). Every screen that needs "today" reads it from here
// rather than doing its own date math, mirroring service_day_service.py's
// own single-source-of-truth rule on the backend.

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function useCurrentServiceDay() {
  const { currentVenueId } = useAuth()
  return useQuery({
    queryKey: ['service-day', 'current', currentVenueId],
    queryFn: () => api.serviceDays.current(currentVenueId!),
    enabled: !!currentVenueId,
  })
}
