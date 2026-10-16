import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../lib/api'
import type { Dashboard } from '../lib/types'
import { cx } from './ui'

const icons: Record<string, ReactNode> = {
  today: <path d="M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10" />,
  log: <path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4 12.5-12.5z" />,
  goals: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </>
  ),
  trends: <path d="M3 17l6-6 4 4 8-8M15 7h6v6" />,
  weekly: (
    <>
      <rect x="3" y="4" width="18" height="17" rx="2" />
      <path d="M3 9h18M8 2v4M16 2v4" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
    </>
  ),
}

const NAV = [
  { to: '/', label: 'Today', icon: 'today', end: true },
  { to: '/log', label: 'Day', icon: 'log' },
  { to: '/goals', label: 'Goals', icon: 'goals' },
  { to: '/trends', label: "What's new", icon: 'trends' },
  { to: '/weekly', label: 'Weekly', icon: 'weekly' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      {icons[name]}
    </svg>
  )
}

export default function Layout({ onLogout }: { onLogout: () => void }) {
  const { data } = useQuery({ queryKey: ['dashboard'], queryFn: () => api<Dashboard>('/dashboard/summary') })
  const badge = (icon: string) => (icon === 'trends' && data?.new_trends ? data.new_trends : 0)

  return (
    <div className="min-h-dvh md:flex">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-zinc-200 bg-white px-3 py-5 md:flex dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-6 flex items-center gap-2 px-2">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span className="text-lg font-bold tracking-tight">GoalCoach</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cx(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100'
                    : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800',
                )
              }
            >
              <Icon name={n.icon} />
              <span className="flex-1">{n.label}</span>
              {badge(n.icon) > 0 && <span className="rounded-full bg-brand-600 px-1.5 text-xs text-white">{badge(n.icon)}</span>}
            </NavLink>
          ))}
        </nav>
        <button onClick={onLogout} className="rounded-lg px-3 py-2 text-left text-sm text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">
          Log out
        </button>
      </aside>

      <main className="mx-auto w-full max-w-5xl px-4 pt-5 pb-28 sm:px-6 md:pb-10 md:pt-8">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-6 border-t border-zinc-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-zinc-800 dark:bg-zinc-900/95">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              cx('relative flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium', isActive ? 'text-brand-600 dark:text-brand-400' : 'text-zinc-500')
            }
          >
            <Icon name={n.icon} />
            <span className="truncate">{n.label.split(' ')[0]}</span>
            {badge(n.icon) > 0 && <span className="absolute top-1 right-1/4 size-2 rounded-full bg-brand-600" />}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
