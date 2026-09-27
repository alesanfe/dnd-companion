import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api.js'
import { useT } from '../../i18n.jsx'
import { COND_RULES } from './data.js'

/** Sección colapsable de la ficha: el título es un botón con caret
    que expande/contrae el cuerpo. El contenido queda montado
    (hidden) para no perder estado de inputs/listas. */
export function Section({ title, children, hidden, extraClass = '',
                         defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`card csec${open ? ' open' : ''} ${extraClass}`}
             hidden={hidden}>
      <h2 className="csec-head">
        <button className="csec-btn" aria-expanded={open}
                onClick={() => setOpen(!open)}>
          <span className="csec-caret" aria-hidden="true">▾</span>
          {title}
        </button>
      </h2>
      <div className="csec-body" hidden={!open}>{children}</div>
    </section>
  )
}

/** Panel de lanzamiento: elige nivel de espacio, muestra CD/daño
    y avisa si rompe una concentración activa. */
export function CastPanel({ spellId, slots, pactSlots = {},
                             concentrating, onCast, onClose,
                             preparedIds }) {
  const { t, tf } = useT()
  const [sp, setSp] = useState(null)
  const [lvl, setLvl] = useState(null)   // clave de opción: 'r3'|'p2'
  useEffect(() => {
    api.getEntity(spellId).then((e) => {
      setSp(e)
      setLvl(`r${e.data?.level ?? 0}`)
    }).catch(() => {})
  }, [spellId])
  if (!sp) return null
  const sd = sp.data || {}
  const base = sd.level ?? 0
  const conc = !!(sd.concentration || sd.duration === 'concentration' ||
                  /concentración|concentration/i.test(
                    String(sd.duration || '')))
  const avail = Object.entries(slots)
    .filter(([k, s]) => +k >= base && s.used < s.total)
    .map(([k]) => `r${k}`)
    .concat(Object.entries(pactSlots)
      .filter(([k, s]) => +k >= base && s.used < s.total)
      .map(([k]) => `p${k}`))
  /* opciones: 'r3' = espacio regular nv.3 · 'p2' = pacto nv.2 */
  const options = [...new Set([`r${base}`, ...avail])]
  const parseKey = (k) => k[0] === 'p'
    ? { lvl: +k.slice(1), pool: 'pact' }
    : { lvl: +k.slice(1), pool: 'regular' }
  const slotFor = (k) => {
    const { lvl: l, pool } = parseKey(k)
    return (pool === 'pact' ? pactSlots : slots)[l] ||
           (pool === 'pact' ? pactSlots : slots)[String(l)]
  }
  const sel = lvl ? parseKey(lvl) : { lvl: base, pool: 'regular' }
  const slot = lvl != null ? slotFor(lvl) : null
  return (
    <div className="card" role="dialog"
         aria-label={tf('pan.castAria', { name: sp.name })}
         style={{ background: 'var(--card-raised)' }}>
      <strong>{t('sheet.cast')} {sp.name}</strong>
      <div className="row">
        <span className="muted">{t('pan.slotLevel')}</span>
        <select value={lvl ?? `r${base}`}
                onChange={(e) => setLvl(e.target.value)}>
          {options.map((v) => {
            const { lvl: l, pool } = parseKey(v)
            const s = slotFor(v)
            return (
              <option key={v} value={v}
                      disabled={l !== 0 && !(s && s.used < s.total)}>
                {t('pan.lv')} {l}{pool === 'pact'
                  ? ` · ${t('pan.pact')}` : ''}
                {s ? ` (${tf('pan.free', { n: s.total - s.used })})` : ''}
              </option>)
          })}
        </select>
      </div>
      {slot && (
        <p className="muted">
          {tf('pan.slotsOf', { lv: sel.lvl })}
          {sel.pool === 'pact' ? ` ${t('pan.pactTag')}` : ''}:{' '}
          {slot.total - slot.used} → {slot.total - slot.used - 1}</p>)}
      {(() => {
        const scale = sd.damage_at_slot_level ||
                      sd.higher_level_scaling || {}
        const dice = scale[sel.lvl] || scale[String(sel.lvl)] ||
                     sd.damage?.dice || sd.damage_dice
        const scaled = sel.lvl > base &&
          Object.keys(scale).length > 0
        return dice ? (
          <p className="muted">
            {t('pan.dmg')}{scaled
              ? ` ${tf('pan.dmgScaled', { lv: sel.lvl })}` : ''}: {dice}
          </p>) : null
      })()}
      {conc && concentrating && (
        <p className="notice" role="note">
          ⚠ {tf('pan.concWarn', { name: concentrating })}
          {' '}<b>{sp.name}</b> {t('pan.concEnd')}.</p>)}
      {preparedIds?.length > 0 && !preparedIds.includes(spellId) &&
        base > 0 && (
        <p className="notice" role="note">
          ⚠ {tf('pan.notPrepared', { name: sp.name })}</p>)}
      <div className="row">
        <button className="primary"
                disabled={sel.lvl > 0 && !(slot && slot.used < slot.total)}
                onClick={() =>
                  onCast(sel.lvl, sel.pool)}>{t('pan.castBtn')}</button>
        <button className="ghost" onClick={onClose}>
          {t('common.cancel')}</button>
      </div>
    </div>
  )
}

/** Panel de ataque: muestra mods antes de tirar y permite marcar
    ventaja/desventaja y CA del objetivo — nada de tiradas ciegas. */
export function AttackPanel({ charId, item, onResult, onClose }) {
  const { t, tf } = useT()
  const [mode, setMode] = useState('normal')
  const [ac, setAc] = useState('')
  const [last, setLast] = useState(null)
  const roll = async () => {
    const r = await api.characterAttack(
      charId, item.name, mode, ac ? +ac : null)
    setLast(r)
    const miss = r.hit.hits === false ? ` — ${t('pan.miss')}`
               : r.hit.hits === true ? ` — ${t('pan.hitBang')}` : ''
    onResult(`${item.name}: ${t('pan.hit')} ${r.hit.total}${miss}` +
             ` · ${t('pan.dmg')} ${r.damage.expression} = ${
               r.damage.total}` +
             (r.notes?.length ? ` [${r.notes.join(', ')}]` : ''))
  }
  return (
    <div className="card" role="dialog"
         aria-label={tf('pan.atkAria', { name: item.name })}
         style={{ background: 'var(--card-raised)' }}>
      <strong>{item.name}</strong>
      <div className="row" role="radiogroup" aria-label={t('pan.atkMode')}>
        {[['normal', t('pan.normal')], ['adv', t('pan.adv')],
          ['dis', t('pan.dis')]].map(([v, l]) => (
          <label key={v}>
            <input type="radio" name="atk-mode" checked={mode === v}
                   onChange={() => setMode(v)} /> {l}</label>))}
      </div>
      <div className="row">
        <input type="number" placeholder={t('pan.targetAc')}
               aria-label={t('pan.targetAcAria')} style={{ maxWidth: 150 }}
               value={ac} onChange={(e) => setAc(e.target.value)} />
        <button className="primary" onClick={roll}>
          {t('pan.atkRoll')}</button>
        <button className="ghost" onClick={onClose}>
          {t('common.close')}</button>
      </div>
      {last && (
        <p className="muted" role="status">
          {t('pan.hit')}: {last.hit.rolls.join(' + ')} = <b>{last.hit.total}</b>
          {last.hit.target_ac != null &&
            ` ${tf('pan.vsAc', { ac: last.hit.target_ac })} → ${
              last.hit.hits ? t('pan.hits') : t('pan.misses')}`}
          <br />{t('pan.dmg')}: {last.damage.expression} = <b>{last.damage.total}</b>
          {last.notes?.length > 0 && <><br />{last.notes.join(' · ')}</>}
        </p>)}
    </div>
  )
}

export function CondChip({ name, onRemove, rules = COND_RULES }) {
  const { t, tf } = useT()
  const [open, setOpen] = useState(false)
  // 'exhaustion ×3' → regla de 'exhaustion' (sufijo de apilado)
  const rule = rules[name.replace(/\s*×\d+$/, '').toLowerCase()]
  return (
    <span>
      <span className="chip" role="button" tabIndex={0}
            title={t('pan.condTitle')}
            onClick={() => setOpen(!open)}
            onKeyDown={(e) => e.key === 'Enter' && setOpen(!open)}>
        {name}
        <button aria-label={tf('pan.condRemove', { name })}
                onClick={(e) => { e.stopPropagation(); onRemove() }}>×</button>
      </span>
      {open && (
        <p className="muted" style={{ margin: '.2rem 0 .4rem' }}>
          {rule || t('pan.condNone')}
        </p>)}
    </span>
  )
}

/* Paleta para colorear conjuros por uso — patrón DiceCloud:
   rojo=ataque, violeta=buff, azul=debuff, verde=apoyo,
   ámbar=utilidad. Persiste por personaje en localStorage. */
const SPELL_PALETTE =
  ['', '#e74c3c', '#9b59b6', '#3498db', '#27ae60', '#f39c12']

export function SpellList({ ids, onCast, onForget, onPin,
                             charId = 'x', preparedIds, onTogglePrepare,
                             onToBook }) {
  const { t, tf } = useT()
  const [names, setNames] = useState({})
  const [meta, setMeta] = useState({})
  const [menu, setMenu] = useState(null)
  const cKey = `dnd-spellcolors-${charId}`
  const [colors, setColors] = useState(() => {
    try { return JSON.parse(localStorage.getItem(cKey) || '{}') }
    catch { return {} }
  })
  const setColor = (sid, hex) => {
    setColors((c) => {
      const n = { ...c, [sid]: hex }
      localStorage.setItem(cKey, JSON.stringify(n))
      return n
    })
  }
  const navigate = useNavigate()
  useEffect(() => {
    for (const sid of ids) {
      if (names[sid]) continue
      api.getEntity(sid)
        .then((e) => {
          const dd = e.data || {}
          const school = typeof dd.school === 'string' ? dd.school
            : dd.school?.name || dd.school?.index
          const sub = [
            dd.level != null && `${t('pan.lv')} ${dd.level}`,
            school && String(school).replace(/_/g, ' '),
            (dd.concentration === true || dd.concentration === 'yes')
              && `⭑ ${t('pan.concTag')}`,
          ].filter(Boolean).join(' · ')
          setNames((n) => ({ ...n, [sid]: e.name || sid }))
          setMeta((m) => ({ ...m, [sid]: sub }))
        })
        .catch(() => setNames((n) => ({ ...n, [sid]: sid })))
    }
  }, [ids])
  return (
    <ul>
      {ids.map((sid) => (
        <li key={sid} className="row">
          <span className="spell-name" style={{
            flex: 1,
            borderLeft: colors[sid]
              ? `4px solid ${colors[sid]}` : 'none',
            paddingLeft: colors[sid] ? '0.4rem' : 0,
          }}>{preparedIds?.includes(sid) && (
              <span title={t('pan.prepared')}
                    style={{ color: 'var(--accent)' }}>
                ✔ </span>)}
            {/* nombre clicable → compendio, estilo Beyond */}
            <Link to={`/content/${encodeURIComponent(sid)}`}
                  style={{ color: 'inherit', textDecoration: 'none' }}>
              {names[sid] || sid}</Link>
            {meta[sid] && (
              <><br /><span className="muted"
                style={{ fontSize: '.8em' }}>{meta[sid]}</span></>)}
          </span>
          <button onClick={() => onCast(sid)}>{t('sheet.cast')}</button>
          <button className="ghost"
                  aria-label={tf('pan.spellOpts',
                                 { name: names[sid] || sid })}
                  aria-expanded={menu === sid}
                  onClick={() => setMenu(menu === sid ? null : sid)}>
            ⋮</button>
          {menu === sid && (
            <span className="row" role="menu">
              {onTogglePrepare && (
                <button className="ghost" onClick={() => {
                  setMenu(null); onTogglePrepare(sid)
                }}>{preparedIds?.includes(sid)
                    ? t('pan.unprepare') : t('pan.prepare')}</button>)}
              <button className="ghost"
                      title={t('pan.colorTitle')}
                      onClick={() => {
                const next = SPELL_PALETTE[
                  (SPELL_PALETTE.indexOf(colors[sid] || '') + 1)
                  % SPELL_PALETTE.length]
                setColor(sid, next)
              }}>{t('pan.color')} {colors[sid]
                && <i style={{ display: 'inline-block', width: 10,
                               height: 10, borderRadius: '50%',
                               background: colors[sid] }} />}</button>
              {onToBook && (
                <button className="ghost"
                        title={t('pan.toBookTitle')}
                        onClick={() => {
                  setMenu(null); onToBook(sid)
                }}>{t('pan.toBook')}</button>)}
              <button className="ghost" onClick={() => {
                setMenu(null); onPin?.(sid)
              }}>{t('common.pin')}</button>
              <button className="ghost" onClick={() => {
                setMenu(null)
                navigate(`/content/${encodeURIComponent(sid)}`)
              }}>{t('common.details')}</button>
              <button className="ghost" onClick={() => {
                setMenu(null); onForget(sid)
              }}>{t('common.forget')}</button>
            </span>)}
        </li>
      ))}
    </ul>
  )
}


export function FeatList({ ids, onForget }) {
  const [names, setNames] = useState({})
  useEffect(() => {
    for (const fid of ids) {
      if (names[fid]) continue
      api.getEntity(fid)
        .then((e) => setNames((n) => ({ ...n, [fid]: e.name || fid })))
        .catch(() => setNames((n) => ({ ...n, [fid]: fid })))
    }
  }, [ids])
  return (
    <ul>
      {ids.map((fid) => (
        <li key={fid} className="row">
          {/* wiki-link al compendio — la dote es una entidad */}
          <span style={{ flex: 1 }}>
            <Link to={`/content/${encodeURIComponent(fid)}`}
                  style={{ color: 'inherit', textDecoration: 'none' }}>
              {names[fid] || fid}</Link></span>
          <button className="ghost" onClick={() => onForget(fid)}>×</button>
        </li>))}
    </ul>
  )
}
