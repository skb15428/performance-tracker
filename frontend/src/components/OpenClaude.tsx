import { claudeLink } from '../lib/claude'
import { cx } from './ui'

export default function OpenClaude({
  message,
  children,
  variant = 'primary',
  className,
}: {
  message: string
  children: React.ReactNode
  variant?: 'primary' | 'secondary'
  className?: string
}) {
  return (
    <a
      href={claudeLink(message)}
      target="_blank"
      rel="noreferrer"
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors',
        variant === 'primary'
          ? 'bg-brand-600 text-white hover:bg-brand-700'
          : 'bg-white text-zinc-800 ring-1 ring-zinc-200 hover:bg-zinc-50 dark:bg-zinc-900 dark:text-zinc-100 dark:ring-zinc-700 dark:hover:bg-zinc-800',
        className,
      )}
    >
      {children} <span aria-hidden>↗</span>
    </a>
  )
}
