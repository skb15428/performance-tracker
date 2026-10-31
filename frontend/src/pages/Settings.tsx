import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button, Card, ErrorText, Input, Label, Loading, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { enablePush, pushSupported } from '../lib/push'
import type { AppStatus, Settings } from '../lib/types'

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8000'

const BACKUP_DAYS = 30
const backupIsRecent = (at: string | null) => !!at && Date.now() - new Date(at).getTime() < BACKUP_DAYS * 86_400_000

const when = (at: string | null) => (at ? new Date(at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Never')

function Status({ status }: { status: AppStatus }) {
  const rows: [string, string, boolean][] = [
    ['Scheduler last ran', when(status.scheduler_last_run), !!status.scheduler_last_run],
    ['Email reminders', status.email_enabled ? 'Ready' : 'Not set up: add a RESEND_API_KEY on Render', status.email_enabled],
    ['Calendar', status.calendar_connected ? 'Link created' : 'Not connected yet', status.calendar_connected],
    ['Notifications', status.push_devices ? `${status.push_devices} device${status.push_devices > 1 ? 's' : ''}` : 'No devices', status.push_devices > 0],
    ['Your last download', when(status.last_backup), backupIsRecent(status.last_backup)],
    ['Errors in the last 7 days', String(status.errors_last_7_days), status.errors_last_7_days === 0],
  ]
  return (
    <Card title="Is everything working?">
      <ul className="space-y-2 text-sm">
        {rows.map(([label, value, ok]) => (
          <li key={label} className="flex items-baseline justify-between gap-3">
            <span>{label}</span>
            <span className={ok ? 'text-right text-emerald-700 dark:text-emerald-300' : 'text-right text-amber-700 dark:text-amber-300'}>{value}</span>
          </li>
        ))}
      </ul>
      {status.last_error && <p className="mt-3 rounded-2xl bg-surface-2 px-3 py-2 text-xs break-words text-muted">Latest error ({status.last_error.where}): {status.last_error.error}</p>}
      {status.default_secrets && <p className="mt-3 text-sm text-red-700 dark:text-red-300">The server is using a default secret. Set JWT_SECRET and JOBS_SECRET on Render.</p>}
    </Card>
  )
}

function CalendarCard({ token }: { token: string | null }) {
  const qc = useQueryClient()
  const make = useMutation({
    mutationFn: () => api('/me/calendar-token', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries(),
  })
  const link = token && `${API_URL}/calendar/${token}.ics`
  const replace = () => window.confirm('Your calendar will stop updating until you add the new link. Replace it?') && make.mutate()
  return (
    <Card title="Calendar">
      <p className="mb-3 text-sm text-muted">Puts your plan in your phone's calendar, with an alert 10 minutes before each block and a nightly "Log your day".</p>
      {link ? (
        <>
          <a href={link.replace(/^https?:/, 'webcal:')} className="inline-flex rounded-full bg-ink px-4 py-2 text-sm font-medium text-canvas">
            Add to my calendar
          </a>
          <p className="mt-3 text-xs break-all text-muted">{link}</p>
          <p className="mt-2 text-xs text-muted">
            Keep this link private: anyone with it can see your plan.{' '}
            <button className="underline hover:text-ink" onClick={replace}>
              Replace it
            </button>
          </p>
        </>
      ) : (
        <Button variant="secondary" loading={make.isPending} onClick={() => make.mutate()}>
          Create my calendar link
        </Button>
      )}
      <ErrorText error={make.error} />
    </Card>
  )
}

function PasswordCard() {
  const [form, setForm] = useState({ current_password: '', new_password: '' })
  const save = useMutation({
    mutationFn: () => api('/me/password', { method: 'PUT', json: form }),
    onSuccess: () => setForm({ current_password: '', new_password: '' }),
  })
  return (
    <Card title="Password">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <label className="block">
          <Label>Current password</Label>
          <Input type="password" required autoComplete="current-password" value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} />
        </label>
        <label className="block">
          <Label hint="(at least 10 characters)">New password</Label>
          <Input type="password" required minLength={10} autoComplete="new-password" value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} />
        </label>
        <ErrorText error={save.error} />
        <Button type="submit" variant="secondary" loading={save.isPending}>
          {save.isSuccess ? 'Changed ✓' : 'Change password'}
        </Button>
      </form>
    </Card>
  )
}

function YourData() {
  const qc = useQueryClient()
  const download = useMutation({
    mutationFn: () => api<object>('/me/export'),
    onSuccess: (data) => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `goalcoach-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      qc.invalidateQueries({ queryKey: ['status'] })
    },
  })
  return (
    <Card title="Your data">
      <p className="mb-3 text-sm text-muted">Download everything as one file, about once a month. Keep it somewhere safe: it holds your goals and logs, and it can be restored if the database is ever lost.</p>
      <Button variant="secondary" loading={download.isPending} onClick={() => download.mutate()}>
        Download my data
      </Button>
      <ErrorText error={download.error} />
    </Card>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/me/settings') })
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: () => api<AppStatus>('/me/status') })
  const [form, setForm] = useState({ name: '', timezone: '', reminder_time: '21:30', daily_available_hours: 3, morning_push: false, email_reminders: true })
  const [pushMsg, setPushMsg] = useState<string | null>(null)

  useEffect(() => {
    if (data)
      setForm({
        name: data.name ?? '',
        timezone: data.timezone,
        reminder_time: data.reminder_time,
        daily_available_hours: data.daily_available_hours,
        morning_push: data.morning_push,
        email_reminders: data.email_reminders,
      })
  }, [data])

  const save = useMutation({
    mutationFn: (body: object) => api<Settings>('/me/settings', { method: 'PUT', json: body }),
    onSuccess: (s) => {
      qc.setQueryData(['settings'], s)
      qc.invalidateQueries({ queryKey: ['goals'] })
    },
  })
  const push = useMutation({
    mutationFn: async () => {
      await enablePush(data!.vapid_public_key)
      return api<{ sent: number }>('/push/test', { method: 'POST' })
    },
    onSuccess: (r) => setPushMsg(r.sent ? 'Notifications enabled. Check for a test notification.' : 'Subscribed, but the test push could not be sent.'),
  })

  if (isLoading || !data) return <Loading />
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone

  return (
    <>
      <PageHeader title="Settings" subtitle={data.email} />
      <div className="space-y-4">
        <Card title="Your time">
          <form
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate(form)
            }}
          >
            <label>
              <Label>Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              <Label hint="(only for goals without a routine)">Hours per day for your goals</Label>
              <Input type="number" min={0.5} max={16} step={0.5} value={form.daily_available_hours} onChange={(e) => setForm({ ...form, daily_available_hours: Number(e.target.value) })} />
            </label>
            <label>
              <Label>Time zone</Label>
              <Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
              {browserTz !== form.timezone && (
                <button type="button" className="mt-1 text-xs text-accent-ink" onClick={() => setForm({ ...form, timezone: browserTz })}>
                  Use {browserTz}
                </button>
              )}
            </label>
            <label>
              <Label>Nightly reminder</Label>
              <Input type="time" value={form.reminder_time} onChange={(e) => setForm({ ...form, reminder_time: e.target.value })} />
            </label>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={form.morning_push} onChange={(e) => setForm({ ...form, morning_push: e.target.checked })} />
              Also send me today's plan at 7:00 am
            </label>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" className="size-4 accent-[var(--accent)]" disabled={!data?.email_enabled} checked={!!data?.email_enabled && form.email_reminders} onChange={(e) => setForm({ ...form, email_reminders: e.target.checked })} />
              Email me the nightly reminder
              {data && !data.email_enabled && <span className="text-xs text-muted">(email isn't set up yet)</span>}
            </label>
            <div className="flex justify-end sm:col-span-2">
              <Button type="submit" loading={save.isPending}>
                {save.isSuccess ? 'Saved ✓' : 'Save'}
              </Button>
            </div>
          </form>
        </Card>

        <Card title="Notifications">
          <p className="mb-3 text-sm text-muted">
            Get a nightly nudge to log your day. On iPhone, first use Share → Add to Home Screen, then enable notifications from the installed app.
          </p>
          <Button variant="secondary" loading={push.isPending} onClick={() => push.mutate()} disabled={!pushSupported()}>
            {pushSupported() ? 'Enable notifications' : 'Not supported in this browser'}
          </Button>
          {pushMsg && <p className="mt-2 text-sm text-emerald-600">{pushMsg}</p>}
          <ErrorText error={push.error} />
        </Card>

        <CalendarCard token={data?.calendar_token ?? null} />
        <PasswordCard />
        <YourData />
        {status && <Status status={status} />}
      </div>
    </>
  )
}
