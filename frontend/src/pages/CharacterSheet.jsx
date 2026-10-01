import { useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams }
  from 'react-router-dom'
import { api } from '../api.js'
import { useT } from '../i18n.jsx'
import { STATS, SKILL_ES, COND_RULES, SHEET_TABS }
  from '../components/sheet/data.js'
import SheetIdentity from '../components/sheet/SheetIdentity.jsx'
import SheetToolbar from '../components/sheet/SheetToolbar.jsx'
import SheetLevelUp from '../components/sheet/SheetLevelUp.jsx'
import SheetHead from '../components/sheet/SheetHead.jsx'
import TabResumen from '../components/sheet/TabResumen.jsx'
import TabAcciones from '../components/sheet/TabAcciones.jsx'
import TabStats from '../components/sheet/TabStats.jsx'
import TabMagia from '../components/sheet/TabMagia.jsx'
import TabInventario from '../components/sheet/TabInventario.jsx'
import TabRasgos from '../components/sheet/TabRasgos.jsx'
import TabHistoria from '../components/sheet/TabHistoria.jsx'
import TabActividad from '../components/sheet/TabActividad.jsx'
import { useEntityNames } from '../components/sheet/pickers.jsx'
import { CastPanel } from '../components/sheet/panels.jsx'
import { SheetTour, useCampaignSocket }
  from '../components/sheet/sheetParts.jsx'

export default function CharacterSheet() {
  const { id, tab: routeTab } = useParams()
  const { t, tf } = useT()
  const [char, setChar] = useState(null)
  const [portrait, setPortrait] = useState(() =>
    localStorage.getItem(`dnd-portrait-${id}`))
  const [tourStep, setTourStep] = useState(() =>
    localStorage.getItem('dnd-tour-done') === '1' ? null : 0)
  const [lvlPanel, setLvlPanel] = useState(false)
  const fileRef = useRef(null)
  const [amount, setAmount] = useState(1)
  const [charDmgType, setCharDmgType] = useState('')
  const [expr, setExpr] = useState('1d20')
  const [rollType, setRollType] = useState('check')
  const [rollLog, setRollLog] = useState([])
  const [err, setErr] = useState(null)
  const [history, setHistory] = useState(null)
  const [newItem, setNewItem] = useState('')
  const [newCond, setNewCond] = useState('')
  const [condRounds, setCondRounds] = useState('')
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
  const [pinnedNames, setPinnedNames] = useState({})
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

  const applyChar = (c) => {
    setChar(c)
    // peticiones del DM que llegaron estando offline — la sala solo
    // emite el evento una vez; pendingRolls las reaparece al volver
    if (c.campaign_id)
      api.pendingRolls(c.campaign_id, [id])
        .then((r) => {
          const p = (r.pending || [])[0]
          if (p) setRollRequest(p)
        }).catch(() => {})
    // retrato: prioriza el guardado en la ficha (sincronizable),
    // luego el local del navegador
    setPortrait(c.data?.narrative?.portrait_url ||
                localStorage.getItem(`dnd-portrait-${id}`))
  }
  const load = () => api.getCharacter(id).then((c) => {
    applyChar(c)
    // caché offline: la tabla char_cache existía pero nadie escribía
    // — sin ella, recargar la ficha sin conexión moría en el GET
    import('../db.js').then(({ db }) =>
      db.char_cache.put({ id, updated_at: Date.now(), char: c }))
      .catch(() => {})
  }).catch(async (e) => {
    // sin red → última versión cacheada; las ops que haga el jugador
    // encima ya van encoladas por applyOp
    const cached = await import('../db.js')
      .then(({ db }) => db.char_cache.get(id)).catch(() => null)
    if (cached?.char) applyChar(cached.char)
    else setErr(e.message)
  })
  useEffect(() => { load() }, [id])

  // "continuar" del dashboard: última ficha abierta en este dispositivo
  useEffect(() => {
    if (!char) return
    localStorage.setItem('dnd-last-char', JSON.stringify(
      { id: char.id, name: char.name, at: Date.now() }))
  }, [char?.id])

  // tablas normativas desde el rules pack (backend) — fallback local
  const [rulesTbl, setRulesTbl] = useState(null)
  useEffect(() => {
    api.rulesTables().then(setRulesTbl).catch(() => {})
  }, [])
  /* etiquetas por idioma: 'stat.str' / 'skill.perception'… con
     fallback al id para claves sin traducir (homebrew) */
  const tr = (key, fb) => {
    const v = t(key)
    return v === key ? fb : v
  }
  const skillName = (sid) => tr(`skill.${sid}`, SKILL_ES[sid] || sid)
  const statName = (ab) => tr(`stat.${ab}`, ab.toUpperCase())
  const stats = rulesTbl?.ability_skills
    ? STATS.map(([ab]) => [ab, statName(ab),
        (rulesTbl.ability_skills[
          { str: 'strength', dex: 'dexterity', con: 'constitution',
            int: 'intelligence', wis: 'wisdom',
            cha: 'charisma' }[ab]] || []).map((s) =>
          [s, skillName(s)])])
    : STATS.map(([ab,, skills]) =>
        [ab, statName(ab), (skills || []).map(([sid]) =>
          [sid, skillName(sid)])])
  // fusiona: la tabla del rules pack manda, pero los alias ES del
  // fallback local siguen funcionando para chips escritos a mano
  const condRules = { ...COND_RULES, ...(rulesTbl?.conditions || {}) }

  const [rollRequest, setRollRequest] = useState(null)
  const [xpAdd, setXpAdd] = useState(0)
  const [chat, setChat] = useState([])
  const [chatText, setChatText] = useState('')
  const [typing, setTyping] = useState(null)   // {from, at} efímero
  const typingSent = useRef(0)
  const [notify, setNotify] = useState(
    localStorage.getItem('dnd-notify') === '1')
  const toggleNotify = async () => {
    if (notify) {
      localStorage.setItem('dnd-notify', '0'); setNotify(false); return
    }
    if (!('Notification' in window)) return
    if ((await Notification.requestPermission()) !== 'granted') return
    localStorage.setItem('dnd-notify', '1'); setNotify(true)
  }
  const sendChat = async (e) => {
    e?.preventDefault()
    const text = chatText.trim()
    if (!text) return
    // estilo Avrae: /r 1d20+5 tira dados en abierto (llega al feed
    // de todos), /rs … es una tirada secreta solo visible para el DM
    const m = text.match(/^\/(r|roll|rs)\s+(.+)$/i)
    if (m) {
      try {
        await api.characterRoll(id, m[2].trim(), 'check',
                                false, m[1].toLowerCase() === 'rs')
        setChatText('')
        return
      } catch { /* expresión inválida → se envía como mensaje */ }
    }
    if (wsRef.current?.socket?.readyState !== 1) return
    wsRef.current.socket.send(JSON.stringify(
      { type: 'chat', from: char?.name || '?', text }))
    setChatText('')
  }


  // Sync en vivo: si el personaje está en una campaña, escucha eventos
  // de la sala y recarga cuando algo lo toca. Las peticiones de tirada
  // nombres de favoritos que no son objetos de inventario (conjuros)
  useEffect(() => {
    if (!char) return
    const dd = char.data
    for (const pid of dd.pinned || []) {
      if ((dd.inventory || []).some((x) => x.id === pid)) continue
      if (pinnedNames[pid]) continue
      api.getEntity(pid)
        .then((e) => setPinnedNames((n) => ({ ...n, [pid]: e.name })))
        .catch(() => setPinnedNames((n) =>
          ({ ...n, [pid]: pid.split(':').pop().replace(/-/g, ' ') })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [char?.data?.pinned])

  // sync en vivo: la sala de campaña alimenta chat, log de tiradas
  // y peticiones del DM (y dispara resync cuando algo toca la ficha)
  const wsRef = useCampaignSocket(char, id, notify, load,
                                  { setChat, setRollLog,
                                    setRollRequest, setTyping })

  // el "está escribiendo" caduca a los 3s — no hay 'stop typing'
  useEffect(() => {
    if (!typing) return undefined
    const tm = setTimeout(() => setTyping(null), 3000)
    return () => clearTimeout(tm)
  }, [typing])

  // throttle: un ping cada 1.5s como máximo, nada por tecla
  const onTyping = () => {
    if (Date.now() - typingSent.current < 1500) return
    if (wsRef.current?.socket?.readyState !== 1) return
    typingSent.current = Date.now()
    wsRef.current.socket.send(JSON.stringify(
      { type: 'typing', from: char?.name || '?' }))
  }

  const op = async (type, payload) => {
    setErr(null)
    try {
      const r = await api.applyOp(char, type, payload)
      if (r.queued) {
        // offline: encolada en IndexedDB — avisa para que el jugador
        // sepa que el cambio se enviará al volver la red
        setNotice(t('sheet.opQueued'))
        return r
      }
      if (r.operation_id) {
        setUndoable({ id: r.operation_id, label: type })
        setTimeout(() => setUndoable((u) =>
          u?.id === r.operation_id ? null : u), 8000)
      }
      // daño manteniendo concentración → avisa de la tirada de CON
      const cc = (r.events || []).find((e) => e.payload?.concentration_check)
      if (cc) {
        setNotice(tf('sheet.concCheck',
                     { spell: cc.payload.spell, dc: cc.payload.concentration_dc }))
      }
      // transparencia mecánica: resistencia/vuln/inmunidad aplicada
      const fx = (r.events || [])
        .flatMap((e) => e.payload?.damage_effects || [])
      if (fx.length) {
        setRollLog((l) => [
          `${t('sheet.dmgApplied')}: ${fx.join(' · ')}`, ...l]
          .slice(0, 10))
      }
      load()
      return r
    } catch (e) {
      setErr(e.message)
      load() // resync on conflict
      return null
    }
  }

  const doRoll = async (e) => {
    e.preventDefault()
    // tirada a través del motor de efectos: aplica ventaja/desventaja y
    // mods declarativos activos sobre el personaje
    // inspiración: se gasta en la PRÓXIMA tirada de d20 (SRD) —
    // antes doRoll nunca la usaba ni la consumía
    const useInsp = !!d.inspiration && rollType !== 'damage'
    try {
      const r = await api.characterRoll(id, expr, rollType, useInsp)
      const fx = (r.effects_applied || []).length
        ? ` [${r.effects_applied.join(', ')}]` : ''
      setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total}${fx}`, ...l].slice(0, 10))
      if (useInsp)
        await op('character.inspiration.set', { value: false })
    } catch (e) { setErr(e.message) }
  }

  // hook incondicional — jamás después de un return (React exige
  // el mismo número de hooks en cada render)
  const d0 = char?.data || {}
  const idNames = useEntityNames([
    ...(d0.classes || []).flatMap((cl) => [cl.class_id, cl.subclass_id]),
    d0.species_id, d0.background_id].filter(Boolean))

  if (err && !char) return <main><p className="error">{err}</p></main>
  if (!char) return <main><p>{t('common.loading')}</p></main>

  const d = char.data
  const hp = d.hp || { current: 0, max: 0, temp: 0 }
  const slots = d.spell_slots || {}

  const rollInit = async (mode = '') => {
    // check:dex → el backend suma el mod DES y aplica condiciones
    // (agotamiento da desventaja en pruebas); el resto del bono de
    // iniciativa derivado (efectos) va como mod fijo
    const dexMod = Math.floor(((d.abilities?.dexterity ?? 10) - 10) / 2)
    const extra = (derived?.initiative ?? dexMod) - dexMod
    try {
      const r = await api.characterRoll(
        id, `1d20${mode}${extra ? `${extra >= 0 ? '+' : ''}${extra}` : ''}`,
        'check:dex')
      setRollLog((l) => [
      `${t('sheet.initiative')}${mode === 'adv' ? ` ${t('sheet.advTag')}`
                : mode === 'dis' ? ` ${t('sheet.disTag')}` : ''}: ${
        (r.kept || []).join('+')} = ${r.total}${
        (r.effects_applied || []).length
          ? ` [${r.effects_applied.join(', ')}]` : ''}`, ...l]
      .slice(0, 10))
    } catch (e) { setErr(e.message) }
  }

  // contexto compartido con las pestañas extraídas (components/sheet/)
  const ctx = {
    id, char, d, hp, slots, derived, stats, condRules, condOptions,
    shops, setShops, t, tf, focus, hud, tab, op, load, setNotice,
    rollLog, setRollLog, doRoll,
    amount, setAmount, xpAdd, setXpAdd,
    charDmgType, setCharDmgType, coin, setCoin,
    pinnedNames, journalEntry, setJournalEntry,
    newCond, setNewCond, condRounds, setCondRounds,
    actions, setActions, expr, setExpr, rollType, setRollType,
    invTab, setInvTab, newItem, setNewItem,
    atkItem, setAtkItem, castId, setCastId,
    history, setHistory,
    chat, chatText, setChatText, sendChat, typing, onTyping,
  }

  // "quién es" de un vistazo: avatar + clases/subclases/especie/trasfondo
  const entName = (eid) => eid
    ? (idNames[eid] || eid.split(':').pop().replaceAll('-', ' ')) : null
  const classLine = (d.classes || [])
    .map((cl) => entName(cl.class_id) +
      (cl.subclass_id ? ` (${entName(cl.subclass_id)})` : '') +
      ` ${cl.level}`).join(' · ')
  const speciesName = entName(d.species_id)
  const bgName = entName(d.background_id)
  const totalLevel = d.classes?.reduce((s, cl) => s + cl.level, 0) || 1

  // retrato propio: se guarda como dataURL reducida en localStorage
  const onPortrait = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    const img = new Image()
    img.onload = () => {
      const s = Math.min(1, 128 / Math.max(img.width, img.height))
      const cnv = document.createElement('canvas')
      cnv.width = Math.round(img.width * s)
      cnv.height = Math.round(img.height * s)
      cnv.getContext('2d').drawImage(img, 0, 0, cnv.width, cnv.height)
      const url = cnv.toDataURL('image/jpeg', 0.85)
      localStorage.setItem(`dnd-portrait-${id}`, url)
      setPortrait(url)
      URL.revokeObjectURL(img.src)
      // persiste en la ficha (narrative.portrait_url) para sincronizar
      op('character.narrative.set',
         { field: 'portrait_url', value: url })
    }
    img.src = URL.createObjectURL(f)
  }

  return (
    <main className={`wide${focus ? ' concentration' : ''}`}>
      <SheetIdentity char={char} d={d} portrait={portrait}
                     classLine={classLine} speciesName={speciesName}
                     bgName={bgName} totalLevel={totalLevel}
                     fileRef={fileRef} onPortrait={onPortrait}
                     setPortrait={setPortrait} t={t} op={op} />
      {/* recorrido de primera visita — una vez, salta con Saltar */}
      <SheetTour step={tourStep} onStep={setTourStep} />
      <SheetToolbar char={char} focus={focus} hudSize={hud.size}
                    setHud={setHud} setFocus={setFocus}
                    lvlPanel={lvlPanel} setLvlPanel={setLvlPanel}
                    history={history} setHistory={setHistory}
                    notify={notify} toggleNotify={toggleNotify}
                    setErr={setErr} load={load} t={t} />
      {/* subida de nivel: clase existente o multiclase nueva */}
      {lvlPanel && (
        <SheetLevelUp classes={d.classes} entName={entName}
                      op={op} setLvlPanel={setLvlPanel}
                      t={t} tf={tf} />)}
      {err && (
        <p className="error" role="alert">
          {err}
          <button className="ghost" style={{ minHeight: 24 }}
                  onClick={() => setErr(null)}>×</button>
        </p>)}
      {notice && (
        <p className="notice" role="alert">
          {notice} <button onClick={() => setNotice(null)}>OK</button>
        </p>
      )}
      {undoable && (
        <p className="notice" role="status">
          {t('sheet.opApplied')}
          <button onClick={async () => {
            try {
              await api.undoOp(undoable.id)
              setUndoable(null); load()
            } catch (e) { setErr(e.message) }
          }}>{t('sheet.undoBtn')}</button>
          <button className="ghost"
                  onClick={() => setUndoable(null)}>×</button>
        </p>)}

      {rollRequest && (
        <section className="card" role="alert">
          <h2>{t('sheet.rollreq')}</h2>
          <p><strong>{rollRequest.expression}</strong>
            {rollRequest.reason && ` — ${rollRequest.reason}`}
            {rollRequest.secret &&
              <span className="muted"> ({t('sheet.secret')})</span>}
          </p>
          <button onClick={async () => {
            try {
              const r = await api.characterRoll(id, rollRequest.expression, 'check')
              setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total}`, ...l].slice(0, 10))
              setRollRequest(null)
            } catch (e) { setErr(e.message) }
          }}>{t('sheet.roll')} {rollRequest.expression}</button>
          <button className="ghost" title={t('sheet.secretHint')}
                  onClick={async () => {
            try {
              const r = await api.characterRoll(
                id, rollRequest.expression, 'check', false, true)
              setRollLog((l) => [
                `🔒 ${r.expression} → ${r.total} ${t('sheet.secretTag')}`,
                ...l].slice(0, 10))
              setRollRequest(null)
            } catch (e) { setErr(e.message) }
          }}>{t('sheet.secretBtn')}</button>
          <button className="ghost"
                  onClick={() => setRollRequest(null)}>
            {t('sheet.discard')}</button>
        </section>
      )}

      {/* vitales siempre a mano: cabecera pegajosa sobre las pestañas */}
      <SheetHead hp={hp} derived={derived} d={d}
                   rollInit={rollInit} op={op} focus={focus}
                   hud={hud} setHud={setHud} tab={tab}
                   setTab={setTab} t={t} tf={tf} tr={tr} />

      <TabResumen c={ctx} />
      <TabActividad c={ctx} />
      <TabStats c={ctx} />
      <TabMagia c={ctx} />
      <TabInventario c={ctx} />
      <TabAcciones c={ctx} />
      <TabRasgos c={ctx} />
      <TabHistoria c={ctx} />
      {/* panel de lanzamiento global — funciona desde cualquier
          pestaña (Magia, Acciones, favoritos del Resumen) */}
      {castId && (
        <CastPanel spellId={castId} slots={slots}
                   pactSlots={d.pact_slots || {}}
                   concentrating={d.concentrating_on}
                   preparedIds={d.spells_prepared}
                   onCast={async (lvl, pool) => {
                     setCastId(null)
                     await op('character.spell.cast',
                              { spell_id: castId, level: lvl, pool })
                   }}
                   onClose={() => setCastId(null)} />)}
    </main>
  )
}
