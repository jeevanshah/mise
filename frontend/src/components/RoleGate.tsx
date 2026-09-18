import type { ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import type { MembershipRole } from '../api/types'

/** Hides children the current role's own API token would get a 403 from
 * anyway — pure UX, never the real access boundary (that's always
 * require_membership on the backend). */
export function RoleGate({ allow, children }: { allow: MembershipRole[]; children: ReactNode }) {
  const { currentRole } = useAuth()
  if (!currentRole || !allow.includes(currentRole)) return null
  return <>{children}</>
}
