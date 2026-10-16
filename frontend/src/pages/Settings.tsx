import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button, Card, ErrorText, Input, Label, Loading, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { enablePush, pushSupported } from '../lib/push'
import type { Settings } from '../lib/types'

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/me/settings') })
  const [form, setForm] = useState({ name: '', timezone: '', reminder_time: '21:30', daily_available_hours: 3, morning_push: false })
  const [pushMsg, setPushMsg] = useState<string | null>(null)

  useEffect(() => {
    if (data)
      setForm({
        name: data.name ?? '',
        timezone: data.timezone,
        reminder_time: data.reminder_time,
        daily_available_hours: data.daily_available_hours,
        morning_push: data.morning_push,
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
              <Label hint="(split across goals by priority)">Hours per day for your goals</Label>
              <Input type="number" min={0.5} max={16} step={0.5} value={form.daily_available_hours} onChange={(e) => setForm({ ...form, daily_available_hours: Number(e.target.value) })} />
            </label>
            <label>
              <Label>Time zone</Label>
              <Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
              {browserTz !== form.timezone && (
                <button type="button" className="mt-1 text-xs text-brand-600" onClick={() => setForm({ ...form, timezone: browserTz })}>
                  Use {browserTz}
                </button>
              )}
            </label>
            <label>
              <Label>Nightly reminder</Label>
              <Input type="time" value={form.reminder_time} onChange={(e) => setForm({ ...form, reminder_time: e.target.value })} />
            </label>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" className="size-4 accent-brand-600" checked={form.morning_push} onChange={(e) => setForm({ ...form, morning_push: e.target.checked })} />
              Also send me today's plan at 7:00 am
            </label>
            <div className="flex justify-end sm:col-span-2">
              <Button type="submit" loading={save.isPending}>
                {save.isSuccess ? 'Saved ✓' : 'Save'}
              </Button>
            </div>
          </form>
        </Card>

        <Card title="Notifications">
          <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-300">
            Get a nightly nudge to log your day. On iPhone, first use Share → Add to Home Screen, then enable notifications from the installed app.
          </p>
          <Button variant="secondary" loading={push.isPending} onClick={() => push.mutate()} disabled={!pushSupported()}>
            {pushSupported() ? 'Enable notifications' : 'Not supported in this browser'}
          </Button>
          {pushMsg && <p className="mt-2 text-sm text-emerald-600">{pushMsg}</p>}
          <ErrorText error={push.error} />
        </Card>

      </div>
    </>
  )
}
