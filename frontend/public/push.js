/* Web Push handler — importado por el SW generado (workbox
   importScripts). El payload JSON llega del backend
   (/api/push): {title, body, url}. */
self.addEventListener('push', (e) => {
  const d = e.data ? e.data.json() : {}
  e.waitUntil(self.registration.showNotification(
    d.title || 'D&D Companion',
    { body: d.body || '', icon: '/icon-192.png',
      data: { url: d.url || '/' } }))
})

self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const url = e.notification.data?.url || '/'
  e.waitUntil(clients.matchAll({ type: 'window' })
    .then((cs) => cs.length
      ? cs[0].focus().then((c) => c.navigate(url))
      : clients.openWindow(url)))
})
