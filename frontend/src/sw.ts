/// <reference lib="webworker" />
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching'

declare const self: ServiceWorkerGlobalScope

cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)
self.skipWaiting()

self.addEventListener('push', (event) => {
  const data = event.data?.json() ?? {}
  event.waitUntil(
    self.registration.showNotification(data.title ?? 'GoalCoach', {
      body: data.body ?? '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: data.url ?? '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url: string = event.notification.data?.url ?? '/'
  // Links to Claude open the Claude app/site rather than navigating this app away.
  if (/^https?:\/\//.test(url) && new URL(url).origin !== self.location.origin) {
    event.waitUntil(self.clients.openWindow(url))
    return
  }
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((c) => 'focus' in c) as WindowClient | undefined
      if (existing) {
        existing.navigate(url)
        return existing.focus()
      }
      return self.clients.openWindow(url)
    }),
  )
})
