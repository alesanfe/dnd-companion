import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { useT } from '../../i18n.jsx'

/** Resuelve ids de entidad → nombres en caché local (una sola
    petición por id, sin reordenar). Para mostrar ids del modelo
    como 'srd-2014:college-of-lore' en lugar de crudo. */
export function useEntityNames(ids) {
  const [names, setNames] = useState({})
  const key = (ids || []).filter(Boolean).join('|')
  useEffect(() => {
    for (const id of ids || []) {
      if (!id || names[id]) continue
      api.getEntity(id)
        .then((e) => setNames((n) => ({ ...n, [id]: e.name || id })))
        .catch(() => setNames((n) => ({ ...n, [id]: id.split(':').pop() })))
    }
  }, [key])
  return names
}

export function ItemPicker({ onPick }) {
  const { t } = useT()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [err, setErr] = useState(null)
  const go = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    try {
      const r = await api.search(q.trim())
      setHits(r.results
        .filter((h) => ['item', 'magic-item', 'equipment']
          .includes(h.entity_type))
        .slice(0, 12))
      setErr(null)
    } catch (ex) { setErr(ex.message) }
  }
  return (
    <div>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('pick.itemPh')} />
        <button type="submit">{t('search.button')}</button>
      </form>
      {err && <p className="error" role="alert">{err}</p>}
      {hits.length > 0 && (
        <ul>
          {hits.map((h) => (
            <li key={h.id} className="row">
              <span style={{ flex: 1 }}>{h.name}
                <span className="muted"> · {h.source_id}</span></span>
              <button onClick={() => { onPick(h); setHits([]) }}>
                {t('common.add')}</button>
            </li>))}
        </ul>)}
    </div>
  )
}


export function SpellPicker({ onPick, entityType = 'spell',
                      verb,
                      placeholder,
                      forClass }) {
  const { t, tf } = useT()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [onlyClass, setOnlyClass] = useState(Boolean(forClass))
  const [err, setErr] = useState(null)
  const go = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    try {
      const r = await api.search(q.trim(), entityType, undefined,
                                 onlyClass ? forClass : undefined)
      setHits(r.results.slice(0, 12))
      setErr(null)
    } catch (ex) { setErr(ex.message) }
  }
  return (
    <div>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={placeholder || t('pick.searchPh')} />
        <button type="submit">{t('search.button')}</button>
      </form>
      {err && <p className="error" role="alert">{err}</p>}
      {forClass && (
        <label className="row muted" style={{ fontSize: '.85em' }}>
          <input type="checkbox" checked={onlyClass}
                 onChange={(e) => setOnlyClass(e.target.checked)} />
          {tf('pick.onlyClass', { cls: forClass })}
        </label>)}
      {hits.length > 0 && (
        <ul>
          {hits.map((h) => (
            <li key={h.id} className="row">
              <span style={{ flex: 1 }}>{h.name}
                <span className="muted"> · {h.source_id}</span></span>
              <button onClick={() => { onPick(h.id); setHits([]) }}>
                {verb || t('common.add')}</button>
            </li>))}
        </ul>)}
    </div>
  )
}
