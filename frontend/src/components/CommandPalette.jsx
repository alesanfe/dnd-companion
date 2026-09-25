import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useT } from '../i18n.jsx'

/** Ctrl/Cmd+K — búsqueda global del corpus desde cualquier página.
    Flechas para navegar, Enter abre el resultado, Esc cierra. */
export default function CommandPalette() {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [idx, setIdx] = useState(0)
  const nav = useNavigate()
  const inputRef = useRef(null)

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault(); setOpen((o) => !o)
      } else if (e.key === 'Escape' && open) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  useEffect(() => { if (open) inputRef.current?.focus() }, [open])
  useEffect(() => {
    if (!q.trim()) { setResults([]); return }
    const t = setTimeout(() => {
      api.search(q).then((r) => {
        setResults((r.results || []).slice(0, 8)); setIdx(0)
      }).catch(() => {})
    }, 200)
    return () => clearTimeout(t)
  }, [q])

  if (!open) return null
  const pick = (r) => {
    setOpen(false); setQ(''); setResults([])
    nav(`/content/${encodeURIComponent(r.id)}`)
  }
  return (
    <div role="dialog" aria-modal="true" aria-label="Búsqueda global"
         style={{ position: 'fixed', inset: 0, zIndex: 100,
                  background: 'rgba(0,0,0,.5)' }}
         onClick={() => setOpen(false)}>
      <div style={{ maxWidth: 560, margin: '15vh auto 0',
                    background: 'var(--card-raised)',
                    borderRadius: 10, padding: '0.8rem',
                    border: '1px solid var(--border)' }}
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
            <li key={r.id}>
              <button className="ghost"
                      style={{ width: '100%', textAlign: 'left',
                               borderColor: i === idx
                                 ? 'var(--accent)' : 'transparent' }}
                      onClick={() => pick(r)}
                      onMouseEnter={() => setIdx(i)}>
                <strong>{r.name}</strong>{' '}
                <span className="muted">
                  {r.entity_type} · {r.source_id}</span>
              </button>
            </li>))}
        </ul>
      </div>
    </div>
  )
}
