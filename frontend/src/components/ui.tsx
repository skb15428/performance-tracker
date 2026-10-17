import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import type { Timeline } from '../lib/types'

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const variants: Record<Variant, string> = {
  primary: 'bg-ink text-canvas hover:opacity-90 shadow-sm',
  secondary: 'bg-surface text-ink ring-1 ring-line hover:bg-surface-2',
  ghost: 'text-muted hover:bg-surface-2 hover:text-ink',
  danger: 'text-red-600 hover:bg-red-500/10 dark:text-red-400',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-full font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm',
        variants[variant],
        className,
      )}
    >
      {loading && <Spinner className="size-3.5" />}
      {children}
    </button>
  )
}

export function Card({
  className,
  children,
  title,
  action,
  eyebrow,
}: {
  className?: string
  children: ReactNode
  title?: ReactNode
  action?: ReactNode
  eyebrow?: ReactNode
}) {
  return (
    <section className={cx('rise rounded-3xl border border-line bg-surface p-5 sm:p-6', className)}>
      {(title || action || eyebrow) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {eyebrow && <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">{eyebrow}</p>}
            {title && <h2 className="text-[15px] font-semibold text-ink">{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

const field =
  'rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-muted/70 focus:border-accent focus:ring-2 focus:ring-accent-soft'
// Fields fill their container unless the caller sizes them.
const sized = (className?: string) => /(^|\s)(w-|flex-|basis-|min-w-)/.test(className ?? '')

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(field, !sized(className) && 'w-full', className)} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(field, !sized(className) && 'w-full', 'resize-y', className)} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={cx(field, !sized(className) && 'w-full', 'pr-8', className)}>
      {children}
    </select>
  )
}

export function Label({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <span className="mb-1.5 block text-xs font-medium text-muted">
      {children}
      {hint && <span className="ml-1 font-normal opacity-70">{hint}</span>}
    </span>
  )
}

export function Spinner({ className = 'size-5' }: { className?: string }) {
  return <span className={cx('inline-block animate-spin rounded-full border-2 border-current border-t-transparent', className)} />
}

export function Loading() {
  return (
    <div className="space-y-4 py-2" aria-busy="true" aria-label="Loading">
      <div className="skeleton h-4 w-40 rounded-full" />
      <div className="skeleton h-12 w-2/3 rounded-2xl" />
      <div className="grid grid-cols-1 gap-4 pt-4 lg:grid-cols-3">
        <div className="skeleton h-64 rounded-3xl lg:col-span-2" />
        <div className="skeleton h-64 rounded-3xl" />
      </div>
    </div>
  )
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p className="rounded-2xl bg-red-500/10 px-4 py-2.5 text-sm text-red-700 dark:text-red-300">
      {String((error as Error).message ?? error)}
    </p>
  )
}

const badgeTones = {
  zinc: 'bg-surface-2 text-muted',
  green: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300',
  amber: 'bg-amber-500/14 text-amber-800 dark:text-amber-300',
  red: 'bg-red-500/12 text-red-700 dark:text-red-300',
  brand: 'bg-accent-soft text-accent-ink',
}
export type Tone = keyof typeof badgeTones

export function Badge({ tone = 'zinc', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold whitespace-nowrap', badgeTones[tone], className)}>
      {children}
    </span>
  )
}

export function TimelineBadge({ timeline }: { timeline: Timeline | null }) {
  if (!timeline) return <Badge>Setting up</Badge>
  switch (timeline.state) {
    case 'behind':
      return <Badge tone="red">● Behind {timeline.behind_days}d</Badge>
    case 'ahead':
      return <Badge tone="green">● Ahead {Math.abs(timeline.behind_days)}d</Badge>
    case 'not_started':
      return <Badge tone="brand">● Just started</Badge>
    default:
      return <Badge tone="green">● On track</Badge>
  }
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-surface-2', className)}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-brand-500 via-[#b46cff] to-[#ff8a5c] transition-all"
        style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }}
      />
    </div>
  )
}

export function scoreTone(score: number): string {
  if (score >= 70) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 40) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

export function ScoreRing({ score, size = 96 }: { score: number; size?: number }) {
  const stroke = Math.max(size / 14, 6)
  const r = size / 2 - stroke
  const c = 2 * Math.PI * r
  return (
    <div className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} className="fill-none stroke-surface-2" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.min(score, 100) / 100)}
          className={cx('fill-none stroke-current transition-all duration-700', scoreTone(score))}
        />
      </svg>
      <span className="absolute font-display tabular-nums" style={{ fontSize: size * 0.36 }}>
        {Math.round(score)}
      </span>
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-3xl border border-dashed border-line bg-surface/50 px-6 py-12 text-center">
      <p className="font-display text-2xl">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-muted">{children}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, action, eyebrow }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="mb-2 text-[11px] font-semibold tracking-[0.16em] text-muted uppercase">{eyebrow}</p>}
        <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export { cx }
