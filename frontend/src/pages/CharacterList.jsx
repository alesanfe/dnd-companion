import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

export default function CharacterList() {
  const [chars, setChars] = useState([])
  const [name, setName] = useState('')
  const [err, setErr] = useState(null)

  const load = () => api.listCharacters()
    .then((r) => setChars(r.characters))
    .catch((e) => setErr(e.message))

  useEffect(() => { load() }, [])

  const create = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    await api.createCharacter(name.trim())
    setName('')
    load()
  }

  return (
    <main>
      <h1>Mis personajes</h1>
      {err && <p className="error">Backend no disponible: {err}</p>}
      <form onSubmit={create} className="row">
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Nombre rápido (vacío)" />
        <button type="submit">Crear</button>
        <Link to="/new"><button type="button">Wizard →</button></Link>
        <label className="ghost" style={{ cursor: 'pointer',
             display: 'inline-flex', alignItems: 'center',
             minHeight: 44, padding: '0 1rem', borderRadius: 6,
             border: '1px solid var(--border)' }}>
          Importar
          <input type="file" accept=".json" hidden
                 aria-label="Importar personaje desde JSON"
                 onChange={async (e) => {
                   const f = e.target.files[0]
                   if (!f) return
                   try {
                     const data = JSON.parse(await f.text())
                     await api.importCharacter(data)
                     load()
                   } catch (ex) { setErr(`Importación: ${ex.message}`) }
                 }} />
        </label>
      </form>
      {chars.length === 0 && !err && (
        <div className="card empty">
          <p><strong>Todavía no tienes personajes</strong></p>
          <p>Crea una ficha guiada con el wizard — usa datos reales
             de todas las fuentes instaladas.</p>
          <Link to="/new">
            <button className="primary">Crear personaje</button></Link>
        </div>)}
      <ul className="char-list">
        {chars.map((c) => (
          <li key={c.id} className="row">
            <Link to={`/character/${c.id}`} style={{ flex: 1 }}>{c.name}</Link>
            <span className="muted"> v{c.version} · {c.ruleset}</span>
            <button className="ghost" aria-label={`Borrar ${c.name}`}
                    onClick={async () => {
              if (!confirm(`¿Borrar a ${c.name}? Esta acción no se puede deshacer.`)) return
              await fetch(`/api/characters/${c.id}`, { method: 'DELETE' })
              load()
            }}>×</button>
          </li>
        ))}
      </ul>
    </main>
  )
}
