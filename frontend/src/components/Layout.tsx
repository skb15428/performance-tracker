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
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col px-4 py-6 md:flex">
        <div className="mb-8 flex items-center gap-2.5 px-3">
          <img src="/favicon.svg" alt="" className="size-8 rounded-xl" />
          <span className="font-display text-2xl tracking-tight">GoalCoach</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cx(
                  'flex items-center gap-3 rounded-full px-4 py-2.5 text-sm font-medium transition',
                  isActive ? 'bg-ink text-canvas shadow-sm' : 'text-muted hover:bg-surface hover:text-ink',
                )
              }
            >
              <Icon name={n.icon} />
              <span className="flex-1">{n.label}</span>
              {badge(n.icon) > 0 && <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold text-white">{badge(n.icon)}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="rounded-3xl border border-line bg-surface p-4 text-xs text-muted">
          <p className="mb-1 font-semibold text-ink">Your coach lives in Claude</p>
          Log your day, plan and replan by chatting with Claude. This dashboard shows the results.
        </div>
        <button onClick={onLogout} className="mt-3 rounded-full px-4 py-2 text-left text-sm text-muted hover:bg-surface hover:text-ink">
          Log out
        </button>
      </aside>

      <main className="bg-glow mx-auto w-full max-w-6xl px-4 pt-6 pb-32 sm:px-8 md:rounded-l-[2rem] md:border-l md:border-line md:bg-surface/40 md:pt-10 md:pb-12">
        <Outlet />
      </main>

      <nav className="fixed inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-20 grid grid-cols-6 rounded-full border border-line bg-surface/80 p-1.5 shadow-lg shadow-black/5 backdrop-blur-xl md:hidden">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              cx(
                'relative flex flex-col items-center gap-0.5 rounded-full py-1.5 text-[10px] font-medium transition',
                isActive ? 'bg-ink text-canvas' : 'text-muted',
              )
            }
          >
            <Icon name={n.icon} />
            <span className="truncate">{n.label.split(' ')[0]}</span>
            {badge(n.icon) > 0 && <span className="absolute top-1 right-1/4 size-2 rounded-full bg-accent" />}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
