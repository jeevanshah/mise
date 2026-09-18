// Shared, dumb UI building blocks — no data-fetching, no routing. Mobile-
// first (locked AC: one-handed use on a phone screen down to 390px), so
// every tap target here defaults to a comfortable minimum height rather
// than shrinking to fit desktop density.

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: 'bg-[var(--color-accent)] text-[#111827] active:bg-[var(--color-accent-strong)]',
  secondary: 'bg-[var(--color-surface-raised)] text-[var(--color-text)] border border-[var(--color-border)] active:bg-[var(--color-surface-card)]',
  danger: 'bg-[var(--color-danger)] text-white active:brightness-90',
  ghost: 'bg-transparent text-[var(--color-text)] active:bg-[var(--color-surface-raised)]',
}

export function Button({
  variant = 'primary',
  fullWidth,
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; fullWidth?: boolean }) {
  return (
    <button
      className={`min-h-11 px-4 rounded-xl font-medium text-[15px] transition-colors disabled:opacity-40 disabled:pointer-events-none ${VARIANT_CLASSES[variant]} ${fullWidth ? 'w-full' : ''} ${className}`}
      {...props}
    />
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl bg-[var(--color-surface-card)] border border-[var(--color-border)] p-4 ${className}`}>
      {children}
    </div>
  )
}

export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`min-h-11 w-full rounded-lg bg-[var(--color-surface-raised)] border border-[var(--color-border)] px-3 text-[16px] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-accent)] ${className}`}
      {...props}
    />
  )
}

export function Textarea({ className = '', ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full min-h-24 rounded-lg bg-[var(--color-surface-raised)] border border-[var(--color-border)] px-3 py-2 text-[16px] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-accent)] ${className}`}
      {...props}
    />
  )
}

export function Select({ className = '', children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <select
      className={`min-h-11 w-full rounded-lg bg-[var(--color-surface-raised)] border border-[var(--color-border)] px-3 text-[16px] text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] ${className}`}
      {...props}
    >
      {children}
    </select>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-sm text-[var(--color-text-muted)] mb-1">{label}</span>
      {children}
    </label>
  )
}

type Tone = 'neutral' | 'warning' | 'danger' | 'success' | 'info'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-[var(--color-surface-raised)] text-[var(--color-text-muted)]',
  warning: 'bg-amber-950 text-amber-300',
  danger: 'bg-red-950 text-red-300',
  success: 'bg-emerald-950 text-emerald-300',
  info: 'bg-sky-950 text-sky-300',
}

// Every glyph is DISTINCT per tone, not just the color — "never color
// alone" (locked AC) so a colorblind Head Chef reading this under kitchen
// lighting still gets the signal.
const TONE_GLYPH: Record<Tone, string> = {
  neutral: '•',
  warning: '▲',
  danger: '✕',
  success: '✓',
  info: 'ℹ',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${TONE_CLASSES[tone]}`}>
      <span aria-hidden="true">{TONE_GLYPH[tone]}</span>
      {children}
    </span>
  )
}

export function SectionHeading({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">{children}</h2>
      {action}
    </div>
  )
}
