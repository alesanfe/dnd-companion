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
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.getEntity(id).then(setEnt).catch((e) => setErr(e.message))
    api.statblockPreview(id).then((r) => setBlock(r.statblock))
      .catch(() => setBlock(null))
  }, [id])

  if (err) return <main><p className="error">{err}</p></main>
  if (!ent) return <main><p className="muted">Cargando…</p></main>

  const d = ent.data || {}
  return (
    <main>
      <h1>{ent.name}</h1>
      <p className="muted">
        {ent.entity_type} · {ent.ruleset} · {ent.source_id}
        {!ent.is_redistributable && ' · contenido privado'}
      </p>

      {block && (
        <section className="card">
          <h2>Stat block</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <span className="chip">CA {block.ac}</span>
            <span className="chip">PG {block.hp}</span>
            <span className="chip">CR {block.cr}</span>
            <span className="chip">Vel {block.speed || '—'}</span>
          </div>
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
            <p key={i}><strong>{a.name}.</strong> {a.text}</p>))}
        </section>)}

      {!block && (
        <section className="card">
          <h2>Detalle</h2>
          {d.desc && <p>{Array.isArray(d.desc)
            ? d.desc.join(' ') : d.desc}</p>}
          {d.entries && <p>{d.entries.join(' ')}</p>}
          {d.description && <p>{d.description}</p>}
          {d.properties && (
            <p className="muted">
              {Object.entries(d.properties)
                .map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>)}
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
        <p className="chip">
          {Array.isArray(rolled) ? rolled.join(' — ') : String(rolled)}</p>)}
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
