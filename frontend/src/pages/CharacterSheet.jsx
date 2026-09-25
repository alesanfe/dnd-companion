import { useEffect, useState } from 'react'
import { useParams, useNavigate, useSearchParams }
  from 'react-router-dom'
import { api } from '../api.js'
import { currentUser } from '../session.js'

const SHEET_TABS = [
  ['resumen', 'Resumen'], ['acciones', 'Acciones'],
  ['stats', 'Características'], ['magia', 'Magia'],
  ['inventario', 'Inventario'], ['rasgos', 'Rasgos'],
  ['historia', 'Historia'], ['actividad', 'Actividad'],
]

export default function CharacterSheet() {
  const { id, tab: routeTab } = useParams()
  const [char, setChar] = useState(null)
  const [amount, setAmount] = useState(1)
  const [charDmgType, setCharDmgType] = useState('')
  const [expr, setExpr] = useState('1d20')
  const [rollType, setRollType] = useState('check')
  const [rollLog, setRollLog] = useState([])
  const [err, setErr] = useState(null)
  const [history, setHistory] = useState(null)
  const [newItem, setNewItem] = useState('')
  const [newCond, setNewCond] = useState('')
  const [coin, setCoin] = useState('gp')
  const [actions, setActions] = useState(null)
  const [searchParams] = useSearchParams()
  const [focus, setFocus] = useState(       // modo partida (HUD)
    searchParams.get('focus') === '1')
  const [tab, _setTab] = useState(() => {
    const t = routeTab ||
      new URLSearchParams(window.location.search).get('tab')
    return SHEET_TABS.some(([k]) => k === t) ? t : 'resumen'
  })
  const setTab = (t) => {           // pestaña compartible vía URL
    _setTab(t)
    const u = new URL(window.location)
    u.pathname = `/character/${id}/${t}`
    u.searchParams.delete('tab')
    window.history.replaceState(null, '', u)
  }
  // HUD: qué grupos quedan visibles en vista rápida
  const [hud, setHud] = useState(
    () => new Set(['resumen']))
  const [notice, setNotice] = useState(null)  // aviso de concentración
  const [undoable, setUndoable] = useState(null)  // {id, label} toast deshacer
  const [journalEntry, setJournalEntry] = useState('')
  const [derived, setDerived] = useState(null)
  const [shops, setShops] = useState([])
  const [condOptions, setCondOptions] = useState([])
  const [atkItem, setAtkItem] = useState(null)   // arma en panel de ataque
  const [castId, setCastId] = useState(null)     // conjuro en panel de lanzamiento
  const [invTab, setInvTab] = useState('equipado')  // inventario interno

  const loadMeta = () => {
    api.derivedAll(id).then(setDerived).catch(() => {})
    api.contentOptions('condition').then((r) =>
      setCondOptions((r.options || []).map((o) =>
        o.id.split(':').pop()))).catch(() => {})
  }
  useEffect(() => { loadMeta() }, [id])
  useEffect(() => {
    if (!char?.campaign_id) return
    api.listEntities(char.campaign_id, 'shop', 'player')
      .then((r) => setShops(r.entities)).catch(() => {})
  }, [char?.campaign_id])

  const load = () => api.getCharacter(id).then(setChar).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [id])

  const [rollRequest, setRollRequest] = useState(null)
  const [xpAdd, setXpAdd] = useState(0)

  // Sync en vivo: si el personaje está en una campaña, escucha eventos
  // de la sala y recarga cuando algo lo toca. Las peticiones de tirada
  // del DM aparecen como banner accionable.
  useEffect(() => {
    if (!char?.campaign_id) return undefined
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const uid = currentUser()?.user_id
    const ws = new WebSocket(`${proto}://${location.host}/ws/campaign/${char.campaign_id}` + (uid ? `?user_id=${uid}` : ''))
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type !== 'event') return
      const ev = msg.event
      if (ev.aggregate_id !== id) return
      if (ev.type === 'dice.roll.requested') setRollRequest(ev.payload)
      else load()
    }
    return () => ws.close()
  }, [char?.campaign_id, id])

  const op = async (type, payload) => {
    try {
      const r = await api.applyOp(char, type, payload)
      if (r.operation_id) {
        setUndoable({ id: r.operation_id, label: type })
        setTimeout(() => setUndoable((u) =>
          u?.id === r.operation_id ? null : u), 8000)
      }
      // daño manteniendo concentración → avisa de la tirada de CON
      const cc = (r.events || []).find((e) => e.payload?.concentration_check)
      if (cc) {
        setNotice(`Concentración (${cc.payload.spell}): salva CON, CD ${cc.payload.concentration_dc}`)
      }
      // transparencia mecánica: resistencia/vuln/inmunidad aplicada
      const fx = (r.events || [])
        .flatMap((e) => e.payload?.damage_effects || [])
      if (fx.length) {
        setRollLog((l) => [`Daño aplicado: ${fx.join(' · ')}`, ...l].slice(0, 10))
      }
      load()
    } catch (e) {
      setErr(e.message)
      load() // resync on conflict
    }
  }

  const doRoll = async (e) => {
    e.preventDefault()
    // tirada a través del motor de efectos: aplica ventaja/desventaja y
    // mods declarativos activos sobre el personaje
    const r = await api.characterRoll(id, expr, rollType)
    const fx = (r.effects_applied || []).length
      ? ` [${r.effects_applied.join(', ')}]` : ''
    setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total}${fx}`, ...l].slice(0, 10))
  }

  if (err && !char) return <main><p className="error">{err}</p></main>
  if (!char) return <main><p>Cargando…</p></main>

  const d = char.data
  const hp = d.hp || { current: 0, max: 0, temp: 0 }
  const slots = d.spell_slots || {}

  return (
    <main className={focus ? 'concentration' : ''}>
      <h1>{char.name}
        <span className="muted" style={{ fontSize: '0.9rem' }}>
          {' '}nivel {d.classes?.reduce((s, c) => s + c.level, 0) || 1}
        </span>
      </h1>
      <div className="row">
        <button className={focus ? '' : 'ghost'}
                aria-pressed={focus}
                onClick={() => setFocus(!focus)}>
          {focus ? 'Salir de modo partida' : 'Modo partida'}
        </button>
        <button className="ghost" onClick={async () => {
          const h = await api.opHistory(id)
          const last = (h.operations || []).find((o) => o.reversible)
          if (last) { await api.undoOp(last.operation_id); load() }
        }}>↩ Deshacer</button>
        <button onClick={async () => {
          const ex = await api.exportCharacter(id)
          const blob = new Blob([JSON.stringify(ex, null, 2)],
                                { type: 'application/json' })
          const a = document.createElement('a')
          a.href = URL.createObjectURL(blob)
          a.download = `${char.name}.json`
          a.click()
        }}>Exportar</button>
        {d.classes?.length > 0 && (
          <button onClick={() =>
            op('character.level_up',
               { class_id: d.classes[0].class_id, hp_mode: 'fixed' })}>
            Subir nivel
          </button>
        )}
        <button onClick={async () => {
          const h = await api.opHistory(id)
          setHistory(history ? null : h.operations)
        }}>Historial</button>
      </div>
      {err && <p className="error">{err}</p>}
      {notice && (
        <p className="notice" role="alert">
          {notice} <button onClick={() => setNotice(null)}>OK</button>
        </p>
      )}
      {undoable && (
        <p className="notice" role="status">
          Operación aplicada
          <button onClick={async () => {
            await api.undoOp(undoable.id)
            setUndoable(null); load()
          }}>Deshacer</button>
          <button className="ghost"
                  onClick={() => setUndoable(null)}>×</button>
        </p>)}

      {rollRequest && (
        <section className="card" role="alert">
          <h2>El DM pide una tirada</h2>
          <p><strong>{rollRequest.expression}</strong>
            {rollRequest.reason && ` — ${rollRequest.reason}`}
            {rollRequest.secret && <span className="muted"> (secreta)</span>}
          </p>
          <button onClick={async () => {
            const r = await api.characterRoll(id, rollRequest.expression, 'check')
            setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total}`, ...l].slice(0, 10))
            setRollRequest(null)
          }}>Tirar {rollRequest.expression}</button>
          <button className="ghost" title="Solo la ve el DM"
                  onClick={async () => {
            const r = await api.characterRoll(
              id, rollRequest.expression, 'check', false, true)
            setRollLog((l) => [
              `🔒 ${r.expression} → ${r.total} (privada)`, ...l]
              .slice(0, 10))
            setRollRequest(null)
          }}>Privada</button>
          <button className="ghost" onClick={() => setRollRequest(null)}>Descartar</button>
        </section>
      )}

      {/* vitales siempre a mano: cabecera pegajosa sobre las pestañas */}
      <div className="sticky-head">
        <div className="vital">
          <span className="num">{hp.current}/{hp.max}{hp.temp > 0 &&
            `+${hp.temp}`} PG</span>
          {derived && <>
            <span>CA <b>{derived.armor_class.total}</b></span>
            <span>Init {derived.initiative >= 0 ? '+' : ''}
              {derived.initiative}</span>
            <span>Prof +{derived.proficiency_bonus}</span>
          </>}
          {d.concentrating_on &&
            <span className="muted">⭑ {d.concentrating_on}</span>}
          {d.conditions?.length > 0 &&
            <span className="muted">{d.conditions.join(' · ')}</span>}
        </div>
        {focus && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {[['combate', ['resumen', 'acciones', 'magia']],
              ['exploración', ['resumen', 'stats', 'inventario']],
              ['interacción', ['resumen', 'rasgos', 'historia']],
              ['todo', SHEET_TABS.map(([k]) => k)]]
              .map(([p, groups]) => (
              <button key={p} className="ghost" style={{ fontSize: '.85em' }}
                      onClick={() => setHud(new Set(groups))}>
                {p[0].toUpperCase() + p.slice(1)}</button>))}
            <span className="muted">·</span>
            {SHEET_TABS.map(([k, label]) => (
                <label key={k} className="muted"
                       style={{ fontSize: '.85em' }}>
                  <input type="checkbox" checked={hud.has(k)}
                    onChange={(e) => setHud((prev) => {
                      const nx = new Set(prev)
                      e.target.checked ? nx.add(k) : nx.delete(k)
                      return nx
                    })} />
                  {label}</label>))}
          </div>)}
        {!focus && (
          <nav className="tabs" role="tablist" aria-label="Secciones">
            {SHEET_TABS.map(([k, label]) => (
                <button key={k} role="tab" aria-selected={tab === k}
                        onClick={() => setTab(k)}>{label}</button>))}
          </nav>)}
      </div>

      <div className="row" hidden={focus ? !hud.has('resumen') : tab !== 'resumen'}>
        <span className="muted">PX: {d.xp || 0}</span>
        <input type="number" min="0" style={{ maxWidth: 90 }} value={xpAdd}
               onChange={(e) => setXpAdd(+e.target.value)} />
        <button disabled={!xpAdd} onClick={() => {
          op('character.xp.add', { amount: xpAdd }); setXpAdd(0)
        }}>+XP</button>
        {d.inspiration
          ? <span className="chip">✦ Inspiración
              <button aria-label="Gastar inspiración" onClick={async () => {
                const r = await api.characterRoll(id, expr, rollType, true)
                setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total} [inspiración]`, ...l].slice(0, 10))
                await op('character.inspiration.set', { value: false })
              }}>usar</button>
              <button aria-label="Quitar inspiración" onClick={() =>
                op('character.inspiration.set', { value: false })}>×</button>
            </span>
          : <button className="ghost" onClick={() =>
              op('character.inspiration.set', { value: true })}>
              ✦ Sin inspiración</button>}
        {d.concentrating_on && (
          <span className="chip">
            ⭑ {d.concentrating_on}
            <button aria-label="Romper concentración" onClick={() =>
              op('character.concentration.break', {})}>×</button>
          </span>
        )}
      </div>

      {history && (
        <section className="card optional" hidden={focus ? !hud.has('actividad') : tab !== 'actividad'}>
          <h2>Historial <span className="muted">(reversible)</span></h2>
          {history.map((h) => (
            <div key={h.operation_id} className="row">
              <span className="muted">{h.timestamp.slice(11, 19)}</span>
              <span style={{ flex: 1 }}>{h.operation_type}</span>
              {h.reversible ? (
                <>
                <button onClick={async () => {
                  await api.undoOp(h.operation_id)
                  setHistory(null)
                  load()
                }}>Deshacer</button>
                <button className="ghost"
                        title="Deshace esta operación y todas las
                               posteriores, en orden inverso"
                        onClick={async () => {
                  const idx = history.indexOf(h)
                  for (const x of history.slice(0, idx + 1)) {
                    if (x.reversible)
                      await api.undoOp(x.operation_id)
                  }
                  setHistory(null)
                  load()
                }}>Hasta aquí</button>
                </>
              ) : <span className="muted">—</span>}
            </div>
          ))}
        </section>
      )}

      {derived && (
        <section className="card" hidden={focus ? !hud.has('stats') : tab !== 'stats'}>
          <h2>Calculado</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <span className="coin">CA {derived.armor_class.total}</span>
            <span className="coin">Init {derived.initiative >= 0 ? '+' : ''}{derived.initiative}</span>
            <span className="coin">Perc. pasiva {derived.passive_perception}</span>
            {d.spells_known?.length > 0 && <>
              <span className="coin">CD {derived.spell_save_dc}</span>
              <span className="coin">Ataque {derived.spell_attack >= 0 ? '+' : ''}{derived.spell_attack}</span>
            </>}
            <span className="coin">Prof +{derived.proficiency_bonus}</span>
          </div>
          <p className="muted">CA = {derived.armor_class.breakdown
            .map(([n, v]) => `${n} ${v > 0 ? '+' : ''}${v}`).join(' ')}</p>
        </section>
      )}

      {/* hoja 2024: habilidades agrupadas por característica, cada
          valor pulsable para tirar */}
      <section className="card" hidden={focus ? !hud.has('stats') : tab !== 'stats'}>
        <h2>Características</h2>
        <div className="ability-grid">
          {STATS.map(([ab, label, skills]) => {
            const score = d.abilities?.[ab] ?? 10
            const mod = Math.floor((score - 10) / 2)
            const prof = derived?.proficiency_bonus ?? 2
            const saveProf = d.save_proficiencies?.includes(ab)
            const rollIt = async (kind, bonus, name) => {
              const r = await api.characterRoll(
                id, `1d20${bonus >= 0 ? '+' : ''}${bonus}`, kind)
              setRollLog((l) => [
                `${name}: ${r.kept.join('+')} = ${r.total}`, ...l]
                .slice(0, 10))
            }
            return (
              <div key={ab} className="ability-cell">
                <span className="muted">{label}</span>
                <strong className="num">{score}</strong>
                <button className="ghost" style={{ fontSize: '1.1em' }}
                        aria-label={`Prueba de ${label}`}
                        onClick={() =>
                          rollIt('check', mod, label)}>
                  {mod >= 0 ? '+' : ''}{mod}</button>
                <button className="ghost" style={{ fontSize: '.8em' }}
                        aria-label={`Salvación de ${label}${
                          saveProf ? ' (competente)' : ''}`}
                        onClick={() => rollIt(
                          'save', mod + (saveProf ? prof : 0),
                          `Salv. ${label}`)}>
                  Salv {saveProf ? '●' : '○'}{' '}
                  {mod + (saveProf ? prof : 0) >= 0 ? '+' : ''}
                  {mod + (saveProf ? prof : 0)}</button>
                <ul className="skill-list">
                  {skills.map(([sid, sname]) => {
                    const profs = d.skill_proficiencies || []
                    const p = profs.includes(sid) ||
                              profs.includes(sid.replace(/-/g, ' '))
                    const bonus = mod + (p ? prof : 0)
                    return (
                      <li key={sid}>
                        <button className="ghost"
                                style={{ fontSize: '.8em',
                                         textAlign: 'left' }}
                                aria-label={`Habilidad ${sname}${
                                  p ? ' (competente)' : ''}`}
                                onClick={() =>
                                  rollIt('check', bonus, sname)}>
                          {p ? '●' : '○'} {sname}{' '}
                          {bonus >= 0 ? '+' : ''}{bonus}</button>
                      </li>)})}
                </ul>
              </div>)
          })}
        </div>
        <p className="muted" style={{ fontSize: '.8rem' }}>
          ○ sin competencia · ● competente — pulsa para tirar</p>
        <details>
          <summary className="muted" style={{ cursor: 'pointer' }}>
            Edición avanzada (puntuaciones y nombre)</summary>
          <div className="row">
            <input defaultValue={char.name} aria-label="Nombre"
                   onBlur={async (e) => {
                     if (e.target.value.trim() &&
                         e.target.value !== char.name) {
                       await api.patchCharacter(
                         id, { name: e.target.value.trim() })
                       load()
                     }
                   }} />
          </div>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {STATS.map(([ab, label]) => (
              <label key={ab} className="muted"
                     style={{ fontSize: '.8rem' }}>
                {label.slice(0, 3).toUpperCase()}
                <input type="number" min="1" max="30"
                       defaultValue={d.abilities?.[ab] ?? 10}
                       style={{ maxWidth: 64, display: 'block' }}
                       aria-label={`Puntuación de ${label}`}
                       onBlur={(e) =>
                         op('character.ability.set',
                            { ability: ab,
                              value: +e.target.value })} />
              </label>))}
          </div>
        </details>
        {derived && (() => {
          const prof = derived.proficiency_bonus
          const profs = d.skill_proficiencies || []
          const has = (s) => profs.includes(s) ||
                             profs.includes(s.replace(/ /g, '-'))
          const mod = (a) => Math.floor(((d.abilities?.[a] ?? 10) - 10) / 2)
          const pas = (skill, ab) =>
            10 + mod(ab) + (has(skill) ? prof : 0)
          return (
            <div className="row" style={{ flexWrap: 'wrap' }}>
              <span className="coin">
                Perc. pasiva {pas('perception', 'wis')}</span>
              <span className="coin">
                Invest. pasiva {pas('investigation', 'int')}</span>
              <span className="coin">
                Perspic. pasiva {pas('insight', 'wis')}</span>
            </div>)
        })()}
      </section>

      <section className="card" hidden={focus ? !hud.has('resumen') : tab !== 'resumen'}>
        <h2>Experiencia</h2>
        <div className="row">
          <span>XP {d.xp || 0}
            {derived?.next_level_xp &&
              <span className="muted"> / {derived.next_level_xp}
                {' '}para nivel {(d.classes || [])
                  .reduce((a, c) => a + c.level, 0) + 1}</span>}
          </span>
          <input type="number" min="1" value={amount}
                 onChange={(e) => setAmount(+e.target.value)}
                 aria-label="XP a sumar" />
          <button onClick={() =>
            op('character.xp.add', { amount })}>+XP</button>
          {derived?.next_level_xp != null &&
            (d.xp || 0) >= derived.next_level_xp && (
            <button className="primary" onClick={() =>
              op('character.level_up', { hp_mode: 'fixed' })}>
              Subir de nivel</button>)}
        </div>
      </section>

      <section className="card" hidden={focus ? !hud.has('resumen') : tab !== 'resumen'}>
        <h2>Puntos de golpe</h2>
        <div className="hp-big">
          {hp.current} / {hp.max}
          {hp.temp > 0 && <span className="temp"> +{hp.temp} temp</span>}
        </div>
        <div className="hp-bar" role="img"
             aria-label={`PG ${hp.current} de ${hp.max}`}>
          <div style={{
            width: `${hp.max ? Math.round(100 * hp.current / hp.max) : 0}%`,
            background: hp.max && hp.current / hp.max <= 0.25
              ? 'var(--danger)' : 'var(--success)' }} />
        </div>
        <div className="row">
          <input type="number" min="1" value={amount}
                 onChange={(e) => setAmount(+e.target.value)} />
          <select value={charDmgType}
                  onChange={(e) => setCharDmgType(e.target.value)}
                  aria-label="Tipo de daño" style={{ maxWidth: 130 }}>
            <option value="">sin tipo</option>
            {['fire', 'cold', 'lightning', 'poison', 'acid', 'necrotic',
              'radiant', 'psychic', 'thunder', 'force', 'bludgeoning',
              'piercing', 'slashing']
              .map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <button className="dmg" onClick={() =>
            op('character.hp.damage',
               { amount, type: charDmgType || undefined })}>Daño</button>
          <button className="heal" onClick={() =>
            op('character.hp.heal', { amount })}>Curar</button>
        </div>
      </section>

      <section className="card" hidden={focus ? !hud.has('resumen') : tab !== 'resumen'}>
        <h2>Descansos</h2>
        <div className="row">
          <button onClick={() => op('character.rest.short', {})}>Descanso corto</button>
          <button onClick={() => op('character.rest.long', {})}>Descanso largo</button>
        </div>
        {(d.hit_dice || []).map((p, i) => (
          <div key={i} className="row">
            <span>Dados de golpe {p.die}: {p.remaining}/{p.total}</span>
            <button disabled={p.remaining <= 0}
                    onClick={() => op('character.hit_die.spend', { pool: i })}>
              Gastar
            </button>
          </div>
        ))}
      </section>

      {Object.keys(slots).length > 0 && (
        <section className="card" hidden={focus ? !hud.has('magia') : tab !== 'magia'}>
          <h2>Espacios de conjuro</h2>
          {Object.entries(slots).map(([lvl, s]) => (
            <div key={lvl} className="row">
              <span aria-label={`Espacios nivel ${lvl}: ${
                s.total - s.used} de ${s.total} disponibles`}>
                Nv.{lvl}{' '}
                <span className="coin">
                  {'●'.repeat(s.total - s.used)}{'○'.repeat(s.used)}
                </span>{' '}
                {s.total - s.used}/{s.total}</span>
              <button disabled={s.used >= s.total}
                      onClick={() => op('character.spell_slot.use', { level: +lvl })}>
                Usar
              </button>
            </div>
          ))}
        </section>
      )}

      {(d.resources || []).length > 0 && (
        <section className="card" hidden={focus ? !hud.has('resumen') : tab !== 'resumen'}>
          <h2>Usos limitados</h2>
          {Object.entries(d.resources.reduce((g, r) => {
            (g[r.reset_on || 'long'] ??= []).push(r)
            return g
          }, {})).sort(([a], [b]) =>
            RESET_ORDER.indexOf(a) - RESET_ORDER.indexOf(b))
            .map(([reset, list]) => (
              <div key={reset}>
                <h3 className="muted" style={{ fontSize: '.85rem' }}>
                  {RESET_LABELS[reset] || reset}</h3>
                {list.map((r) => (
            <div key={r.id} className="row">
              <span style={{ flex: 1 }}>{r.name}: {r.current}/{r.max}</span>
              {r.current > 0
                ? <button onClick={() => op('character.resource.consume',
                                           { resource_id: r.id })}>
                    Usar</button>
                : <span className="muted">Agotado</span>}
            </div>
          ))}
              </div>))}
        </section>
      )}

      <section className="card optional" hidden={focus ? !hud.has('inventario') : tab !== 'inventario'}>
        <h2>Monedas</h2>
        <div className="row purse">
          {['pp', 'gp', 'ep', 'sp', 'cp'].map((c) => (
            <span key={c} className="coin">{c.toUpperCase()}: {(d.purse || {})[c] || 0}</span>
          ))}
        </div>
        <div className="row">
          <input type="number" min="1" value={amount}
                 onChange={(e) => setAmount(+e.target.value)} />
          <select value={coin} onChange={(e) => setCoin(e.target.value)}>
            {['pp', 'gp', 'ep', 'sp', 'cp'].map((c) => <option key={c}>{c}</option>)}
          </select>
          <button className="heal" onClick={() => op('character.currency.earn', { [coin]: amount })}>+</button>
          <button className="dmg" onClick={() => op('character.currency.spend', { [coin]: amount })}>-</button>
        </div>
      </section>

      <section className="card" hidden={focus ? !hud.has('acciones') : tab !== 'acciones'}>
        <h2>Acciones</h2>
        <button onClick={async () => {
          if (actions) { setActions(null); return }
          const r = await fetch(`/api/characters/${id}/actions`).then((x) => x.json())
          setActions(r.actions)
        }}>{actions ? 'Ocultar' : 'Ver acciones disponibles'}</button>
        {actions && Object.entries(actions).map(([g, list]) => (
          <div key={g}>
            <h3 className="muted" style={{ textTransform: 'capitalize' }}>{g.replace('_', ' ')}</h3>
            <ul>{list.map((a, i) => (
              <li key={i}>{a.name}
                {a.hit && <span className="muted"> {a.hit} · {a.damage}</span>}
                {a.name.startsWith('Ataque:') && (
                  <button style={{ minHeight: 32, marginLeft: 8 }}
                          onClick={async () => {
                    const w = a.name.replace('Ataque: ', '')
                    const r = await api.characterAttack(id, w)
                    setRollLog((l) => [`${w}: impacto ${r.hit.total} · daño ${r.damage.total}`, ...l].slice(0, 10))
                  }}>⚔</button>
                )}
                {a.name.startsWith('Conjuro:') && (
                  <button style={{ minHeight: 32, marginLeft: 8 }}
                          onClick={async () => {
                    await op('character.spell.cast',
                             { spell_id: a.source, level: 0 })
                  }}>✦</button>
                )}
              </li>))}
            </ul>
          </div>
        ))}
      </section>

      {(d.effects || []).length > 0 && (
        <section className="card optional" hidden={focus ? !hud.has('acciones') : tab !== 'acciones'}>
          <h2>Efectos activos</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.effects.map((e) => (
              <span key={e.id} className="chip" title={e.source}>
                {e.name}
                <button aria-label={`Quitar efecto ${e.name}`} onClick={() =>
                  op('character.effect.remove', { effect_id: e.id })}>×</button>
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="card optional" hidden={focus ? !hud.has('resumen') : tab !== 'resumen'}>
        <h2>Condiciones</h2>
        <div className="row">
          <input value={newCond} onChange={(e) => setNewCond(e.target.value)}
                 placeholder="poisoned, stunned…" list="cond-list" />
          <datalist id="cond-list">
            {condOptions.map((c) => <option key={c} value={c} />)}
          </datalist>
          <button disabled={!newCond.trim()} onClick={() => {
            op('character.condition.apply', { condition: newCond.trim() })
            setNewCond('')
          }}>Aplicar</button>
        </div>
        {(d.conditions || []).map((c) => (
          <CondChip key={c} name={c}
                    onRemove={() => op('character.condition.remove',
                                       { condition: c })} />
        ))}
      </section>

      <section className="card optional" hidden={focus ? !hud.has('inventario') : tab !== 'inventario'}>
        <h2>Inventario</h2>
        <p className="muted">
          Sintonizados:{' '}
          {(d.inventory || []).filter((i) => i.attuned).length}/3
        </p>
        <ItemPicker onPick={(it) =>
          op('character.inventory.add',
             { name: it.name, source_id: it.id })} />
        <div className="row">
          <input value={newItem} onChange={(e) => setNewItem(e.target.value)}
                 placeholder="Objeto manual" />
          <button disabled={!newItem.trim()} onClick={() => {
            op('character.inventory.add', { name: newItem.trim() })
            setNewItem('')
          }}>Añadir</button>
        </div>
        <div className="row tabs" role="tablist"
             aria-label="Inventario">
          {[['equipado', 'Equipado'], ['mochila', 'Mochila'],
            ['consumibles', 'Consumibles']].map(([k, l]) => (
            <button key={k} role="tab" aria-selected={invTab === k}
                    onClick={() => setInvTab(k)}>{l}</button>))}
        </div>
        {(d.inventory || []).filter((it) => {
          if (invTab === 'equipado') return it.equipped
          const consum = /poci|potion|scroll|pergamino|antorcha|torch|flecha|arrow|raci[oó]n|ration/i.test(it.name)
          if (invTab === 'consumibles') return consum && !it.equipped
          return !it.equipped && !consum          // mochila
        }).map((it) => (
          <div key={it.id} className="row">
            <span style={{ flex: 1 }}>
              {it.name} ×{it.quantity}
              {it.equipped && <span className="muted"> · equipado</span>}
              {it.attuned && <span className="muted"> · sintonizado</span>}
            </span>
            {it.source_id && (
              <button onClick={() => setAtkItem(it)}>Atacar</button>)}
            <button onClick={() =>
              op(it.equipped ? 'character.item.unequip'
                             : 'character.item.equip',
                 { item_id: it.id })
            }>{it.equipped ? 'Quitar' : 'Equipar'}</button>
            <button onClick={() => op('character.inventory.remove',
                                      { item_id: it.id, quantity: 1 })}>-</button>
          </div>
        ))}
        {invTab === 'equipado' &&
          !(d.inventory || []).some((i) => i.equipped) && (
          <p className="muted">Nada equipado — marca objetos desde la
             mochila.</p>)}
        {atkItem && (
          <AttackPanel charId={id} item={atkItem}
                       onResult={(line) =>
                         setRollLog((l) => [line, ...l].slice(0, 10))}
                       onClose={() => setAtkItem(null)} />)}
      </section>

      <section className="card" hidden={focus ? !hud.has('acciones') : tab !== 'acciones'}>
        <h2>Dados</h2>
        <form onSubmit={doRoll} className="row">
          <input value={expr} onChange={(e) => setExpr(e.target.value)}
                 placeholder="2d6+3, 1d20adv, 4d6kh3" />
          <select value={rollType} onChange={(e) => setRollType(e.target.value)}>
            <option value="check">check</option>
            <option value="attack">attack</option>
            <option value="damage">damage</option>
            <optgroup label="Salvaciones">
              {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
                <option key={a} value={`save:${a}`}>save:{a}</option>))}
            </optgroup>
            <optgroup label="Habilidades">
              {['skill:perception', 'skill:stealth', 'skill:athletics',
                'skill:insight', 'skill:investigation', 'skill:persuasion']
                .map((s) => <option key={s} value={s}>{s.slice(6)}</option>)}
            </optgroup>
          </select>
          <button type="submit">Tirar</button>
        </form>
        <ul className="log" role="status" aria-live="polite">
          {rollLog.map((l, i) => <li key={i}>{l}</li>)}</ul>
      </section>

      <section className="card optional" hidden={focus ? !hud.has('magia') : tab !== 'magia'}>
        <h2>Conjuros</h2>
        <SpellPicker onPick={(sid) =>
          op('character.spell.learn', { spell_id: sid })}
          placeholder="Aprender conjuro — buscar en todas las fuentes"
          forClass={d.classes?.[0]?.class_id?.split(/[:|]/).pop()
                    .replace(/-/g, ' ')} />
        {(d.spells_known || []).length > 0 && (
          <SpellList ids={d.spells_known}
            onCast={(sid) => setCastId(sid)}
            onForget={(sid) =>
              op('character.spell.forget', { spell_id: sid })} />
        )}
        {castId && (
          <CastPanel charId={id} spellId={castId} slots={slots}
                     concentrating={d.concentrating_on}
                     onCast={async (lvl) => {
                       setCastId(null)
                       await op('character.spell.cast',
                                { spell_id: castId, level: lvl })
                     }}
                     onClose={() => setCastId(null)} />)}
      </section>

      {shops.length > 0 && (
        <section className="card optional" hidden={focus ? !hud.has('inventario') : tab !== 'inventario'}>
          <h2>Tienda</h2>
          {shops.map((s) => (
            <div key={s.id}>
              <h3 className="muted">{s.name}</h3>
              {(s.data.stock || []).filter((x) => x.quantity > 0).map((it) => (
                <div key={it.name} className="row">
                  <span style={{ flex: 1 }}>{it.name} ×{it.quantity}</span>
                  <span className="muted">{it.price_cp}cp</span>
                  <button onClick={async () => {
                    await op('character.shop.buy',
                             { shop_id: s.id, item: it.name })
                    api.listEntities(char.campaign_id, 'shop', 'player')
                      .then((r) => setShops(r.entities))
                  }}>Comprar</button>
                </div>
              ))}
            </div>
          ))}
        </section>
      )}

      <section className="card optional" hidden={focus ? !hud.has('rasgos') : tab !== 'rasgos'}>
        <h2>Rasgos</h2>
        <SpellPicker entityType="feature" verb="Añadir"
          placeholder="Rasgo opcional (invocación, infusión, maniobra…)"
          onPick={(fid) =>
            op('character.feature.add', { entity_id: fid })} />
        {(d.features || []).length > 0 && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.features.map((f) => (
              <span key={f} className="chip">{f}
                <button aria-label={`Quitar rasgo ${f}`} onClick={() =>
                  op('character.feature.remove', { name: f })
                }>×</button></span>))}
          </div>)}
      </section>

      <section className="card optional" hidden={focus ? !hud.has('rasgos') : tab !== 'rasgos'}>
        <h2>Dotes y dones</h2>
        <SpellPicker entityType="feat" verb="Añadir"
          placeholder="Buscar dote en todas las fuentes"
          onPick={(fid) =>
            op('character.feat.learn', { feat_id: fid })} />
        {(d.feats_known || []).length > 0 && (
          <FeatList ids={d.feats_known} onForget={(fid) =>
            op('character.feat.forget', { feat_id: fid })} />)}
        <SpellPicker entityType="reward" verb="Añadir"
          placeholder="Don sobrenatural / bendición (charm, boon…)"
          onPick={(rid) =>
            op('character.reward.add', { reward_id: rid })} />
        {(d.rewards || []).length > 0 && (
          <FeatList ids={d.rewards} onForget={(rid) =>
            op('character.reward.remove', { reward_id: rid })} />)}
      </section>

      <section className="card optional" hidden={focus ? !hud.has('rasgos') : tab !== 'rasgos'}>
        <h2>Subclase e idiomas</h2>
        <SpellPicker entityType="subclass" verb="Elegir"
          placeholder="Buscar subclase…"
          onPick={(sid) =>
            op('character.subclass.set',
               { class_index: 0, subclass_id: sid })} />
        {(d.classes || []).map((c, i) => (
          <p key={i} className="muted">
            {c.class_id}{c.subclass_id ? ` · ${c.subclass_id}` : ''}
            {' · nv.'}{c.level}</p>))}
        <SpellPicker entityType="language" verb="Añadir"
          placeholder="Idioma (elfo, común, dracónico…)"
          onPick={(lid) =>
            op('character.language.add',
               { name: lid.split(':').pop().split('|')[0] })} />
        {(d.languages || []).length > 0 && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.languages.map((l) => (
              <span key={l} className="chip">{l}
                <button aria-label={`Quitar idioma ${l}`} onClick={() =>
                  op('character.language.remove', { name: l })
                }>×</button></span>))}
          </div>)}
      </section>

      <section className="card optional" hidden={focus ? !hud.has('stats') : tab !== 'stats'}>
        <h2>Competencias</h2>
        <SpellPicker entityType="skill" verb="Competente"
          placeholder="Habilidad (percepción, sigilo…)"
          onPick={(sid) =>
            op('character.proficiency.add',
               { kind: 'skill',
                 name: sid.split(':').pop().split('|')[0]
                      .replace(/-/g, ' ') })} />
        <div className="row">
          <span className="muted">Salvación:</span>
          {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
            <button key={a} className="ghost" onClick={() =>
              op('character.proficiency.add',
                 { kind: 'save', name: a })}>{a.toUpperCase()}</button>))}
        </div>
        {(d.skill_proficiencies?.length > 0 || d.save_proficiencies?.length > 0) && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.save_proficiencies?.map((s) => (
              <span key={s} className="chip">save:{s}
                <button aria-label={`Quitar competencia ${s}`} onClick={() =>
                  op('character.proficiency.remove',
                     { kind: 'save', name: s })}>×</button>
              </span>))}
            {d.skill_proficiencies?.map((s) => (
              <span key={s} className="chip">{s}
                <button aria-label={`Quitar competencia ${s}`} onClick={() =>
                  op('character.proficiency.remove',
                     { kind: 'skill', name: s })}>×</button>
              </span>))}
          </div>
        )}
      </section>

      <section className="card optional" hidden={focus ? !hud.has('historia') : tab !== 'historia'}>
        <h2>Diario</h2>
        <div className="row">
          <input value={journalEntry} placeholder="Anotación de la sesión…"
                 onChange={(e) => setJournalEntry(e.target.value)} />
          <button disabled={!journalEntry.trim()} onClick={() => {
            op('character.journal.add', { entry: journalEntry.trim() })
            setJournalEntry('')
          }}>Anotar</button>
        </div>
        <ul>{(d.narrative?.journal || []).map((j, i) => <li key={i}>{j}</li>)}</ul>
      </section>
    </main>
  )
}


function ItemPicker({ onPick }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const go = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    const r = await api.search(q.trim())
    setHits(r.results
      .filter((h) => ['item', 'magic-item', 'equipment']
        .includes(h.entity_type))
      .slice(0, 12))
  }
  return (
    <div>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Buscar objeto en el corpus (daga, potion…)" />
        <button type="submit">Buscar</button>
      </form>
      {hits.length > 0 && (
        <ul>
          {hits.map((h) => (
            <li key={h.id} className="row">
              <span style={{ flex: 1 }}>{h.name}
                <span className="muted"> · {h.source_id}</span></span>
              <button onClick={() => { onPick(h); setHits([]) }}>
                Añadir</button>
            </li>))}
        </ul>)}
    </div>
  )
}


function SpellPicker({ onPick, entityType = 'spell',
                      verb = 'Aprender',
                      placeholder = 'Buscar en todas las fuentes',
                      forClass }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [onlyClass, setOnlyClass] = useState(Boolean(forClass))
  const go = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    const r = await api.search(q.trim(), entityType, undefined,
                               onlyClass ? forClass : undefined)
    setHits(r.results.slice(0, 12))
  }
  return (
    <div>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={placeholder} />
        <button type="submit">Buscar</button>
      </form>
      {forClass && (
        <label className="row muted" style={{ fontSize: '.85em' }}>
          <input type="checkbox" checked={onlyClass}
                 onChange={(e) => setOnlyClass(e.target.checked)} />
          solo lista de {forClass}
        </label>)}
      {hits.length > 0 && (
        <ul>
          {hits.map((h) => (
            <li key={h.id} className="row">
              <span style={{ flex: 1 }}>{h.name}
                <span className="muted"> · {h.source_id}</span></span>
              <button onClick={() => { onPick(h.id); setHits([]) }}>
                {verb}</button>
            </li>))}
        </ul>)}
    </div>
  )
}


/** Efecto mecánico SRD de la condición — espejo de
    domain/conditions.py (los nombres en ES se muestran tal cual). */
/** [id, etiqueta, habilidades] — agrupación de la hoja oficial 2024. */
const STATS = [
  ['str', 'Fuerza', [['athletics', 'Atletismo']]],
  ['dex', 'Destreza', [['acrobatics', 'Acrobacias'],
                      ['sleight-of-hand', 'Juego de manos'],
                      ['stealth', 'Sigilo']]],
  ['con', 'Constitución', []],
  ['int', 'Inteligencia', [['arcana', 'Arcana'], ['history', 'Historia'],
                          ['investigation', 'Investigación'],
                          ['nature', 'Naturaleza'],
                          ['religion', 'Religión']]],
  ['wis', 'Sabiduría', [['animal-handling', 'Trato animal'],
                       ['insight', 'Perspicacia'],
                       ['medicine', 'Medicina'],
                       ['perception', 'Percepción'],
                       ['survival', 'Supervivencia']]],
  ['cha', 'Carisma', [['deception', 'Engaño'],
                      ['intimidation', 'Intimidación'],
                      ['performance', 'Interpretación'],
                      ['persuasion', 'Persuasión']]],
]

const RESET_ORDER = ['short', 'dawn', 'long', 'none']
const RESET_LABELS = { short: 'Descanso corto', dawn: 'Al amanecer',
                       long: 'Descanso largo', none: 'Sin recuperación' }

const COND_RULES = {
  blinded: 'Desventaja en ataques', cegado: 'Desventaja en ataques',
  cegada: 'Desventaja en ataques',
  invisible: 'Ventaja en ataques',
  poisoned: 'Desventaja en ataques y pruebas',
  envenenado: 'Desventaja en ataques y pruebas',
  envenenada: 'Desventaja en ataques y pruebas',
  prone: 'Desventaja en ataques', tumbado: 'Desventaja en ataques',
  derribado: 'Desventaja en ataques', postrado: 'Desventaja en ataques',
  restrained: 'Desventaja en ataques y salvaciones de DES',
  apresado: 'Desventaja en ataques y salvaciones de DES',
  apresada: 'Desventaja en ataques y salvaciones de DES',
  frightened: 'Desventaja en ataques y pruebas',
  asustado: 'Desventaja en ataques y pruebas',
  atemorizado: 'Desventaja en ataques y pruebas',
  stunned: 'Incapacitado · autofallo STR/DES', aturdido: 'Incapacitado · autofallo STR/DES',
  aturdida: 'Incapacitado · autofallo STR/DES',
  paralyzed: 'Incapacitado · autofallo STR/DES',
  paralizado: 'Incapacitado · autofallo STR/DES',
  paralizada: 'Incapacitado · autofallo STR/DES',
  petrified: 'Incapacitado · autofallo STR/DES',
  petrificado: 'Incapacitado · autofallo STR/DES',
  unconscious: 'Incapacitado · autofallo STR/DES',
  inconsciente: 'Incapacitado · autofallo STR/DES',
  incapacitated: 'Sin acciones ni reacciones',
  incapacitado: 'Sin acciones ni reacciones',
  incapacitada: 'Sin acciones ni reacciones',
  exhaustion: 'Desventaja en pruebas (3+: también ataques y saves)',
  exhausto: 'Desventaja en pruebas (3+: también ataques y saves)',
  agotado: 'Desventaja en pruebas (3+: también ataques y saves)',
  grappled: 'Velocidad 0', agarrado: 'Velocidad 0',
  agarrada: 'Velocidad 0',
  dead: 'Muerto', muerto: 'Muerto', muerta: 'Muerto',
}

/** Panel de lanzamiento: elige nivel de espacio, muestra CD/daño
    y avisa si rompe una concentración activa. */
function CastPanel({ spellId, slots, concentrating, onCast, onClose }) {
  const [sp, setSp] = useState(null)
  const [lvl, setLvl] = useState(null)
  useEffect(() => {
    api.getEntity(spellId).then((e) => {
      setSp(e)
      setLvl(e.data?.level ?? 0)
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
    .map(([k]) => +k)
  const options = [...new Set([base, ...avail])].sort((a, b) => a - b)
  const slot = slots[lvl] || slots[String(lvl)]
  return (
    <div className="card" role="dialog" aria-label={`Lanzar ${sp.name}`}
         style={{ background: 'var(--card-raised)' }}>
      <strong>Lanzar {sp.name}</strong>
      <div className="row">
        <span className="muted">Nivel de espacio</span>
        <select value={lvl ?? base}
                onChange={(e) => setLvl(+e.target.value)}>
          {options.map((v) => (
            <option key={v} value={v}
                    disabled={v !== 0 && !(slots[v]?.used < slots[v]?.total)}>
              Nv. {v}{slots[v] ? ` (${slots[v].total - slots[v].used} libres)` : ''}
            </option>))}
        </select>
      </div>
      {slot && (
        <p className="muted">
          Espacios de nivel {lvl}: {slot.total - slot.used} →{' '}
          {slot.total - slot.used - 1}</p>)}
      {(() => {
        const scale = sd.damage_at_slot_level ||
                      sd.higher_level_scaling || {}
        const dice = scale[lvl] || scale[String(lvl)] ||
                     sd.damage?.dice || sd.damage_dice
        const scaled = lvl > base &&
          Object.keys(scale).length > 0
        return dice ? (
          <p className="muted">
            Daño{scaled ? ` a nivel ${lvl} (escalado)` : ''}: {dice}
          </p>) : null
      })()}
      {conc && concentrating && (
        <p className="notice" role="note">
          ⚠ Estás concentrado en <b>{concentrating}</b> — lanzar
          {' '}{sp.name} la finalizará.</p>)}
      <div className="row">
        <button className="primary"
                disabled={lvl > 0 && !(slot && slot.used < slot.total)}
                onClick={() => onCast(lvl ?? base)}>Lanzar conjuro</button>
        <button className="ghost" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  )
}

/** Panel de ataque: muestra mods antes de tirar y permite marcar
    ventaja/desventaja y CA del objetivo — nada de tiradas ciegas. */
function AttackPanel({ charId, item, onResult, onClose }) {
  const [mode, setMode] = useState('normal')
  const [ac, setAc] = useState('')
  const [last, setLast] = useState(null)
  const roll = async () => {
    const r = await api.characterAttack(
      charId, item.name, mode, ac ? +ac : null)
    setLast(r)
    const miss = r.hit.hits === false ? ' — fallo'
               : r.hit.hits === true ? ' — ¡impacta!' : ''
    onResult(`${item.name}: impacto ${r.hit.total}${miss}` +
             ` · daño ${r.damage.expression} = ${r.damage.total}` +
             (r.notes?.length ? ` [${r.notes.join(', ')}]` : ''))
  }
  return (
    <div className="card" role="dialog" aria-label={`Atacar con ${item.name}`}
         style={{ background: 'var(--card-raised)' }}>
      <strong>{item.name}</strong>
      <div className="row" role="radiogroup" aria-label="Modo de ataque">
        {[['normal', 'Normal'], ['adv', 'Ventaja'],
          ['dis', 'Desventaja']].map(([v, l]) => (
          <label key={v}>
            <input type="radio" name="atk-mode" checked={mode === v}
                   onChange={() => setMode(v)} /> {l}</label>))}
      </div>
      <div className="row">
        <input type="number" placeholder="CA objetivo (opcional)"
               aria-label="CA del objetivo" style={{ maxWidth: 150 }}
               value={ac} onChange={(e) => setAc(e.target.value)} />
        <button className="primary" onClick={roll}>Tirar ataque</button>
        <button className="ghost" onClick={onClose}>Cerrar</button>
      </div>
      {last && (
        <p className="muted" role="status">
          Impacto: {last.hit.rolls.join(' + ')} = <b>{last.hit.total}</b>
          {last.hit.target_ac != null &&
            ` vs CA ${last.hit.target_ac} → ${last.hit.hits ? 'impacta' : 'falla'}`}
          <br />Daño: {last.damage.expression} = <b>{last.damage.total}</b>
          {last.notes?.length > 0 && <><br />{last.notes.join(' · ')}</>}
        </p>)}
    </div>
  )
}

function CondChip({ name, onRemove }) {
  const [open, setOpen] = useState(false)
  const rule = COND_RULES[name.toLowerCase()]
  return (
    <span>
      <span className="chip" role="button" tabIndex={0}
            title="Ver efecto mecánico"
            onClick={() => setOpen(!open)}
            onKeyDown={(e) => e.key === 'Enter' && setOpen(!open)}>
        {name}
        <button aria-label={`Quitar condición ${name}`}
                onClick={(e) => { e.stopPropagation(); onRemove() }}>×</button>
      </span>
      {open && (
        <p className="muted" style={{ margin: '.2rem 0 .4rem' }}>
          {rule || 'Sin efecto mecánico registrado — condición narrativa.'}
        </p>)}
    </span>
  )
}

function SpellList({ ids, onCast, onForget }) {
  const [names, setNames] = useState({})
  const [meta, setMeta] = useState({})
  const [menu, setMenu] = useState(null)
  const navigate = useNavigate()
  useEffect(() => {
    for (const sid of ids) {
      if (names[sid]) continue
      api.getEntity(sid)
        .then((e) => {
          const dd = e.data || {}
          const sub = [
            dd.level != null && `Nv. ${dd.level}`,
            dd.school && String(dd.school).replace(/_/g, ' '),
            dd.concentration && '⭑ conc.',
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
          <span style={{ flex: 1 }}>{names[sid] || sid}
            {meta[sid] && (
              <><br /><span className="muted"
                style={{ fontSize: '.8em' }}>{meta[sid]}</span></>)}
          </span>
          <button onClick={() => onCast(sid)}>Lanzar</button>
          <button className="ghost" aria-label={`Opciones de ${names[sid] || sid}`}
                  aria-expanded={menu === sid}
                  onClick={() => setMenu(menu === sid ? null : sid)}>
            ⋮</button>
          {menu === sid && (
            <span className="row" role="menu">
              <button className="ghost" onClick={() => {
                setMenu(null)
                navigate(`/content/${encodeURIComponent(sid)}`)
              }}>Detalles</button>
              <button className="ghost" onClick={() => {
                setMenu(null); onForget(sid)
              }}>Olvidar</button>
            </span>)}
        </li>
      ))}
    </ul>
  )
}


function FeatList({ ids, onForget }) {
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
          <span style={{ flex: 1 }}>{names[fid] || fid}</span>
          <button className="ghost" onClick={() => onForget(fid)}>×</button>
        </li>))}
    </ul>
  )
}
