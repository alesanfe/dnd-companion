import { useState } from 'react'
import { api } from '../api.js'

export default function Search() {
  const [q, setQ] = useState('')
  const [type, setType] = useState('')
  const [edition, setEdition] = useState('')
  const [results, setResults] = useState([])
  const [parsed, setParsed] = useState(null)
  const [asked, setAsked] = useState(null)
  const [err, setErr] = useState(null)

  const go = async (e) => {
    e.preventDefault()
    try {
      // sintaxis de comandos: /spell fire level:3 — si no, FTS normal
      const cmd = (type ? `/${type} ` : '') + q.trim() +
                  (edition ? ` ruleset:${edition}` : '')
      const r = cmd.trim().startsWith('/') || edition
        ? await api.commandSearch(cmd)
        : await api.search(q)
      setResults(r.results)
      setParsed(r.parsed || null)
    } catch (e2) { setErr(e2.message) }
  }

  return (
    <main>
      <h1>Buscador de reglas</h1>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="fireball — o /monster cr:1..5 type:undead" autoFocus />
        <select value={type} onChange={(e) => setType(e.target.value)}
                aria-label="Tipo de entidad">
          <option value="">todo</option>
          {['spell', 'monster', 'class', 'race', 'species', 'feat',
            'equipment', 'item', 'condition', 'rule', 'background',
            'trait'].map((t) => (
            <option key={t} value={t}>{t}</option>))}
        </select>
        <select value={edition} onChange={(e) => setEdition(e.target.value)}
                aria-label="Edición">
          <option value="">2014+2024</option>
          <option value="2014">2014</option>
          <option value="2024">2024</option>
        </select>
        <button type="submit">Buscar</button>
      </form>
      {err && <p className="error">{err}</p>}

      <div className="row">
        <button onClick={async () => {
          const r = await api.rulesAsk(q)
          setAsked(r)
        }}>Preguntar a las reglas</button>
      </div>
      {asked && (
        <section className="card">
          <h2>Asistente de reglas</h2>
          {!asked.evidence_found
            ? <p>Sin evidencia en las fuentes instaladas.</p>
            : asked.citations.map((c) => (
              <div key={c.entity_id} className="citation">
                <strong>{c.name}</strong>
                <span className="muted"> · {c.ruleset} · {c.citation.source_id} ({c.citation.license})</span>
                {c.excerpt && <p className="excerpt" dangerouslySetInnerHTML={{ __html: c.excerpt }} />}
              </div>
            ))}
        </section>
      )}
      {parsed && (
        <p className="muted">
          tipo: {parsed.type || 'cualquiera'}
          {parsed.terms.length > 0 && ` · texto: ${parsed.terms.join(' ')}`}
          {Object.keys(parsed.filters).length > 0 &&
            ` · filtros: ${JSON.stringify(parsed.filters)}`}
        </p>
      )}
      <ul className="results">
        {results.map((r) => (
          <li key={r.id}>
            <strong>{r.name}</strong>{' '}
            <span className="muted">{r.entity_type} · {r.ruleset}</span>
            {r.summary && (
              <p className="excerpt">
                {Object.entries(r.summary).map(([k, v]) => `${k}: ${v}`).join(' · ')}
              </p>
            )}
            {r.excerpt && <p className="excerpt" dangerouslySetInnerHTML={{ __html: r.excerpt }} />}
          </li>
        ))}
      </ul>
    </main>
  )
}
