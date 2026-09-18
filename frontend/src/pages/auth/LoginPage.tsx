// Magic-link request. No passwords anywhere (locked design decision — see
// backend README's "Design notes"). In dev (ENVIRONMENT != production)
// the backend returns the raw token directly so this screen can offer a
// one-tap "continue" without needing real email delivery wired up yet.

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { Button, Card, Field, Input } from '../../components/primitives'
import { ErrorBlock } from '../../components/feedback'

export function LoginPage() {
  const { status, requestLink } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [devToken, setDevToken] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  if (status === 'signed_in') return <Navigate to="/" replace />

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const { devToken } = await requestLink(email)
      setSent(true)
      setDevToken(devToken)
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-dvh flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold text-center mb-1">
          <span className="text-[var(--color-accent)]">Mise</span>
        </h1>
        <p className="text-center text-[var(--color-text-muted)] mb-6">Head Chef Operating System</p>

        <Card>
          {!sent ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <Field label="Work email">
                <Input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@venue.com" />
              </Field>
              {error !== null ? <ErrorBlock error={error} /> : null}
              <Button type="submit" fullWidth disabled={submitting}>
                {submitting ? 'Sending…' : 'Send magic link'}
              </Button>
            </form>
          ) : (
            <div className="space-y-4 text-center">
              <p>Check <strong>{email}</strong> for a sign-in link.</p>
              {devToken && (
                <div className="text-left border-t border-[var(--color-border)] pt-3">
                  <p className="text-xs text-[var(--color-text-muted)] mb-2">
                    Dev mode — no email provider configured, so here's the link directly:
                  </p>
                  <Button variant="secondary" fullWidth onClick={() => navigate(`/verify?token=${devToken}`)}>
                    Continue as {email}
                  </Button>
                </div>
              )}
              <button className="text-sm text-[var(--color-text-muted)] underline" onClick={() => setSent(false)}>
                Use a different email
              </button>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
