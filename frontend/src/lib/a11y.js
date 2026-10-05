/** Navegación por flechas en tablists — patrón ARIA APG:
    ←/→ mueven el foco entre pestañas, Home/End van a los extremos.
    Uso: <nav role="tablist" onKeyDown={onTabsKeyDown}> */
export function onTabsKeyDown(e) {
  const k = e.key
  if (k !== 'ArrowRight' && k !== 'ArrowLeft' &&
      k !== 'ArrowUp' && k !== 'ArrowDown' &&
      k !== 'Home' && k !== 'End') return
  const tabs = [...e.currentTarget.querySelectorAll('[role="tab"]')]
  const i = tabs.indexOf(document.activeElement)
  if (i === -1) return
  e.preventDefault()
  const next =
    k === 'ArrowRight' ? (i + 1) % tabs.length :
    k === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length :
    k === 'Home' ? 0 :
    k === 'End' ? tabs.length - 1 : i
  tabs[next].focus()
}
