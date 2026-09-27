import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useT } from '../i18n.jsx'

const DICE_RE = /^\s*\d*d\d+([+\-dkslh!a-z0-9]*)\s*$/i

/** Ctrl/Cmd+K — búsqueda y acciones globales desde cualquier página.
    Combina personajes, campañas, contenido del corpus y acciones
    rápidas (crear, navegar, tirar dados). Flechas, Enter, Esc. */
export default function CommandPalette() {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [chars, setChars] = useState([])
  const [camps, setCamps] = useState([])
  const [ents, setEnts] = useState([])  // entidades de campaña
  const [results, setResults] = useState([])   // {kind,label,sub,run}
  const [idx, setIdx] = useState(0)
  const nav = useNavigate()
  const inputRef = useRef(null)
  const dlgRef = useRef(null)

  // focus trap: Tab/Shift+Tab cicla dentro del diálogo
  const trapTab = (e) => {
    if (e.key !== 'Tab' || !dlgRef.current) return
    const els = dlgRef.current.querySelectorAll(
      'input, button, a[href], [tabindex]:not([tabindex="-1"])')
    if (!els.length) return
    const first = els[0], last = els[els.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus()
    }
  }

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault(); setOpen((o) => !o)
      } else if (e.key === 'Escape' && open) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // al abrir: foco + cachear listas locales (baratas)
  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    api.listCharacters().then((r) =>
      setChars(r.characters || [])).catch(() => setChars([]))
    api.listCampaigns().then((r) => {
      const cs = r.campaigns || []
      setCamps(cs)
      // entidades del mundo indexadas en el omnibox (estilo Kanka)
      // — el servidor ya filtra por rol: un jugador no ve las
      // entidades dm-only aunque conozca el nombre
      Promise.all(cs.slice(0, 8).map((cp) =>
        api.listEntities(cp.id)
          .then((x) => (x.entities || []).map((e) =>
            ({ ...e, campaign_name: cp.name })))
          .catch(() => [])))
        .then((lists) => setEnts(lists.flat()))
    }).catch(() => setCamps([]))
  }, [open])

  const go = (to) => { setOpen(false); setQ(''); setResults([]); nav(to) }

  const ACTIONS = [
    { label: `＋ ${t('create.character')}`, sub: 'wizard', run: () => go('/new') },
    { label: `＋ ${t('create.campaign')}`, sub: 'mesa', run: () => go('/dm') },
    { label: t('nav.home'), sub: '/', run: () => go('/') },
    { label: t('nav.sheets'), sub: '/characters', run: () => go('/characters') },
    { label: t('nav.campaigns'), sub: '/campaigns', run: () => go('/campaigns') },
    { label: t('nav.compendium'), sub: '/search', run: () => go('/search') },
    { label: t('nav.dm'), sub: '/dm', run: () => go('/dm') },
    { label: t('set.title'), sub: '/settings', run: () => go('/settings') },
  ]

  useEffect(() => {
    const term = q.trim()
    const low = term.toLowerCase()
    const items = []

    // acciones de navegación/creación filtradas por texto
    for (const a of ACTIONS)
      if (term && a.label.toLowerCase().includes(low))
        items.push({ kind: 'action', ...a })

    // tirada directa si la consulta es una expresión de dados
    if (DICE_RE.test(term)) {
      const expression = term
      items.push({
        kind: 'action',
        label: `🎲 ${t('dash.roll')} ${expression}`,
        sub: 'dice',
        run: async () => {
          try {
            const r = await api.roll(expression)
            setResults([{ kind: 'roll', label:
              `${expression} → ${r.rolls?.join(' + ') || ''} = ${r.total}`,
              sub: '', run: () => {} }])
            setIdx(0)
          } catch { /* expresión inválida */ }
        },
      })
    }

    // personajes y campañas locales
    if (term) {
      for (const c of chars)
        if (c.name.toLowerCase().includes(low))
          items.push({ kind: 'char', label: c.name,
            sub: `${(c.class_names || []).join('/') || '—'} · ${t('sheet.lvlShort')}${c.level || 1}`,
            run: () => go(`/character/${c.id}`) })
      for (const c of camps)
        if (c.name.toLowerCase().includes(low))
          items.push({ kind: 'campaign', label: c.name,
            sub: c.ruleset ? t(`ruleset.${c.ruleset}`) : t('camp.name'),
            run: () => go(`/campaign/${c.id}`) })
      // entidades de campaña (PNJ, lugares…) → deep-link al mundo
      let ec = 0
      for (const e of ents) {
        if (ec >= 8 || !(e.name || '').toLowerCase().includes(low))
          continue
        ec++
        items.push({ kind: 'entity', label: e.name,
          sub: `${e.kind} · ${e.campaign_name || ''}`,
          run: () => go(`/campaign/${e.campaign_id}#ent-${e.id}`) })
      }
    }

    setResults(items)
    setIdx(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, chars, camps, ents])

  // contenido del corpus (debounced) — se anexa a los resultados
  // locales; ignora respuestas si la consulta ya cambió (carrera)
  const termRef = useRef('')
  useEffect(() => {
    const term = q.trim()
    termRef.current = term
    if (!term) return
    const tm = setTimeout(() => {
      api.search(term).then((r) => {
        if (termRef.current !== term) return   // respuesta obsoleta
        const content = (r.results || []).slice(0, 6).map((x) => ({
          kind: 'content', label: x.name,
          sub: `${x.entity_type} · ${x.source_id}`,
          run: () => go(`/content/${encodeURIComponent(x.id)}`),
        }))
        setResults((prev) => [
          ...prev.filter((p) => p.kind !== 'content'), ...content])
      }).catch(() => {})
    }, 200)
    return () => clearTimeout(tm)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  if (!open) return null
  const pick = (r) => r.run()

  const KIND_LABEL = {
    action: '→', char: '👤', campaign: '🗺', content: '📖',
    entity: '📌', roll: '🎲',
  }

  return (
    <div role="dialog" aria-modal="true" aria-label={t('palette.aria')}
         style={{ position: 'fixed', inset: 0, zIndex: 100,
                  background: 'rgba(0,0,0,.5)' }}
         onClick={() => setOpen(false)}>
      <div ref={dlgRef}
           style={{ maxWidth: 560, margin: '15vh auto 0',
                    background: 'var(--card-raised)',
                    borderRadius: 10, padding: '0.8rem',
                    border: '1px solid var(--border)' }}
           onKeyDown={trapTab}
           onClick={(e) => e.stopPropagation()}>
        <input ref={inputRef} value={q}
               placeholder={t('palette.placeholder')}
               aria-label={t('search.title')}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => {
                 if (e.key === 'ArrowDown') {
                   e.preventDefault()
                   setIdx((i) => Math.min(i + 1, results.length - 1))
                 } else if (e.key === 'ArrowUp') {
                   e.preventDefault()
                   setIdx((i) => Math.max(i - 1, 0))
                 } else if (e.key === 'Enter' && results[idx]) {
                   pick(results[idx])
                 }
               }} />
        <ul style={{ listStyle: 'none', margin: '.5rem 0 0',
                     padding: 0 }}>
          {results.map((r, i) => (
            <li key={r.kind + i}>
              <button className="ghost"
                      style={{ width: '100%', textAlign: 'left',
                               borderColor: i === idx
                                 ? 'var(--accent)' : 'transparent' }}
                      onClick={() => pick(r)}
                      onMouseEnter={() => setIdx(i)}>
                <span aria-hidden="true">{KIND_LABEL[r.kind]} </span>
                <strong>{r.label}</strong>{' '}
                <span className="muted">{r.sub}</span>
              </button>
            </li>))}
        </ul>
        {q.trim() && results.length === 0 && (
          <p className="muted" style={{ margin: '.5rem 0 0' }}>
            {t('search.empty')}</p>)}
      </div>
    </div>
  )
}
