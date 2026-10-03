import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { currentUser } from '../session.js'
import { campaignSocket } from '../ws.js'
import VoiceChat from '../components/VoiceChat.jsx'
import { useT } from '../i18n.jsx'
import { onTabsKeyDown } from '../a11y.js'
import DmSesion from '../components/dm/DmSesion.jsx'
import DmCombate from '../components/dm/DmCombate.jsx'
import DmCampana from '../components/dm/DmCampana.jsx'
import DmMapa from '../components/dm/DmMapa.jsx'

export default function DmBoard() {
  const { t, tf } = useT()
  const [campaign, setCampaign] = useState(null)
  const [campName, setCampName] = useState('')
  const [combat, setCombat] = useState(null)   // {id, version, combat}
  const combatRef = useRef(null)              // para el handler WS
  combatRef.current = combat
  const [combatName, setCombatName] = useState('')
  const [query, setQuery] = useState('')
  const [monsters, setMonsters] = useState([])
  const [manual, setManual] = useState({ name: '', hp_max: 10, initiative: 10 })
  const [dmg, setDmg] = useState({})
  const [err, setErr] = useState(null)
  const [dmTab, setDmTab] = useState('sesion')
  const [playerView, setPlayerView] = useState(false)  // lo que ven los jugadores
  const [entities, setEntities] = useState([])
  const [ping, setPing] = useState(null)      // ping de mapa en vivo
  const [entForm, setEntForm] = useState({ kind: 'npc', name: '', notes: '', monsters: '' })
  const [partyLevels, setPartyLevels] = useState('3,3,3,3')
  const [crs, setCrs] = useState('')
  const [difficulty, setDifficulty] = useState(null)
  const [rollReq, setRollReq] = useState({ character_id: '', expression: '1d20', reason: '' })
  const [dmgType, setDmgType] = useState('')
  const [newCond, setNewCond] = useState('')
  const [condRounds, setCondRounds] = useState('')
  const [selId, setSelId] = useState(null)
  const [feedFilter, setFeedFilter] = useState('todas')
  const [sessions, setSessions] = useState([])
  const [sessTitle, setSessTitle] = useState('')
  const [timeline, setTimeline] = useState(null)
  const [rollFeed, setRollFeed] = useState([])
  const [eventFeed, setEventFeed] = useState(null)
  const [areaDmg, setAreaDmg] = useState(null)   // daño multiobjetivo
  const [areaAmt, setAreaAmt] = useState(10)
  const [areaType, setAreaType] = useState('')
  const [areaResults, setAreaResults] = useState(null)
  const feedRef = useRef(null)           // scroll del feed de tiradas
  const [newRolls, setNewRolls] = useState(0)
  const [presence, setPresence] = useState([]) // quién está en la sala
  const [partyChars, setPartyChars] = useState([]) // PJs de la campaña
  const [chat, setChat] = useState([])         // chat efímero de mesa
  const [chatText, setChatText] = useState('')
  const [typing, setTyping] = useState(null)   // {from, at} efímero
  const typingSent = useRef(0)
  const sockRef = useRef(null)                 // WS vivo para el chat
  const [rtcMsg, setRtcMsg] = useState(null)   // señal WebRTC entrante

  // feed en vivo: tiradas de los jugadores en la sala
  useEffect(() => {
    if (!campaign) return undefined
    const sock = campaignSocket(campaign.id, {
      onMessage: (msg) => {
        const ev = msg.event || msg   // el servidor emite el evento suelto
        if (ev?.type === 'chat') {
          setChat((f) => [...f.slice(-40), ev])
        }
        if (ev?.type === 'typing') {
          setTyping({ from: ev.from, at: Date.now() })
        }
        if (ev?.type === 'dice.roll.created') {
          setRollFeed((f) => [ev.payload, ...f].slice(0, 20))
          // si el DM está leyendo eventos antiguos no le movemos el
          // scroll — cuenta "N nuevos" hasta que vuelva arriba
          if ((feedRef.current?.scrollTop ?? 0) > 40)
            setNewRolls((n) => n + 1)
        }
        // entidades vivas: el PATCH del propio DM (tokens, niebla)
        // y los cambios de jugadores/espectadores redibujan el mapa —
        // sin esto la pestaña Mapa se quedaba con datos viejos
        if (ev?.type === 'campaign.entity.updated') {
          api.listEntities(campaign.id)
            .then((r) => setEntities(r.entities)).catch(() => {})
        }
        if (ev?.type === 'campaign.map.ping') {
          setPing({ ...ev.payload, k: Date.now() })
        }
        if (ev?.type === 'campaign.presence') {
          setPresence(ev.payload?.members || [])
        }
        // alta/baja/reasignación de fichas de la campaña — la lista de
        // PJs del DM se refresca sola (claims, fichas borradas)
        if (ev?.type === 'character.updated') {
          api.listCharacters(campaign.id)
            .then((r) => setPartyChars(r.characters || []))
            .catch(() => {})
        }
        if (ev?.type === 'rtc.signal') {
          setRtcMsg({ ...ev, k: Date.now() })
        }
        // eventos del combate abierto (hp/saves/turno desde OTRO
        // dispositivo — la salvación del jugador, otro DM): los tipos
        // son character.hp.changed etc., no combat.* — sin esto el
        // tablero mostraba PG viejos hasta tocar algo
        // combate creado/borrado en OTRO dispositivo (o por escena):
        // abrir si no hay ninguno; limpiar si borraron el abierto
        if (ev?.type === 'combat.started' && !combatRef.current &&
            ev.payload?.combat_id) refresh(ev.payload.combat_id)
        if (ev?.type === 'combat.ended' && ev.payload?.deleted &&
            combatRef.current?.id === ev.aggregate_id)
          setCombat(null)
        if (combatRef.current) {
          const cb = combatRef.current
          // los eventos character.* de OPS DE FICHA llevan
          // aggregate_id = character_id (no el del combate): si ese PJ
          // es combatiente del combate abierto, también refresca
          const charIds = new Set(
            (cb.combat.combatants || [])
              .filter((x) => x.kind === 'character')
              .map((x) => x.ref_id))
          if (ev?.aggregate_id === cb.id ||
              (String(ev?.type || '').startsWith('character.') &&
               (charIds.has(ev.aggregate_id) ||
                charIds.has(ev.payload?.character_id)))) {
            refresh(cb.id)
          }
        }
      },
    })
    sockRef.current = sock
    return () => { sockRef.current = null; sock.close() }
  }, [campaign?.id])

  // al entrar en la campaña se cargan sesiones y entidades — antes
  // solo se repoblaban tras crear/editar y salían vacías
  useEffect(() => {
    if (!campaign) return
    api.listSessions(campaign.id)
      .then((r) => setSessions(r.sessions)).catch(() => {})
    api.listEntities(campaign.id)
      .then((r) => setEntities(r.entities)).catch(() => {})
    api.listCharacters(campaign.id)
      .then((r) => setPartyChars(r.characters || [])).catch(() => {})
    // restaurar el combate activo — recargar /dm a mitad de
    // encuentro dejaba el tracker vacío aunque el combate seguía vivo
    api.listCombats(campaign.id, 'active')
      .then((r) => {
        const open = r.combats?.[0]
        if (open && !combatRef.current) refresh(open.id)
      }).catch(() => {})
  }, [campaign?.id])

  // recargar /dm no debe tirar el tablero entero: restaura la última
  // campaña abierta y recuérdala para la próxima visita
  useEffect(() => {
    if (campaign) return
    // formato unificado {id,name,at} (CampaignBoard/Dashboard lo
    // escriben/leen así) — el id en crudo rompía la tarjeta de
    // "continuar" del Dashboard y viceversa
    const raw = localStorage.getItem('dnd-last-campaign')
    if (!raw) return
    let last = null
    try { last = JSON.parse(raw)?.id } catch { last = raw }
    if (!last) return
    api.getCampaign(last)
      .then(setCampaign)
      .catch(() => localStorage.removeItem('dnd-last-campaign'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (campaign?.id)
      localStorage.setItem('dnd-last-campaign', JSON.stringify(
        { id: campaign.id, name: campaign.name, at: Date.now() }))
  }, [campaign?.id])

  // el "está escribiendo" caduca solo a los 3s
  useEffect(() => {
    if (!typing) return undefined
    const tm = setTimeout(() => setTyping(null), 3000)
    return () => clearTimeout(tm)
  }, [typing])

  const onDmTyping = () => {
    if (Date.now() - typingSent.current < 1500) return
    if (sockRef.current?.socket?.readyState !== 1) return
    typingSent.current = Date.now()
    sockRef.current.socket.send(JSON.stringify(
      { type: 'typing', from: 'DM' }))
  }

  const sendDmChat = (e) => {
    e?.preventDefault()
    const text = chatText.trim()
    if (!text || sockRef.current?.socket?.readyState !== 1) return
    sockRef.current.socket.send(JSON.stringify(
      { type: 'chat', from: 'DM', text }))
    setChatText('')
  }

  const refresh = (id, version) =>
    api.getCombat(id).then((r) => setCombat(r)).catch((e) => setErr(e.message))

  const cop = async (type, payload) => {
    try {
      const r = await api.applyOp(
        { id: combat.id, version: combat.version },
        type, payload, 'combat')
      refresh(combat.id)
      return r
    } catch (e) { setErr(e.message); refresh(combat.id); return null }
  }

  const searchMonsters = async (e) => {
    e.preventDefault()
    try {
      const r = await api.search(query, 'monster')
      setMonsters(r.results)
    } catch (ex) { setErr(ex.message) }
  }

  // mismo orden que Combat.ordered() del motor: los fuera de combate
  // (muerto/inconsciente/estable o monstruo a 0 PG) no toman turno —
  // sin el filtro el índice del turno desapuntaba en cuanto alguien caía
  const OUT = new Set(['muerto', 'inconsciente', 'estable',
                       'dead', 'unconscious', 'stable'])
  const ordered = combat
    ? [...combat.combat.combatants]
        .filter((cb) => !(cb.conditions || []).some((x) => OUT.has(x))
                && !(cb.hp_current <= 0 && cb.kind !== 'character'))
        .sort((a, b) => b.initiative - a.initiative)
    : []
  const activeIdx = combat ? combat.combat.turn_index % Math.max(1, ordered.length) : 0
  const sel = ordered.find((c) => c.id === selId)
    || ordered[activeIdx] || null   // por defecto: el del turno

  const ctx = {
    t, tf, dmTab, setDmTab, playerView,
    campaign, setCampaign, campName, setCampName,
    eventFeed, setEventFeed, rollFeed, feedFilter, setFeedFilter,
    newRolls, setNewRolls, feedRef,
    sessTitle, setSessTitle, sessions, setSessions,
    timeline, setTimeline, rollReq, setRollReq,
    entities, setEntities, entForm, setEntForm, ping,
    partyChars,
    chat, chatText, setChatText, sendDmChat, typing, onDmTyping,
    combat, combatName, setCombatName, refresh, cop, setCombat,
    ordered, activeIdx, sel, setSelId,
    difficulty, setDifficulty, partyLevels, setPartyLevels,
    crs, setCrs, query, setQuery, monsters, manual, setManual,
    searchMonsters, dmg, setDmg, dmgType, setDmgType,
    newCond, setNewCond, condRounds, setCondRounds,
    areaDmg, setAreaDmg, areaAmt, setAreaAmt,
    areaType, setAreaType, areaResults, setAreaResults,
  }

  return (
    <main className="dm">
      <datalist id="dm-conds">
        {['blinded', 'charmed', 'deafened', 'frightened', 'grappled',
          'incapacitated', 'invisible', 'paralyzed', 'petrified',
          'poisoned', 'prone', 'restrained', 'stunned', 'unconscious',
          'muerto', 'concentrando'].map((x) =>
          <option key={x} value={x} />)}
      </datalist>
      <h1>{t('nav.dm')}</h1>
      <div className="dm-shell">
      <aside className="dm-side">
        <nav role="tablist" aria-label={t('nav.dm')}
             onKeyDown={onTabsKeyDown}>
          {[['sesion', t('dm.session')], ['combate', t('dm.combat')],
            ['mapa', t('dm.map')], ['campana', t('dm.campaign')]]
            .map(([k, label]) => (
            <button key={k} role="tab" aria-selected={dmTab === k}
                    onClick={() => setDmTab(k)}>{label}</button>))}
        </nav>
        <button className="ghost" aria-pressed={playerView}
                title={t('dm.playerViewHint')}
                onClick={() => setPlayerView(!playerView)}>
          {playerView ? t('dm.playerViewOn') : t('dm.playerView')}
        </button>
        {campaign && (
          <p className="muted" style={{ fontSize: '.8rem' }}>
            {campaign.name}
            {combat && <> · {t('com.round')} {combat.combat.round}</>}
            {rollFeed.length > 0 &&
              <> · {rollFeed.length} {t('dm.rollsCount')}</>}
          </p>)}
        {/* presencia estilo Discord: quién está en la sala ahora */}
        {(presence.length > 0 || currentUser()?.user_id) && (
          <p className="muted" style={{ fontSize: '.8rem',
                                       display: 'flex', gap: 4,
                                       alignItems: 'center' }}>
            🟢 {t('camp.online')}: {presence.map((m) =>
              m.count ? `+${m.count} ${t('camp.guests')}` : m.name
            ).join(' · ')}
            <VoiceChat sock={sockRef}
                       me={currentUser()?.user_id}
                       presence={presence} rtcMsg={rtcMsg} />
          </p>)}
      </aside>
      <div className="dm-main">
      {err && <p className="error" role="alert">{err}</p>}

      <DmSesion c={ctx} />
      <DmCampana c={ctx} />
      <DmCombate c={ctx} />
      <DmMapa c={ctx} />
      </div>{/* dm-main */}
      </div>{/* dm-shell */}
    </main>
  )
}
