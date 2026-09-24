import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api.js'

/** Vista legible de una entidad del corpus — stat block normalizado
    para monstruos, campos clave para conjuros/objetos, y el JSON
    original como fallback. */
export default function Entity() {
  const { id } = useParams()
  const [ent, setEnt] = useState(null)
  const [block, setBlock] = useState(null)
  const [view, setView] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.getEntity(id).then(setEnt).catch((e) => setErr(e.message))
    api.statblockPreview(id).then((r) => setBlock(r.statblock))
      .catch(() => setBlock(null))
    api.entityRender(id).then((r) => setView(r.render))
      .catch(() => setView(null))
  }, [id])

  // favoritos + recientes: compendio local, no del backend
  const [fav, setFav] = useState(() =>
    (JSON.parse(localStorage.getItem('dnd-favs') || '[]')).includes(id))
  useEffect(() => {
    if (!ent) return
    const rec = JSON.parse(localStorage.getItem('dnd-recents') || '[]')
    const nx = [{ id: ent.id, name: ent.name, type: ent.entity_type },
      ...rec.filter((r) => r.id !== ent.id)].slice(0, 12)
    localStorage.setItem('dnd-recents', JSON.stringify(nx))
  }, [ent?.id])
  const toggleFav = () => {
    const favs = JSON.parse(localStorage.getItem('dnd-favs') || '[]')
    const nx = fav
      ? favs.filter((f) => f.id !== id && f !== id)
      : [...favs, { id: ent.id, name: ent.name, type: ent.entity_type }]
    localStorage.setItem('dnd-favs', JSON.stringify(nx))
    setFav(!fav)
  }

  if (err) return <main><p className="error">{err}</p></main>
  if (!ent) return <main><p className="muted">Cargando…</p></main>

  const d = ent.data || {}
  return (
    <main className="wide">
      <div className="row">
        <h1 style={{ flex: 1, margin: 0 }}>{ent.name}</h1>
        <button className="ghost" aria-pressed={fav}
                aria-label="Guardar en favoritos"
                onClick={toggleFav}>
          {fav ? '★ Guardado' : '☆ Guardar'}</button>
      </div>
      <p className="muted">
        {ent.entity_type} · {ent.ruleset} · {ent.source_id}
        {!ent.is_redistributable &&
          <span className="tag-private"> · contenido privado</span>}
      </p>

      {block && (
        <section className="card">
          <h2>Stat block</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <span className="chip">CA {block.ac}</span>
            <span className="chip">PG {block.hp}</span>
            <span className="chip">CR {block.cr}</span>
            <span className="chip">Vel {block.speed || '—'}</span>
            {block.type && <span className="chip">{block.type}</span>}
            {block.size && <span className="chip">{block.size}</span>}
            {block.alignment &&
              <span className="chip">{block.alignment}</span>}
            {block.environment &&
              <span className="chip">⛰ {block.environment}</span>}
          </div>
          {[
            ['Resistencias', block.resistances],
            ['Inmunidades', block.immunities],
            ['Vulnerabilidades', block.vulnerabilities],
            ['Cond. inmunes', block.condition_immune],
          ].filter(([, v]) => v?.length).map(([label, v]) => (
            <p key={label} className="muted">
              <strong>{label}:</strong> {v.join(', ')}</p>))}
          {block.senses && <p className="muted">
            <strong>Sentidos:</strong> {block.senses}</p>}
          {block.languages && <p className="muted">
            <strong>Idiomas:</strong> {block.languages}</p>}
          {Object.keys(block.skills || {}).length > 0 && (
            <p className="muted"><strong>Habilidades:</strong>{' '}
              {Object.entries(block.skills)
                .map(([k, v]) => `${k} ${v >= 0 ? '+' : ''}${v}`)
                .join(', ')}</p>)}
          {block.spellcasting && (
            <p className="muted"><strong>Conjuros:</strong>{' '}
              {block.spellcasting.spells.join(', ')}</p>)}
          <table className="abilities">
            <thead><tr>
              {Object.keys(block.abilities).map((a) =>
                <th key={a}>{a.toUpperCase()}</th>)}
            </tr></thead>
            <tbody><tr>
              {Object.entries(block.abilities).map(([a, v]) => (
                <td key={a}>{v} ({block.saves[a] >= 0 ? '+' : ''}
                  {block.saves[a]})</td>))}
            </tr></tbody>
          </table>
          {block.actions.map((a, i) => (
            <p key={i}>
              {a.category && a.category !== 'action' &&
                <em className="muted">[{a.category}] </em>}
              <strong>{a.name}.</strong> {a.text}</p>))}
        </section>)}

      {!block && view && (
        <section className="card">
          {view.fields.length > 0 && (
            <div className="row" style={{ flexWrap: 'wrap' }}>
              {view.fields.map((f) => (
                <span key={f.label} className="chip">
                  {f.label}: {f.value}</span>))}
            </div>)}
          {view.desc && <p>{view.desc}</p>}
        </section>)}

      {ent.entity_type === 'table' && <TableView data={d} />}
    </main>
  )
}


/** Tabla aleatoria rodable — 5etools {colLabels, rows:[[…]]} y
    variantes {entries} / {table:{rows}}. */
function TableView({ data }) {
  const [rolled, setRolled] = useState(null)
  const rows = data.rows || data.table?.rows || []
  const cols = data.colLabels || data.table?.colLabels || []
  const entries = data.entries || []
  const roll = () => {
    if (rows.length) {
      setRolled(rows[Math.floor(Math.random() * rows.length)])
    } else if (entries.length) {
      setRolled(entries[Math.floor(Math.random() * entries.length)])
    }
  }
  return (
    <section className="card">
      <h2>Tabla
        {(rows.length > 0 || entries.length > 0) &&
          <button style={{ marginLeft: '1rem' }}
                  onClick={roll}>Tirar</button>}</h2>
      {rolled && (
        <div className="row">
          <p className="chip">
            {Array.isArray(rolled) ? rolled.join(' — ') : String(rolled)}</p>
          <button className="ghost" onClick={() => {
            const txt = Array.isArray(rolled)
              ? rolled.join(' — ') : String(rolled)
            navigator.clipboard?.writeText(txt)
          }}>Copiar</button>
        </div>)}
      {cols.length > 0 && rows.length > 0 && (
        <table>
          <thead><tr>{cols.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
          <tbody>
            {rows.slice(0, 40).map((r, i) => (
              <tr key={i}>
                {(Array.isArray(r) ? r : [r]).map((cell, j) =>
                  <td key={j}>{typeof cell === 'object'
                    ? JSON.stringify(cell) : String(cell)}</td>)}
              </tr>))}
          </tbody>
        </table>)}
      {rows.length === 0 && entries.length > 0 && (
        <ul>{entries.slice(0, 40).map((e, i) =>
          <li key={i}>{typeof e === 'object'
            ? JSON.stringify(e) : String(e)}</li>)}</ul>)}
    </section>
  )
}
