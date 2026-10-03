import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { loadJSON } from '../session.js'
import { useT, etypeLabel } from '../i18n.jsx'
import EntityPreview from '../components/EntityPreview.jsx'
import { trackTask } from '../metrics.js'

/* el excerpt del FTS viene del JSON de la entidad (homebrew
   incluido) — escapar SIEMPRE antes de marcar, o es XSS */
const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
    "'": '&#39;' }[ch]))
const markExcerpt = (s) =>
  esc(s).replace(/\[([^\]]+)\]/g, '<mark>$1</mark>')

export default function Search() {
  const { t, tf } = useT()
  // los filtros sobreviven al ir y volver del detalle (sessionStorage)
  const saved = loadJSON('dnd-search', {}, sessionStorage)
  const [q, setQ] = useState(saved.q || '')
  const [type, setType] = useState(saved.type || '')
  const [edition, setEdition] = useState(saved.edition || '')
  const [source, setSource] = useState(saved.source || '')
  const [sources, setSources] = useState([])
  const [results, setResults] = useState([])
  const [parsed, setParsed] = useState(null)
  const [asked, setAsked] = useState(null)
  const [compare, setCompare] = useState([])   // ids a comparar (máx 2)
  const [preview, setPreview] = useState(null) // id en el panel derecho
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
      trackTask('search', true)
      if (term0.trim()) {                   // historial de consultas
        const rec = loadJSON('dnd-recent-searches', [], sessionStorage)
        sessionStorage.setItem('dnd-recent-searches',
          JSON.stringify([term0.trim(),
            ...rec.filter((x) => x !== term0.trim())].slice(0, 8)))
      }
    } catch (e2) { setErr(e2.message); trackTask('search', false) }
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
               aria-label={t('search.title')}
               placeholder={t('search.placeholder')} autoFocus />
        <select value={type} onChange={(e) => setType(e.target.value)}
                aria-label={t('search.typeAria')}>
          <option value="">{t('search.allTypes')}</option>
          {['spell', 'monster', 'class', 'race', 'species', 'feat',
            'equipment', 'item', 'condition', 'rule', 'background',
            'trait'].map((t) => (
            <option key={t} value={t}>{t}</option>))}
        </select>
        <button type="submit">{t('search.button')}</button>
        {/* el atajo existe desde la paleta pero nadie lo anunciaba —
            kbd visible junto al campo que dispara */}
        <span className="muted" style={{ fontSize: '.8rem',
                                         alignSelf: 'center' }}>
          <kbd>Ctrl</kbd>+<kbd>K</kbd> {t('search.kbdHint')}</span>
      </form>

      {/* progressive disclosure: edición, fuente y asistente quedan
          fuera de la vista básica */}
      <details className="adv">
        <summary>{t('search.advanced')}</summary>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <select value={edition} onChange={(e) => setEdition(e.target.value)}
                  aria-label={t('search.edition')}>
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
          <button className="ghost" onClick={async () => {
            try {
              // el asistente respeta el filtro de edición — antes se
              // ignoraba y citaba las dos ediciones mezcladas
              const r = await api.rulesAsk(
                q, edition ? `dnd5e-${edition}` : null)
              setAsked(r)
            } catch (e2) { setErr(e2.message) }
          }}>{t('search.ask')}</button>
        </div>
      </details>
      {err && <p className="error" role="alert">{err}</p>}
      {asked && (
        <section className="card">
          <h2>{t('search.assistant')}</h2>
          {!asked.evidence_found
            ? <p>{t('search.noEvidence')}</p>
            : asked.citations.map((c) => (
              <div key={c.entity_id} className="citation">
                <strong>{c.name}</strong>
                <span className="muted"> · {c.ruleset} · {c.citation.source_id} ({c.citation.license})</span>
                {c.excerpt && <p className="excerpt" dangerouslySetInnerHTML={{ __html: markExcerpt(c.excerpt) }} />}
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
          {t('search.parsedType')}: {parsed.type || t('search.anyType')}
          {parsed.terms.length > 0 && ` · ${t('search.parsedText')}: ${parsed.terms.join(' ')}`}
          {Object.keys(parsed.filters).length > 0 &&
            ` · ${t('search.parsedFilters')}: ${JSON.stringify(parsed.filters)}`}
        </p>
      )}
      {compare.length === 2 && <Compare ids={compare} />}

      <div className="compendium">
      <ul className="results">
        {results.map((r) => (
          <li key={r.id}>
            <label className="muted" style={{ fontSize: '.8em' }}
                   title={t('search.compare')}>
              <input type="checkbox"
                     aria-label={`${t('search.compare')} ${r.name}`}
                     checked={compare.includes(r.id)}
                     onChange={(e) => setCompare((prev) =>
                       e.target.checked
                         ? [...prev, r.id].slice(-2)
                         : prev.filter((x) => x !== r.id))} />
              ≈
            </label>{' '}
            <button className="linkish"
                    aria-current={preview === r.id}
                    onClick={() => setPreview(r.id)}>
              <strong>{r.name}</strong></button>{' '}
            <Link to={`/content/${encodeURIComponent(r.id)}`}
                  className="muted" title={t('common.details')}
                  aria-label={tf('search.openAria', { name: r.name })}
                  onClick={() => sessionStorage.setItem(
                    'dnd-search-scroll', String(window.scrollY))}>
              ↗</Link>{' '}
            <span className="muted">
              {etypeLabel(t, r.entity_type)} · {r.ruleset} · {r.source_id}
              {!r.is_redistributable && ` · ${t('search.private')}`}
            </span>
            {r.summary && (
              <p className="excerpt">
                {/* claves snake_case del backend (level, casting_time…)
                    se traducen via search.field.* — sin clave se deja
                    el nombre crudo (mejor que inventar traducción) */}
                {Object.entries(r.summary).map(([k, v]) => {
                  const lbl = t(`search.field.${k}`)
                  return `${lbl === `search.field.${k}` ? k : lbl}: ${v}`
                }).join(' · ')}
              </p>
            )}
            {r.excerpt && <p className="excerpt"
              dangerouslySetInnerHTML={{ __html: markExcerpt(r.excerpt) }} />}
          </li>
        ))}
      </ul>
      {preview && (
        <aside className="card preview-pane" aria-label={t('search.previewAria')}>
          <EntityPreview id={preview} />
        </aside>)}
      </div>

      <HomebrewForm />
    </main>
  )
}


/** Comparación lado a lado: campos renderizados de ambas entidades. */
function Compare({ ids }) {
  const { t } = useT()
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
      <h2>{t('search.compare')}</h2>
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
  const favs = loadJSON('dnd-favs', [])
  const recs = loadJSON('dnd-recents', [])
  const norm = (x) => typeof x === 'string'
    ? { id: x, name: x.split(':').pop(), type: '' } : x
  // colecciones nombradas: {nombre: [ids]} — el nombre se resuelve
  // a la entidad en render
  const cols = loadJSON('dnd-collections', {})
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
      <div className="row" role="group" aria-label={t('search.colsAria')}>
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
  const { t } = useT()
  const items = loadJSON('dnd-recent-searches', [], sessionStorage)
  if (!items.length) return null
  return (
    <section className="card">
      <h2>{t('search.recentQueries')}</h2>
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
  /* stats de monstruo homebrew — el normalizador de statblock los
     lee igual que en 5e-bits/Open5e (armor_class int, hit_points,
     cr '1/4', speed str, str..cha, actions[{name,desc}]) */
  const [m, setM] = useState({ ac: '', hp: '', cr: '', speed: '',
    size: '', mtype: '', align: '',
    str: '', dex: '', con: '', int: '', wis: '', cha: '', actions: '' })
  const setMf = (k) => (e) => setM({ ...m, [k]: e.target.value })
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  if (!open) return (
    <button className="ghost" onClick={() => setOpen(true)}>
      {t('search.homebrew')}</button>)
  return (
    <section className="card" role="dialog"
             aria-label={t('search.hbAria')}>
      <h2>{t('search.hbTitle')}</h2>
      <div className="row">
        <select value={form.entity_type} aria-label={t('search.hbType')}
                onChange={(e) => setForm(
                  { ...form, entity_type: e.target.value })}>
          {['item', 'weapon', 'armor', 'spell', 'feat', 'monster',
            'trait', 'condition', 'background', 'species', 'rule']
            .map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={form.ruleset} aria-label={t('search.hbRuleset')}
                onChange={(e) => setForm(
                  { ...form, ruleset: e.target.value })}>
          <option value="dnd5e-2014">2014</option>
          <option value="dnd5e-2024">2024</option>
          <option value="mixed">{t('search.hbMixed')}</option>
        </select>
        <input value={form.name} placeholder={t('camp.name')}
               aria-label={t('search.hbNameAria')}
               onChange={(e) => setForm(
                 { ...form, name: e.target.value })} />
      </div>
      <textarea value={form.desc} rows={2}
                placeholder={t('search.hbDescPh')}
                aria-label={t('search.hbDescPh')}
                onChange={(e) => setForm(
                  { ...form, desc: e.target.value })} />
      {form.entity_type === 'monster' && (<>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input type="number" value={m.ac} placeholder={t('hbm.ac')}
                 aria-label={t('hbm.ac')} style={{ maxWidth: 80 }}
                 onChange={setMf('ac')} />
          <input type="number" value={m.hp} placeholder={t('hbm.hp')}
                 aria-label={t('hbm.hp')} style={{ maxWidth: 80 }}
                 onChange={setMf('hp')} />
          <input value={m.cr} placeholder={t('hbm.cr')}
                 aria-label={t('hbm.cr')} style={{ maxWidth: 80 }}
                 onChange={setMf('cr')} />
          <input value={m.speed} placeholder={t('hbm.speed')}
                 aria-label={t('hbm.speed')} style={{ maxWidth: 130 }}
                 onChange={setMf('speed')} />
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input value={m.size} placeholder={t('hbm.size')}
                 aria-label={t('hbm.size')} style={{ maxWidth: 100 }}
                 onChange={setMf('size')} />
          <input value={m.mtype} placeholder={t('hbm.type')}
                 aria-label={t('hbm.type')} style={{ maxWidth: 130 }}
                 onChange={setMf('mtype')} />
          <input value={m.align} placeholder={t('hbm.align')}
                 aria-label={t('hbm.align')} style={{ maxWidth: 80 }}
                 onChange={setMf('align')} />
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
            <input key={a} type="number" value={m[a]} placeholder={a}
                   aria-label={a} style={{ maxWidth: 58 }}
                   onChange={setMf(a)} />))}
        </div>
        <textarea value={m.actions} rows={3}
                  placeholder={t('hbm.actionsPh')}
                  aria-label={t('hbm.actionsPh')}
                  onChange={setMf('actions')} />
      </>)}
      <div className="row">
        <button className="primary"
                disabled={!form.name.trim() || saving}
                onClick={async () => {
          const data = form.desc ? { desc: form.desc } : {}
          if (form.entity_type === 'monster') {
            if (+m.ac) data.armor_class = +m.ac
            if (+m.hp) data.hit_points = +m.hp
            if (m.cr.trim()) data.cr = m.cr.trim()
            if (m.speed.trim()) data.speed = m.speed.trim()
            if (m.size.trim()) data.size = m.size.trim()
            if (m.mtype.trim()) data.type = m.mtype.trim()
            if (m.align.trim()) data.alignment = m.align.trim()
            for (const a of ['str', 'dex', 'con', 'int', 'wis', 'cha'])
              if (+m[a]) data[a] = +m[a]
            const acts = m.actions.split('\n').map((l) => l.trim())
              .filter(Boolean).map((l) => {
                const i = Math.max(l.indexOf('. '), l.indexOf(': '))
                return i > 0
                  ? { name: l.slice(0, i), desc: l.slice(i + 2) }
                  : { name: t('hbm.actionName'), desc: l }
              })
            if (acts.length) data.actions = acts
          }
          setSaving(true)
          try {
            const r = await api.createHomebrew({
              entity_type: form.entity_type,
              name: form.name.trim(),
              ruleset: form.ruleset,
              data,
              license: 'user-created',
            })
            setMsg(`${t('search.hbCreated')}: ${r.id}`)
          } catch (ex) { setMsg(`⚠ ${ex.message}`) }
          setSaving(false)
        }}>{t('search.hbSave')}</button>
        <button className="ghost" onClick={() => setOpen(false)}>
          {t('common.close')}</button>
      </div>
      {msg && <p className="muted" role="status">✓ {msg}</p>}
    </section>)
}

/** Una colección: resuelve ids a nombres de entidad. */
function CollectionBlock({ ids, name }) {
  const { t } = useT()
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
      <h2>{t('search.colPrefix')} {name}</h2>
      {items.map((x) => (
        <div key={x.id} className="row">
          <Link to={`/content/${encodeURIComponent(x.id)}`}
                style={{ flex: 1 }}>{x.name}</Link>
          <span className="muted">{x.type}</span>
        </div>))}
      {!items.length && <p className="muted">{t('search.colEmpty')}</p>}
    </section>)
}
