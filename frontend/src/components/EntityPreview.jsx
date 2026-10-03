import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useT, etypeLabel } from '../i18n.jsx'

/** Vista previa compacta de una entidad del compendio — se usa en
    el panel derecho del buscador. El detalle completo sigue en
    /content/:id (stat block, comparador de ediciones, colecciones). */
export default function EntityPreview({ id }) {
  const { t, tf } = useT()
  const [ent, setEnt] = useState(null)
  const [view, setView] = useState(null)
  const [block, setBlock] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    setEnt(null); setView(null); setBlock(null); setErr(null)
    api.getEntity(id).then(setEnt).catch((e) => setErr(e.message))
    api.entityRender(id).then((r) => setView(r.render)).catch(() => {})
    api.statblockPreview(id).then((r) =>
      setBlock(r.statblock)).catch(() => setBlock(null))
  }, [id])

  if (err) return <p className="error" role="alert">{err}</p>
  if (!ent) return <p className="muted" role="status">{t('common.loading')}</p>

  return (
    <div>
      <div className="row">
        <h2 style={{ flex: 1, margin: 0 }}>{ent.name}</h2>
        <Link to={`/content/${encodeURIComponent(id)}`}
              className="ghost"
              style={{ textDecoration: 'none' }}
              title={t('common.details')}>↗</Link>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {etypeLabel(t, ent.entity_type)} · {ent.ruleset} · {ent.source_id}
        {!ent.is_redistributable && ` · ${t('search.private')}`}
      </p>

      {block && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <span className="chip">CA {block.ac}</span>
          <span className="chip">PG {block.hp}</span>
          <span className="chip">CR {block.cr}</span>
          <span className="chip">{t('ent.speed')} {block.speed || '—'}</span>
        </div>)}

      {!block && view?.fields?.length > 0 && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {view.fields.slice(0, 8).map((f) => (
            <span key={f.label} className="chip">
              {f.label}: {f.value}</span>))}
        </div>)}

      {view?.desc && (
        <p className="muted">
          {view.desc.length > 500
            ? view.desc.slice(0, 500) + '…' : view.desc}</p>)}

      {block?.actions?.slice(0, 3).map((a, i) => (
        <p key={i} className="muted">
          <strong>{a.name}.</strong> {a.text}</p>))}
      {block?.actions?.length > 3 && (
        <p className="muted">… {tf('ep.moreActions',
          { n: block.actions.length - 3 })}</p>)}
    </div>
  )
}
