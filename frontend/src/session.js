// Sesión local: token Bearer + preferencias de accesibilidad.
const K = { token: 'dc.token', user: 'dc.user', theme: 'dc.theme',
            font: 'dc.font', motion: 'dc.motion' }

export function getToken() { return localStorage.getItem(K.token) }
export function currentUser() {
  const u = localStorage.getItem(K.user)
  return u ? JSON.parse(u) : null
}
export function setAuth(token, user) {
  localStorage.setItem(K.token, token)
  localStorage.setItem(K.user, JSON.stringify(user))
}
export function clearAuth() {
  localStorage.removeItem(K.token); localStorage.removeItem(K.user)
}

// --- preferencias visuales -------------------------------------------
export function getPrefs() {
  return { theme: localStorage.getItem(K.theme) || 'dark',
           font: localStorage.getItem(K.font) || 'md',
           motion: localStorage.getItem(K.motion) || 'on' }
}
export function setPref(key, value) {
  localStorage.setItem(K[key] ?? key, value)
  applyPrefs(getPrefs())
}
export function applyPrefs(p) {
  const el = document.documentElement
  el.dataset.theme = p.theme
  el.dataset.font = p.font
  el.dataset.motion = p.motion
}
applyPrefs(getPrefs())
