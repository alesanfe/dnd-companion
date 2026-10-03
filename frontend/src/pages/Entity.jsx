import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import { loadJSON } from '../session.js'
import { useT, etypeLabel } from '../i18n.jsx'

/** Copia con fallback: navigator.clipboard no existe en contextos
    no seguros (http:// en LAN) — el botón "copiar" no hacía nada. */
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true }
  catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { /* sin permiso */ }
    ta.remove()
    return ok
  }
}

/** Vista legible de una entidad del corpus — stat block normalizado
    para monstruos, campos clave para conjuros/objetos, y el JSON
    original como fallback. */
export default function Entity() {
  const { t, tf } = useT()
  const { id } = useParams()
  const [ent, setEnt] = useState(null)
  const [block, setBlock] = useState(null)
  const [view, setView] = useState(null)
  const [err, setErr] = useState(null)
  const [editions, setEditions] = useState(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.getEntity(id).then(setEnt).catch((e) => setErr(e.message))
    api.statblockPreview(id).then((r) => setBlock(r.statblock))
      .catch(() => setBlock(null))
    api.entityRender(id).then((r) => setView(r.render))
      .catch(() => setView(null))
    api.compareEditions(id.split(':').pop())
      .then(setEditions).catch(() => {})
  }, [id])

  // favoritos + recientes: compendio local, no del backend
  const [fav, setFav] = useState(() =>
    loadJSON('dnd-favs', []).some((f) => (f.id || f) === id))
  const [colPick, setColPick] = useState(false)
  const addToCollection = (col) => {
    const cols = loadJSON('dnd-collections', {})
    cols[col] = [...new Set([...(cols[col] || []), ent.id])]
    localStorage.setItem('dnd-collections', JSON.stringify(cols))
    setColPick(false)
  }
  useEffect(() => {
    if (!ent) return
    const rec = loadJSON('dnd-recents', [])
    const nx = [{ id: ent.id, name: ent.name, type: ent.entity_type },
      ...rec.filter((r) => r.id !== ent.id)].slice(0, 12)
    localStorage.setItem('dnd-recents', JSON.stringify(nx))
  }, [ent?.id])
  const toggleFav = () => {
    const favs = loadJSON('dnd-favs', [])
    const nx = fav
      ? favs.filter((f) => f.id !== id && f !== id)
      : [...favs, { id: ent.id, name: ent.name, type: ent.entity_type }]
    localStorage.setItem('dnd-favs', JSON.stringify(nx))
    setFav(!fav)
  }

  if (err) return <main><p className="error" role="alert">{err}</p></main>
  if (!ent) return <main><p className="muted">{t('common.loading')}</p></main>

  const d = ent.data || {}
  return (
    <main className="wide">
      <div className="row">
        <h1 style={{ flex: 1, margin: 0 }}>{ent.name}</h1>
        <button className="ghost" aria-pressed={fav}
                aria-label={t('ent.favAria')}
                onClick={toggleFav}>
          {fav ? `★ ${t('ent.saved')}` : `☆ ${t('ent.save')}`}</button>
        <button className="ghost" aria-expanded={colPick}
                onClick={() => setColPick(!colPick)}>
          {t('ent.collection')}</button>
        <AddToCharacter entity={ent} />
        <button className="ghost" onClick={async () => {
          const text = block
            ? JSON.stringify(block, null, 2)
            : JSON.stringify(ent.data, null, 2)
          if (await copyText(text)) {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }
        }}>{copied ? `✓ ${t('ent.copied')}` : t('entity.copy')}</button>
      </div>
      {colPick && (
        <div className="card" role="dialog" aria-label={t('ent.colAria')}>
          {Object.keys(loadJSON('dnd-collections', {}))
            .map((c) => (
              <button key={c} className="ghost"
                      onClick={() => addToCollection(c)}>{c}</button>))}
          <div className="row">
            <button onClick={() => {
              const n = prompt(t('ent.colNamePrompt'))
              if (n?.trim()) addToCollection(n.trim())
            }}>{t('ent.newCol')}</button>
            <button className="ghost"
                    onClick={() => setColPick(false)}>
              {t('common.close')}</button>
          </div>
        </div>)}
      <p className="muted">
        {etypeLabel(t, ent.entity_type)} · {ent.ruleset} · {ent.source_id}
        {!ent.is_redistributable &&
          <span className="tag-private"> · {t('search.private')}</span>}
      </p>
      {editions && Object.keys(editions.versions || {}).length > 1 && (
        <div className="row" role="group"
             aria-label={t('ent.editionsAria')}>
          <span className="muted">{t('entity.editions')}</span>
          {Object.entries(editions.versions).map(([rs, v]) => (
            v.id !== ent.id && (
              <Link key={rs}
                    to={`/content/${encodeURIComponent(v.id)}`}
                    className="chip">
                {rs.replace('dnd5e-', '')}</Link>)))}
          {editions.diff?.length > 0 && (
            <span className="muted" style={{ fontSize: '.8rem' }}>
              {t('entity.diff')} {editions.diff.map((k) =>
                k.replaceAll('_', ' ')).join(', ')}</span>)}
        </div>)}

      {block && (
        <section className="card">
          <h2>Stat block</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <span className="chip">CA {block.ac}</span>
            <span className="chip">PG {block.hp}</span>
            <span className="chip">CR {block.cr}</span>
            <span className="chip">{t('ent.speed')} {block.speed || '—'}</span>
            {block.type && <span className="chip">{block.type}</span>}
            {block.size && <span className="chip">{block.size}</span>}
            {block.alignment &&
              <span className="chip">{block.alignment}</span>}
            {block.environment &&
              <span className="chip">⛰ {block.environment}</span>}
          </div>
          {[
            [t('ent.resistances'), block.resistances],
            [t('ent.immunities'), block.immunities],
            [t('ent.vulnerabilities'), block.vulnerabilities],
            [t('ent.condImmunes'), block.condition_immune],
          ].filter(([, v]) => v?.length).map(([label, v]) => (
            <p key={label} className="muted">
              <strong>{label}:</strong> {v.join(', ')}</p>))}
          {block.senses && <p className="muted">
            <strong>{t('ent.senses')}:</strong> {block.senses}</p>}
          {block.languages && <p className="muted">
            <strong>{t('ent.languages')}:</strong> {block.languages}</p>}
          {Object.keys(block.skills || {}).length > 0 && (
            <p className="muted"><strong>{t('ent.skills')}:</strong>{' '}
              {Object.entries(block.skills)
                .map(([k, v]) => `${k} ${v >= 0 ? '+' : ''}${v}`)
                .join(', ')}</p>)}
          {block.spellcasting && (
            <p className="muted"><strong>{t('ent.spells')}:</strong>{' '}
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
  const { t } = useT()
  const [rolled, setRolled] = useState(null)
  const [copied, setCopied] = useState(false)
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
      <h2>{t('ent.table')}
        {(rows.length > 0 || entries.length > 0) &&
          <button style={{ marginLeft: '1rem' }}
                  onClick={roll}>{t('sheet.roll')}</button>}</h2>
      {rolled && (
        <div className="row">
          <p className="chip">
            {Array.isArray(rolled) ? rolled.join(' — ') : String(rolled)}</p>
          <button className="ghost" onClick={async () => {
            const txt = Array.isArray(rolled)
              ? rolled.join(' — ') : String(rolled)
            if (await copyText(txt)) {
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }
          }}>{copied ? `✓ ${t('ent.copied')}` : t('entity.copy')}</button>
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


/** "＋Añadir a personaje": conjuros/dotes/objetos del compendio
    directo a la ficha como operación reversible. */
function AddToCharacter({ entity }) {
  const { t, tf } = useT()
  const [open, setOpen] = useState(false)
  const [chars, setChars] = useState(null)
  const [done, setDone] = useState(null)
  const [err, setErr] = useState(null)
  const type = entity.entity_type
  if (!['spell', 'feat', 'item', 'weapon', 'armor', 'magic-item',
        'background', 'feature'].includes(type)) return null

  const add = async (cid) => {
    try {
      const ch = await api.getCharacter(cid)
      const [opType, payload] =
        type === 'spell' ? ['character.spell.learn',
                            { spell_id: entity.id }]
        : type === 'feat' ? ['character.feat.learn',
                             { feat_id: entity.id }]
        : type === 'background'
          ? ['character.identity.set',
             { field: 'background_id', value: entity.id }]
        : type === 'feature'
          ? ['character.feature.add', { entity_id: entity.id }]
        : ['character.inventory.add',
           { name: entity.name, source_id: entity.id }]
      await api.applyOp({ id: ch.id, version: ch.version },
                        opType, payload)
      setDone(`${entity.name} → ${ch.name}`)
      setErr(null)
    } catch (e) { setErr(e.message) }
  }

  return (
    <>
      <button className="ghost" aria-expanded={open}
              onClick={() => {
                setOpen(!open)
                if (!open) api.listCharacters()
                  .then((r) => setChars(r.characters))
                  .catch(() => setChars([]))
              }}>＋ PJ</button>
      {open && (
        <div className="card" role="dialog"
             aria-label={tf('ent.addAria', { name: entity.name })}>
          {chars === null && <p className="muted">{t('common.loading')}</p>}
          {chars?.length === 0 && (
            <p className="muted">{t('ent.noChars')}</p>)}
          {(chars || []).map((c) => (
            <div key={c.id} className="row">
              <span style={{ flex: 1 }}>{c.name}</span>
              <button onClick={() => add(c.id)}>{t('common.add')}</button>
            </div>))}
          {done && <p role="status" className="muted">✓ {done}</p>}
          {err && <p className="error" role="alert">{err}</p>}
        </div>)}
    </>
  )
}
