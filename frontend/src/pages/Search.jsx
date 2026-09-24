import { useState } from 'react'
import { api } from '../api.js'

export default function Search() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [err, setErr] = useState(null)

  const go = async (e) => {
    e.preventDefault()
    try {
      const r = await api.search(q)
      setResults(r.results)
    } catch (e2) { setErr(e2.message) }
  }

  return (
    <main>
      <h1>Buscador de reglas</h1>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="fireball, goblin, grapple…" autoFocus />
        <button type="submit">Buscar</button>
      </form>
      {err && <p className="error">{err}</p>}
      <ul className="results">
        {results.map((r) => (
          <li key={r.id}>
            <strong>{r.name}</strong> <span className="muted">{r.entity_type} · {r.ruleset}</span>
            {r.excerpt && <p className="excerpt" dangerouslySetInnerHTML={{ __html: r.excerpt }} />}
          </li>
        ))}
      </ul>
    </main>
  )
}
