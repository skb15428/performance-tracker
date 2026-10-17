import { useState, type FormEvent } from 'react'
import { Button, ErrorText, Input, Label } from '../components/ui'
import { login } from '../lib/api'

export default function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <img src="/favicon.svg" alt="" className="mx-auto mb-3 size-12" />
          <h1 className="text-2xl font-bold tracking-tight">GoalCoach</h1>
          <p className="mt-1 text-sm text-muted">Your progress at a glance. Coaching happens in Claude.</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl bg-white p-6 ring-1 ring-line">
          <label className="block">
            <Label>Email</Label>
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </label>
          <label className="block">
            <Label>Password</Label>
            <Input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </label>
          <ErrorText error={error} />
          <Button type="submit" loading={busy} className="w-full">
            Log in
          </Button>
        </form>
      </div>
    </div>
  )
}
