// Magic-link auth (mirrors app/services/auth_service.py exactly — no
// passwords anywhere). A user can hold Memberships at more than one Venue
// (e.g. an owner with several sites), so this context also tracks which
// Venue is "current" — everything module-level reads that, not a prop
// drilled through every route.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ApiError, setAuthToken } from '../api/client'
import type { MeResponse, MembershipRole } from '../api/types'

const TOKEN_KEY = 'mise_token'
const VENUE_KEY = 'mise_current_venue_id'

interface AuthContextValue {
  status: 'loading' | 'signed_out' | 'signed_in'
  me: MeResponse | null
  currentVenueId: string | null
  currentRole: MembershipRole | null
  setCurrentVenueId: (venueId: string) => void
  requestLink: (email: string) => Promise<{ devToken: string | null }>
  verify: (token: string) => Promise<void>
  logout: () => void
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthContextValue['status']>('loading')
  const [me, setMe] = useState<MeResponse | null>(null)
  const [currentVenueId, setCurrentVenueIdState] = useState<string | null>(() => localStorage.getItem(VENUE_KEY))

  const loadMe = useCallback(async () => {
    try {
      const response = await api.auth.me()
      setMe(response)
      setStatus('signed_in')
      // Default to the first Membership's venue if none is selected yet,
      // or if the stored one no longer belongs to this user.
      setCurrentVenueIdState((prev) => {
        const stillValid = prev && response.memberships.some((m) => m.venue_id === prev)
        const next = stillValid ? prev : (response.memberships[0]?.venue_id ?? null)
        if (next) localStorage.setItem(VENUE_KEY, next)
        return next
      })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        localStorage.removeItem(TOKEN_KEY)
        setAuthToken(null)
        setMe(null)
        setStatus('signed_out')
      } else {
        throw error
      }
    }
  }, [])

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY)
    if (!stored) {
      setStatus('signed_out')
      return
    }
    setAuthToken(stored)
    loadMe()
  }, [loadMe])

  const requestLink = useCallback(async (email: string) => {
    const response = await api.auth.requestLink(email)
    return { devToken: response.dev_token }
  }, [])

  const verify = useCallback(
    async (token: string) => {
      const response = await api.auth.verify(token)
      localStorage.setItem(TOKEN_KEY, response.access_token)
      setAuthToken(response.access_token)
      await loadMe()
    },
    [loadMe],
  )

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(VENUE_KEY)
    setAuthToken(null)
    setMe(null)
    setStatus('signed_out')
  }, [])

  const setCurrentVenueId = useCallback((venueId: string) => {
    localStorage.setItem(VENUE_KEY, venueId)
    setCurrentVenueIdState(venueId)
  }, [])

  const currentRole = useMemo<MembershipRole | null>(() => {
    if (!me || !currentVenueId) return null
    return me.memberships.find((m) => m.venue_id === currentVenueId)?.role ?? null
  }, [me, currentVenueId])

  const value = useMemo<AuthContextValue>(
    () => ({ status, me, currentVenueId, currentRole, setCurrentVenueId, requestLink, verify, logout, refreshMe: loadMe }),
    [status, me, currentVenueId, currentRole, setCurrentVenueId, requestLink, verify, logout, loadMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}

export const MANAGEMENT_ROLES: MembershipRole[] = ['owner', 'ops_manager', 'head_chef']
export const PREP_EXECUTION_ROLES: MembershipRole[] = ['head_chef', 'sous_chef']
export const OWNER_ONLY: MembershipRole[] = ['owner']

/** Client-side role gating is UX only — hides buttons a role's own token
 * would get a 403 from anyway. The backend (require_membership) is the
 * real, only enforcement point; this never substitutes for it. */
export function useHasRole(allowed: MembershipRole[]): boolean {
  const { currentRole } = useAuth()
  return currentRole !== null && allowed.includes(currentRole)
}
