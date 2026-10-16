const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8000'
const TOKEN_KEY = 'goalcoach.token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail.replaceAll('_', ' ').toLowerCase()
    if (Array.isArray(detail)) return detail.map((d) => d.msg ?? JSON.stringify(d)).join('; ')
  }
  return fallback
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let body = init.body
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(init.json)
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers, body })
  if (res.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event('goalcoach:logout'))
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export async function login(email: string, password: string) {
  const form = new URLSearchParams({ username: email, password })
  const res = await fetch(`${BASE}/auth/jwt/login`, { method: 'POST', body: form })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, 'Login failed'))
  setToken(data.access_token)
}
