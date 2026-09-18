import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <div
      className={`h-5 w-5 rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-accent)] animate-spin ${className}`}
      role="status"
      aria-label="Loading"
    />
  )
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 justify-center text-[var(--color-text-muted)]">
      <Spinner />
      <span>{label}</span>
    </div>
  )
}

export function ErrorBlock({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError
    ? typeof error.detail === 'string' ? error.detail : error.message
    : error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="rounded-xl border border-red-900 bg-red-950/50 p-4 text-red-300">
      <p className="font-medium mb-1">✕ {message}</p>
      {onRetry && (
        <button onClick={onRetry} className="text-sm underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ icon = '—', title, hint }: { icon?: string; title: string; hint?: string }) {
  return (
    <div className="text-center py-10 text-[var(--color-text-muted)]">
      <div className="text-2xl mb-2" aria-hidden="true">{icon}</div>
      <p className="font-medium text-[var(--color-text)]">{title}</p>
      {hint && <p className="text-sm mt-1">{hint}</p>}
    </div>
  )
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 mb-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="text-sm text-[var(--color-text-muted)] mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}
