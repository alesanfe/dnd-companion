import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

export default function Search() {
  const [q, setQ] = useState('')
  const [type, setType] = useState('')
  const [edition, setEdition] = useState('')
  const [source, setSource] = useState('')
  const [sources, setSources] = useState([])
  const [results, setResults] = useState([])
  const [parsed, setParsed] = useState(null)
  const [asked, setAsked] = useState(null)
  const [compare, setCompare] = useState([])   // ids a comparar (máx 2)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.contentSources().then((r) => setSources(r.sources)).catch(() => {})
  }, [])

  const go = async (e) => {
    e.preventDefault()
    try {
      // sintaxis de comandos: /spell fire level:3 — si no, FTS normal
      const cmd = (type ? `/${type} ` : '') + q.trim() +
                  (edition ? ` ruleset:${edition}` : '')
      const r = cmd.trim().startsWith('/') || edition
        ? await api.commandSearch(cmd)
        : await api.search(q, null, source || null)
      setResults(r.results)
      setParsed(r.parsed || null)
    } catch (e2) { setErr(e2.message) }
  }

  return (
    <main className="wide">
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
        <select value={source} onChange={(e) => setSource(e.target.value)}
                aria-label="Fuente de contenido">
          <option value="">todas las fuentes</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.entities})
            </option>))}
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
      {/* recientes + favoritos cuando no hay consulta */}
      {!q.trim() && results.length === 0 && (
        <QuickAccess />)}

      {results.length === 0 && q.trim() && (
        <p className="empty">Sin resultados — prueba otro término,
          quita filtros o busca en otra fuente.</p>)}

      {parsed && (
        <p className="muted">
          tipo: {parsed.type || 'cualquiera'}
          {parsed.terms.length > 0 && ` · texto: ${parsed.terms.join(' ')}`}
          {Object.keys(parsed.filters).length > 0 &&
            ` · filtros: ${JSON.stringify(parsed.filters)}`}
        </p>
      )}
      {compare.length === 2 && <Compare ids={compare} />}

      <ul className="results">
        {results.map((r) => (
          <li key={r.id}>
            <label className="muted" style={{ fontSize: '.8em' }}>
              <input type="checkbox"
                     checked={compare.includes(r.id)}
                     onChange={(e) => setCompare((prev) =>
                       e.target.checked
                         ? [...prev, r.id].slice(-2)
                         : prev.filter((x) => x !== r.id))} />
              cmp
            </label>{' '}
            <Link to={`/content/${encodeURIComponent(r.id)}`}>
              <strong>{r.name}</strong></Link>{' '}
            <span className="muted">
              {r.entity_type} · {r.ruleset} · {r.source_id}
              {!r.is_redistributable && ' · contenido privado'}
            </span>
            {r.summary && (
              <p className="excerpt">
                {Object.entries(r.summary).map(([k, v]) => `${k}: ${v}`).join(' · ')}
              </p>
            )}
            {r.excerpt && <p className="excerpt"
              dangerouslySetInnerHTML={{ __html: r.excerpt.replace(
                /\[([^\]]+)\]/g, '<mark>$1</mark>') }} />}
          </li>
        ))}
      </ul>
    </main>
  )
}


/** Comparación lado a lado: campos renderizados de ambas entidades. */
function Compare({ ids }) {
  const [views, setViews] = useState([])
  useEffect(() => {
    setViews([])
    Promise.all(ids.map((i) => api.entityRender(i)))
      .then((rs) => setViews(rs)).catch(() => {})
  }, [ids.join(',')])
  if (views.length !== 2) return null
  const keys = [...new Set(
    views.flatMap((v) => (v.render?.fields || []).map((f) => f.label)))]
  return (
    <section className="card">
      <h2>Comparar</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          <th />
          {views.map((v) => <th key={v.id} style={{ textAlign: 'left' }}>
            <Link to={`/content/${encodeURIComponent(v.id)}`}>
              {v.name}</Link></th>)}
        </tr></thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td className="muted" style={{ paddingRight: '1rem' }}>{k}</td>
              {views.map((v) => {
                const f = (v.render?.fields || [])
                  .find((x) => x.label === k)
                return <td key={v.id}>{f ? f.value : '—'}</td>})}
            </tr>))}
        </tbody>
      </table>
    </section>
  )
}


/** Favoritos (guardados con ☆ en detalle) + recientes (visitas). */
function QuickAccess() {
  const favs = JSON.parse(localStorage.getItem('dnd-favs') || '[]')
  const recs = JSON.parse(localStorage.getItem('dnd-recents') || '[]')
  const norm = (x) => typeof x === 'string'
    ? { id: x, name: x.split(':').pop(), type: '' } : x
  if (!favs.length && !recs.length) return null
  const block = (title, items) => items.length > 0 && (
    <section className="card">
      <h2>{title}</h2>
      {items.map((x0) => {
        const x = norm(x0)
        return (
          <div key={x.id} className="row">
            <Link to={`/content/${encodeURIComponent(x.id)}`}
                  style={{ flex: 1 }}>{x.name}</Link>
            <span className="muted">{x.type}</span>
          </div>)})}
    </section>)
  return (<>
    {block('★ Favoritos', favs)}
    {block('Recientes', recs)}
  </>)
}
