import { useEffect, useRef, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { ErrorBlock } from '../../components/feedback'
import { LoadingBlock } from '../../components/feedback'

export function VerifyPage() {
  const { status, verify } = useAuth()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [error, setError] = useState<unknown>(null)
  const attempted = useRef(false)

  useEffect(() => {
    if (!token || attempted.current) return
    attempted.current = true
    verify(token).catch(setError)
  }, [token, verify])

  if (status === 'signed_in') return <Navigate to="/" replace />
  if (!token) return <Navigate to="/login" replace />

  return (
    <div className="min-h-dvh flex items-center justify-center px-6">
      <div className="w-full max-w-sm text-center">
        {error ? <ErrorBlock error={error} /> : <LoadingBlock label="Signing you in…" />}
      </div>
    </div>
  )
}
