import { api } from './api'

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return
  const url = import.meta.env.DEV ? '/dev-sw.js?dev-sw' : '/sw.js'
  await navigator.serviceWorker.register(url, { type: import.meta.env.DEV ? 'module' : 'classic' }).catch(() => {})
  // When an updated service worker takes control, reload once so the page shows the new version.
  let reloaded = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!reloaded && !import.meta.env.DEV) {
      reloaded = true
      window.location.reload()
    }
  })
}

export async function enablePush(vapidPublicKey: string): Promise<void> {
  if (!pushSupported()) throw new Error('This browser does not support push notifications. On iPhone, add the app to your Home Screen first.')
  if (!vapidPublicKey) throw new Error('Push is not configured on the server (missing VAPID keys).')
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('Notifications were not allowed.')
  const reg = await navigator.serviceWorker.ready
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(vapidPublicKey) }))
  const json = sub.toJSON()
  await api('/push/subscribe', { method: 'POST', json: { endpoint: json.endpoint, keys: json.keys } })
}
