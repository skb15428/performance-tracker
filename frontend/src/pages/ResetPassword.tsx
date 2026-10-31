import { useState, type FormEvent } from 'react'
import { Button, ErrorText, Input, Label } from '../components/ui'
import { api } from '../lib/api'

/** Opened from the reset email, before signing in. */
export default function ResetPassword() {
  const token = new URLSearchParams(window.location.search).get('token') ?? ''
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/auth/reset-password', { method: 'POST', json: { token, password } })
      setDone(true)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-2xl bg-surface p-6 ring-1 ring-line">
        <h1 className="mb-4 font-display text-3xl">Choose a new password</h1>
        {done ? (
          <>
            <p className="text-sm text-muted">Your password has changed.</p>
            <a href="/" className="mt-4 inline-block text-sm text-accent-ink">
              Log in
            </a>
          </>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="block">
              <Label hint="(at least 10 characters)">New password</Label>
              <Input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
            </label>
            <ErrorText error={error} />
            <Button type="submit" loading={busy} className="w-full">
              Save password
            </Button>
          </form>
        )}
      </div>
    </div>
  )
}
