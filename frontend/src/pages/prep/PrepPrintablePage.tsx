// Epic 4 — the printable list. Locked AC: "no chef-only chrome, just what
// belongs on a printed prep list" — so this deliberately skips the app
// shell's dark theme and nav in favor of plain, high-contrast, print-
// friendly output (a light background prints far better than a dark one).

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { useCurrentServiceDay } from '../../hooks/useCurrentServiceDay'
import { LoadingBlock, ErrorBlock } from '../../components/feedback'

export function PrepPrintablePage() {
  const { currentVenueId } = useAuth()
  const { data: currentDay } = useCurrentServiceDay()
  const businessDate = currentDay?.business_date ?? null

  const { data: items, isLoading, error } = useQuery({
    queryKey: ['prep-printable', currentVenueId, businessDate],
    queryFn: () => api.prep.printableList(currentVenueId!, businessDate!),
    enabled: !!currentVenueId && !!businessDate,
  })

  return (
    <div className="fixed inset-0 bg-white text-black overflow-y-auto p-6 z-50">
      <div className="flex items-center justify-between mb-4 print:hidden">
        <h1 className="text-lg font-semibold">Prep list — {businessDate && format(new Date(businessDate), 'd MMM yyyy')}</h1>
        <div className="flex gap-2">
          <button onClick={() => window.print()} className="text-sm underline">Print</button>
          <button onClick={() => history.back()} className="text-sm underline">Close</button>
        </div>
      </div>

      {isLoading && <LoadingBlock />}
      {error && <ErrorBlock error={error} />}

      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b-2 border-black">
            <th className="py-2 pr-2">Station</th>
            <th className="py-2 pr-2">Item</th>
            <th className="py-2 pr-2">Qty</th>
            <th className="py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {(items ?? []).map((item, i) => (
            <tr key={i} className="border-b border-gray-300">
              <td className="py-2 pr-2">{item.station_name}</td>
              <td className="py-2 pr-2">{item.item}</td>
              <td className="py-2 pr-2">{item.quantity} {item.unit}</td>
              <td className="py-2">{item.status.replace('_', ' ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
