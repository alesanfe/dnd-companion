import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errText } from '../api.js'
import { loadJSON } from '../session.js'
import { useT } from '../i18n.jsx'

const FAVS_KEY = 'dnd-fav-chars'
const ARCH_KEY = 'dnd-archived-chars'
const loadSet = (k) => new Set(loadJSON(k, []))
const saveSet = (k, s) => localStorage.setItem(k, JSON.stringify([...s]))

const avatarHue = (name = '') => {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

export default function CharacterList() {
  const { t, tf } = useT()
  /* null = aún cargando: el estado vacío solo pinta tras la respuesta */
  const [chars, setChars] = useState(null)
  const [name, setName] = useState('')
  const [err, setErr] = useState(null)
  const [menu, setMenu] = useState(null)   // id del char con ⋮ abierto
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState('recent')
  const [view, setView] = useState('activos')  // activos|favoritos|archivados
  const [busy, setBusy] = useState(false)      // crear = una sola vez
  const [favs, setFavs] = useState(() => loadSet(FAVS_KEY))
  const [archived, setArchived] = useState(() => loadSet(ARCH_KEY))

  const [camps, setCamps] = useState([])

  const load = () => api.listCharacters()
    .then((r) => setChars(r.characters))
    .catch((e) => setErr(errText(e, t)))

  useEffect(() => {
    load()
    api.listCampaigns?.()
      .then((r) => setCamps(r.campaigns || [])).catch(() => {})
  }, [])
  const campName = (cid) =>
    camps.find((c) => c.id === cid)?.name || t('camp.name')

  const toggle = (set, setter, key, id) => {
    const nx = new Set(set)
    nx.has(id) ? nx.delete(id) : nx.add(id)
    setter(nx); saveSet(key, nx)
  }

  const create = async (e) => {
    e.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    try { await api.createCharacter(name.trim()); setName(''); load() }
    catch (ex) { setErr(errText(ex, t)) }
    finally { setBusy(false) }
  }

  const act = async (c, action) => {
    setMenu(null)
    try {
      if (action === 'export') {
        const ex = await api.exportCharacter(c.id)
        const a = document.createElement('a')
        a.href = URL.createObjectURL(new Blob(
          [JSON.stringify(ex, null, 2)], { type: 'application/json' }))
        a.download = `${c.name}.json`; a.click()
      } else if (action === 'duplicate') {
        const ex = await api.exportCharacter(c.id)
        await api.importCharacter(
          { ...(ex.character || ex),
            name: tf('clist.copyName', { name: c.name }) })
        load()
      } else if (action === 'archive') {
        toggle(archived, setArchived, ARCH_KEY, c.id)
      } else if (action === 'delete') {
        if (!confirm(tf('clist.deleteConfirm', { name: c.name })))
          return
        await api.deleteCharacter(c.id)
        load()
      }
    } catch (ex) { setErr(errText(ex, t)); load() }
  }

  const lastCharId = loadJSON('dnd-last-char')?.id

  const byView = (chars ?? []).filter((c) => {
    if (view === 'favoritos') return favs.has(c.id)
    if (view === 'archivados') return archived.has(c.id)
    return !archived.has(c.id)
  })
  const shown = (filter.trim()
    ? byView.filter((c) =>
        c.name.toLowerCase().includes(filter.trim().toLowerCase()))
    : byView)
    .sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name)
      if (sort === 'level') return (b.level || 1) - (a.level || 1)
      return (a.id === lastCharId ? -1 : 0) - (b.id === lastCharId ? -1 : 0)
    })

  const renderCard = (c) => {
    const pct = c.hp_max
      ? Math.round(100 * (c.hp_current ?? c.hp_max) / c.hp_max) : 100
    const portrait = localStorage.getItem(`dnd-portrait-${c.id}`)
    return (
      <div key={c.id} className="card char-card">
        <div className="row" style={{ marginTop: 0, flexWrap: 'nowrap',
                                      minWidth: 0,
                                      alignItems: 'flex-start' }}>
          <button className="ghost" style={{ padding: '0 .3rem' }}
                  aria-pressed={favs.has(c.id)}
                  aria-label={tf('clist.favAria', { name: c.name })}
                  onClick={() => toggle(favs, setFavs, FAVS_KEY, c.id)}>
            {favs.has(c.id) ? '★' : '☆'}</button>
          <span className="avatar sm" aria-hidden="true"
                style={portrait
                  ? { backgroundImage: `url(${portrait})`,
                      backgroundSize: 'cover' }
                  : { background:
                      `hsl(${avatarHue(c.class_names?.[0] || c.name)
                      } 45% 42%)` }}>
            {!portrait && (c.name || '?')[0].toUpperCase()}</span>
          <Link to={`/character/${c.id}`}
                style={{ flex: 1, fontSize: '1.1rem', minWidth: 0,
                         fontWeight: 700, textDecoration: 'none',
                         color: 'inherit' }}>
            {c.name}</Link>
          <button className="ghost"
                  aria-label={tf('clist.menuAria', { name: c.name })}
                  onClick={() => setMenu(menu === c.id ? null : c.id)}>
            ⋮</button>
        </div>
        <p className="muted" style={{ margin: '0 0 .4rem' }}>
          {(c.class_names || []).join(' / ') || t('clist.noClass')}
          {' · '}{t('sheet.level')} {c.level || 1}
          {' · '}{t(`ruleset.${c.ruleset}`)}
          {c.id === lastCharId &&
            <span className="chip" style={{ marginLeft: '.4rem',
              fontSize: '.75rem' }}>{t('clist.last')}</span>}
        </p>
        {c.hp_max != null && (
          <>
            <div className="hp-bar" role="img"
                 aria-label={tf('sheet.hpAria2',
                                { cur: c.hp_current, max: c.hp_max })}>
              <div style={{ width: `${pct}%` }} />
            </div>
            <p className="muted" style={{ margin: '.2rem 0 0' }}>
              {c.hp_current}/{c.hp_max} PG</p>
          </>)}
        {menu === c.id && (
          <div className="row" role="menu">
            <Link to={`/character/${c.id}`}>
              <button className="ghost">{t('clist.open')}</button></Link>
            <Link to={`/character/${c.id}?focus=1`}>
              <button className="ghost">{t('clist.focusMode')}</button></Link>
            <button className="ghost"
                    onClick={() => act(c, 'duplicate')}>
              {t('clist.duplicate')}</button>
            <button className="ghost"
                    onClick={() => act(c, 'export')}>
              {t('clist.export')}</button>
            <button className="ghost"
                    onClick={() => act(c, 'archive')}>
              {view === 'archivados'
                ? t('clist.restore') : t('clist.archive')}</button>
            <button className="ghost"
                    onClick={() => act(c, 'delete')}>
              {t('clist.delete')}</button>
          </div>)}
      </div>)
  }

  return (
    <main>
      <h1>{t('charlist.title')}</h1>
      {err && <p className="error" role="alert">{t('clist.backendErr')}: {err}</p>}
      <form onSubmit={create} className="row">
        <input value={name} onChange={(e) => setName(e.target.value)}
               aria-label={t('charlist.new')}
               placeholder={t('charlist.new') + '…'} />
        <button type="submit" disabled={busy}>{t('nav.create')}</button>
        <Link to="/new"><button type="button">{t('charlist.wizard')}</button></Link>
        <label className="ghost" style={{ cursor: 'pointer',
             display: 'inline-flex', alignItems: 'center',
             minHeight: 44, padding: '0 1rem', borderRadius: 6,
             border: '1px solid var(--border)' }}>
          {t('charlist.import')}
          <input type="file" accept=".json" hidden
                 aria-label={t('charlist.import')}
                 onChange={async (e) => {
                   const f = e.target.files[0]
                   if (!f) return
                   try {
                     const data = JSON.parse(await f.text())
                     // acepta el envelope de exportación o la ficha suelta
                     await api.importCharacter(data.character || data)
                     load()
                   } catch (ex) {
                     setErr(`${t('clist.importErr')}: ${ex.message}`) }
                 }} />
        </label>
      </form>

      {chars === null && !err && (
        <p role="status">{t('common.loading')}</p>)}

      {chars !== null && chars.length === 0 && !err && (
        <div className="card empty">
          <p><strong>{t('charlist.empty')}</strong></p>
          <Link to="/new">
            <button className="primary">{t('wiz.finish')}</button></Link>
        </div>)}

      {(chars?.length ?? 0) > 0 && (
        <div className="row" role="group" aria-label={t('clist.filterAria')}>
          {[['activos', t('charlist.view.active')],
            ['favoritos', `★ ${t('dash.favs')}`],
            ['archivados', t('charlist.view.archived')]].map(([k, l]) => (
            <button key={k} className="ghost" aria-pressed={view === k}
                    style={{ borderColor: view === k
                      ? 'var(--accent)' : undefined }}
                    onClick={() => setView(k)}>{l}</button>))}
          <span className="spacer" />
          <select value={sort} aria-label={t('clist.sortAria')}
                  style={{ maxWidth: 140 }}
                  onChange={(e) => setSort(e.target.value)}>
            <option value="recent">{t('charlist.sort.recent')}</option>
            <option value="name">{t('charlist.sort.name')}</option>
            <option value="level">{t('charlist.sort.level')}</option>
          </select>
        </div>)}

      {(chars?.length ?? 0) > 4 && (
        <input value={filter} onChange={(e) => setFilter(e.target.value)}
               placeholder={tf('clist.searchPh', { n: chars?.length ?? 0 })}
               aria-label={t('clist.searchAria')} />)}

      {/* si hay varias campañas, agrupa las tarjetas por campaña
          (lista DiceCloud-style); las "sin campaña" al final */}
      {(() => {
        const campIds = new Set(shown.map((c) => c.campaign_id)
                                    .filter(Boolean))
        if (campIds.size === 0) return null
        const groups = [...campIds, null]
        return groups.map((cid) => {
          const list = shown.filter((c) =>
            (cid === null ? !c.campaign_id : c.campaign_id === cid))
          if (!list.length) return null
          return (
            <div key={cid || 'none'}>
              <h3 className="muted" style={{ margin: '1rem 0 .4rem' }}>
                {cid ? `🗺 ${campName(cid)}` : t('clist.noCamp')}</h3>
              <div className="char-grid">{list.map(renderCard)}</div>
            </div>)
        })
      })()}
      <div className="char-grid">
        {[...new Set(shown.map((c) => c.campaign_id).filter(Boolean))]
          .length > 0 ? null : shown.map(renderCard)}
      </div>
      {shown.length === 0 && (chars?.length ?? 0) > 0 && (
        <p className="muted">{t('charlist.view.empty')}</p>)}
    </main>
  )
}
