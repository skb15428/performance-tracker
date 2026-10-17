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
        'inline-flex items-center justify-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition',
        variant === 'primary' ? 'bg-ink text-canvas shadow-sm hover:opacity-90' : 'bg-surface text-ink ring-1 ring-line hover:bg-surface-2',
        className,
      )}
    >
      {children} <span aria-hidden>↗</span>
    </a>
  )
}
