import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import type { Timeline } from '../lib/types'

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const variants: Record<Variant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-400',
  secondary:
    'bg-white text-zinc-800 ring-1 ring-zinc-200 hover:bg-zinc-50 dark:bg-zinc-900 dark:text-zinc-100 dark:ring-zinc-700 dark:hover:bg-zinc-800',
  ghost: 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800',
  danger: 'text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950',
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
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60',
        size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-sm',
        variants[variant],
        className,
      )}
    >
      {loading && <Spinner className="size-3.5" />}
      {children}
    </button>
  )
}

export function Card({ className, children, title, action }: { className?: string; children: ReactNode; title?: ReactNode; action?: ReactNode }) {
  return (
    <section className={cx('rounded-2xl bg-white p-4 ring-1 ring-zinc-200/80 sm:p-5 dark:bg-zinc-900 dark:ring-zinc-800', className)}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

// Fields fill their container unless the caller sizes them.
const sized = (className?: string) => /(^|\s)(w-|flex-|basis-|min-w-)/.test(className ?? '')
const field =
  'rounded-lg bg-white px-3 py-2 text-sm ring-1 ring-zinc-200 outline-none placeholder:text-zinc-400 focus:ring-2 focus:ring-brand-500 dark:bg-zinc-950 dark:ring-zinc-700'

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
    <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
      {children}
      {hint && <span className="ml-1 font-normal text-zinc-400">{hint}</span>}
    </span>
  )
}

export function Spinner({ className = 'size-5' }: { className?: string }) {
  return <span className={cx('inline-block animate-spin rounded-full border-2 border-current border-t-transparent', className)} />
}

export function Loading() {
  return (
    <div className="flex justify-center py-16 text-brand-600">
      <Spinner className="size-7" />
    </div>
  )
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/60 dark:text-red-300">{String((error as Error).message ?? error)}</p>
}

const badgeTones = {
  zinc: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  green: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  amber: 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  red: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
  brand: 'bg-brand-50 text-brand-700 dark:bg-brand-700/25 dark:text-brand-100',
}
export type Tone = keyof typeof badgeTones

export function Badge({ tone = 'zinc', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap', badgeTones[tone], className)}>{children}</span>
}

export function TimelineBadge({ timeline }: { timeline: Timeline | null }) {
  if (!timeline) return <Badge>Planning</Badge>
  switch (timeline.state) {
    case 'behind':
      return <Badge tone="red">Behind {timeline.behind_days}d</Badge>
    case 'ahead':
      return <Badge tone="green">Ahead {Math.abs(timeline.behind_days)}d</Badge>
    case 'not_started':
      return <Badge>Not started</Badge>
    default:
      return <Badge tone="green">On track</Badge>
  }
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800', className)}>
      <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }} />
    </div>
  )
}

export function scoreTone(score: number): string {
  if (score >= 70) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 40) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

export function ScoreRing({ score, size = 96 }: { score: number; size?: number }) {
  const r = size / 2 - 7
  const c = 2 * Math.PI * r
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={7} className="fill-none stroke-zinc-100 dark:stroke-zinc-800" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={7}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.min(score, 100) / 100)}
          className={cx('fill-none stroke-current transition-all', scoreTone(score))}
        />
      </svg>
      <span className={cx('absolute text-2xl font-bold tabular-nums', scoreTone(score))}>{Math.round(score)}</span>
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-zinc-300 px-6 py-10 text-center dark:border-zinc-700">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-zinc-500">{children}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export { cx }
