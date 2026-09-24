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
               placeholder="Nombre del personaje" />
        <button type="submit">Crear</button>
      </form>
      <ul className="char-list">
        {chars.map((c) => (
          <li key={c.id}>
            <Link to={`/character/${c.id}`}>{c.name}</Link>
            <span className="muted"> v{c.version} · {c.ruleset}</span>
          </li>
        ))}
      </ul>
    </main>
  )
}
