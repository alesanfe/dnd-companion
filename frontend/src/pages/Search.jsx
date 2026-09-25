import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useT } from '../i18n.jsx'

export default function Search() {
  const { t } = useT()
  // los filtros sobreviven al ir y volver del detalle (sessionStorage)
  const saved = JSON.parse(sessionStorage.getItem('dnd-search') || '{}')
  const [q, setQ] = useState(saved.q || '')
  const [type, setType] = useState(saved.type || '')
  const [edition, setEdition] = useState(saved.edition || '')
  const [source, setSource] = useState(saved.source || '')
  const [sources, setSources] = useState([])
  const [results, setResults] = useState([])
  const [parsed, setParsed] = useState(null)
  const [asked, setAsked] = useState(null)
  const [compare, setCompare] = useState([])   // ids a comparar (máx 2)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.contentSources().then((r) => setSources(r.sources)).catch(() => {})
  }, [])
  useEffect(() => {
    sessionStorage.setItem('dnd-search',
      JSON.stringify({ q, type, edition, source }))
  }, [q, type, edition, source])

  const doSearch = async (term) => {
    const term0 = term ?? q
    try {
      const cmd = (type ? `/${type} ` : '') + term0.trim() +
                  (edition ? ` ruleset:${edition}` : '')
      const r = cmd.trim().startsWith('/') || edition
        ? await api.commandSearch(cmd)
        : await api.search(term0, null, source || null)
      setResults(r.results)
      setParsed(r.parsed || null)
      if (term0.trim()) {                   // historial de consultas
        const rec = JSON.parse(sessionStorage.getItem(
          'dnd-recent-searches') || '[]')
        sessionStorage.setItem('dnd-recent-searches',
          JSON.stringify([term0.trim(),
            ...rec.filter((x) => x !== term0.trim())].slice(0, 8)))
      }
    } catch (e2) { setErr(e2.message) }
  }
  const go = (e) => { e?.preventDefault(); doSearch() }

  // al volver del detalle: reejecuta la búsqueda guardada y
  // restaura la posición de scroll
  useEffect(() => {
    if (saved.q) go()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    const y = sessionStorage.getItem('dnd-search-scroll')
    if (y && results.length) {
      window.scrollTo(0, +y)
      sessionStorage.removeItem('dnd-search-scroll')
    }
  }, [results])

  return (
    <main className="wide">
      <h1>{t('search.title')}</h1>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('search.placeholder')} autoFocus />
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
                aria-label={t('search.source')}>
          <option value="">{t('search.allSources')}</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.entities})
            </option>))}
        </select>
        <button type="submit">{t('search.button')}</button>
      </form>
      {err && <p className="error">{err}</p>}

      <div className="row">
        <button onClick={async () => {
          const r = await api.rulesAsk(q)
          setAsked(r)
        }}>{t('search.ask')}</button>
      </div>
      {asked && (
        <section className="card">
          <h2>{t('search.assistant')}</h2>
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
        <QuickAccess t={t} onSearch={(term) => {
          setQ(term)
          doSearch(term)
        }} />)}

      {results.length === 0 && q.trim() && (
        <p className="empty">{t('search.empty')}</p>)}

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
            <Link to={`/content/${encodeURIComponent(r.id)}`}
                  onClick={() => sessionStorage.setItem(
                    'dnd-search-scroll', String(window.scrollY))}>
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

      <HomebrewForm />
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
      <h2>{useT().t('search.compare')}</h2>
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
function QuickAccess({ onSearch, t }) {
  const favs = JSON.parse(localStorage.getItem('dnd-favs') || '[]')
  const recs = JSON.parse(localStorage.getItem('dnd-recents') || '[]')
  const norm = (x) => typeof x === 'string'
    ? { id: x, name: x.split(':').pop(), type: '' } : x
  // colecciones nombradas: {nombre: [ids]} — el nombre se resuelve
  // a la entidad en render
  const cols = JSON.parse(localStorage.getItem('dnd-collections') || '{}')
  const [col, setCol] = useState(null)
  if (!favs.length && !recs.length &&
      !Object.keys(cols).length) return null
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
    {Object.keys(cols).length > 0 && (
      <div className="row" role="group" aria-label="Colecciones">
        {Object.keys(cols).map((c) => (
          <button key={c} className="ghost"
                  aria-pressed={col === c}
                  style={{ borderColor: col === c ? 'var(--accent)'
                                                  : undefined }}
                  onClick={() => setCol(col === c ? null : c)}>
            {c}</button>))}
      </div>)}
    {col && <CollectionBlock ids={cols[col] || []} name={col} />}
    {!col && block(t('search.favorites'), favs)}
    {!col && block(t('search.recent'), recs)}
    {!col && <RecentSearches onSearch={onSearch} />}
  </>)
}

/** Últimas consultas escritas — recuperables con un toque. */
function RecentSearches({ onSearch }) {
  const items = JSON.parse(
    sessionStorage.getItem('dnd-recent-searches') || '[]')
  if (!items.length) return null
  return (
    <section className="card">
      <h2>{useT().t('search.recentQueries')}</h2>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {items.map((x) => (
          <button key={x} className="ghost"
                  onClick={() => onSearch(x)}>{x}</button>))}
      </div>
    </section>)
}

/** Crear contenido propio → fuente 'homebrew' (marcada como
    user-created, privada del usuario). */
function HomebrewForm() {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    entity_type: 'item', name: '', ruleset: 'dnd5e-2014', desc: '' })
  const [msg, setMsg] = useState(null)
  if (!open) return (
    <button className="ghost" onClick={() => setOpen(true)}>
      {t('search.homebrew')}</button>)
  return (
    <section className="card" role="dialog"
             aria-label="Crear contenido homebrew">
      <h2>Contenido homebrew</h2>
      <div className="row">
        <select value={form.entity_type} aria-label="Tipo"
                onChange={(e) => setForm(
                  { ...form, entity_type: e.target.value })}>
          {['item', 'weapon', 'armor', 'spell', 'feat', 'monster',
            'trait', 'condition', 'background', 'species', 'rule']
            .map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={form.ruleset} aria-label="Ruleset"
                onChange={(e) => setForm(
                  { ...form, ruleset: e.target.value })}>
          <option value="dnd5e-2014">2014</option>
          <option value="dnd5e-2024">2024</option>
          <option value="mixed">Mixto</option>
        </select>
        <input value={form.name} placeholder="Nombre"
               aria-label="Nombre del contenido"
               onChange={(e) => setForm(
                 { ...form, name: e.target.value })} />
      </div>
      <textarea value={form.desc} rows={2}
                placeholder="Descripción / reglas caseras"
                onChange={(e) => setForm(
                  { ...form, desc: e.target.value })} />
      <div className="row">
        <button className="primary" disabled={!form.name.trim()}
                onClick={async () => {
          const r = await api.createHomebrew({
            entity_type: form.entity_type,
            name: form.name.trim(),
            ruleset: form.ruleset,
            data: form.desc ? { desc: form.desc } : {},
            license: 'user-created',
          })
          setMsg(`Creado: ${r.id}`)
        }}>Guardar en el compendio</button>
        <button className="ghost" onClick={() => setOpen(false)}>
          {t('common.close')}</button>
      </div>
      {msg && <p className="muted" role="status">✓ {msg}</p>}
    </section>)
}

/** Una colección: resuelve ids a nombres de entidad. */
function CollectionBlock({ ids, name }) {
  const [items, setItems] = useState([])
  useEffect(() => {
    Promise.all(ids.map((id) =>
      api.getEntity(id).then((e) =>
        ({ id: e.id, name: e.name, type: e.entity_type }))
        .catch(() => ({ id, name: id.split(':').pop(), type: '' }))))
      .then(setItems)
  }, [ids])
  return (
    <section className="card">
      <h2>Col. {name}</h2>
      {items.map((x) => (
        <div key={x.id} className="row">
          <Link to={`/content/${encodeURIComponent(x.id)}`}
                style={{ flex: 1 }}>{x.name}</Link>
          <span className="muted">{x.type}</span>
        </div>))}
      {!items.length && <p className="muted">Colección vacía.</p>}
    </section>)
}
