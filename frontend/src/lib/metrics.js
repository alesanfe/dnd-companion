// metrics.js — métricas de uso 100% locales.
//
// El checklist UX pide medir finalización/errores/tiempo, pero la app es
// offline-first y privada por diseño: nada de esto sale del dispositivo.
// Se guarda en localStorage bajo 'dc.metrics' y se muestra en Settings.

const KEY = 'dc.metrics'
const EMPTY = () => ({
  since: Date.now(),
  pages: {},              // sección → nº de vistas
  ops: { ok: 0, error: 0, queued: 0 },
  opTypes: {},            // operation_type → { ok, error, ms, n }
  tasks: {},              // search/roll/wizard… → { ok, fail }
})

function load() {
  try {
    return { ...EMPTY(), ...(JSON.parse(localStorage.getItem(KEY)) || {}) }
  } catch { return EMPTY() }
}

function save(m) {
  try { localStorage.setItem(KEY, JSON.stringify(m)) } catch { /* lleno */ }
}

/** Vista de una sección (path de primer nivel). */
export function trackPage(section) {
  const m = load()
  m.pages[section] = (m.pages[section] || 0) + 1
  save(m)
}

/** Operación aplicada: ok / error / encolada offline + latencia media. */
export function trackOp(type, ms, outcome) {
  const m = load()
  m.ops[outcome] = (m.ops[outcome] || 0) + 1
  const t = (m.opTypes[type] ||= { ok: 0, error: 0, ms: 0, n: 0 })
  t.n++
  if (outcome === 'error') t.error++
  else if (outcome === 'ok' && ms != null) t.ms += ms
  save(m)
}

/** Tarea discreta del usuario: búsqueda, tirada, wizard, import… */
export function trackTask(task, ok = true) {
  const m = load()
  const t = (m.tasks[task] ||= { ok: 0, fail: 0 })
  t[ok ? 'ok' : 'fail']++
  save(m)
}

export function snapshot() {
  const m = load()
  const types = Object.entries(m.opTypes)
    .map(([type, t]) => ({
      type, n: t.n, error: t.error,
      avgMs: t.n - t.error ? Math.round(t.ms / (t.n - t.error)) : null,
    }))
    .sort((a, b) => b.n - a.n).slice(0, 12)
  return { ...m, opTypes: types }
}

export function clearMetrics() {
  localStorage.removeItem(KEY)
}
