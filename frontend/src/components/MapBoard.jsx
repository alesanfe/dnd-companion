import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { blockedByWall, cellDist, inCone, CELL, MARK_COLORS,
         MAP_DEFAULTS } from '../mapMath.js'
import { useT } from '../i18n.jsx'
import WikiText from './WikiText.jsx'
import { MapToken, MapPin, InitiativeRibbon } from './MapPieces.jsx'

const DEFAULTS = MAP_DEFAULTS

/**
 * @typedef {Object} MapTokenData
 * @property {string} id
 * @property {string} name
 * @property {number} x @property {number} y      posición (esquina sup-izq)
 * @property {string} [color]
 * @property {number} [size]                      casillas de lado (2 = grande)
 * @property {string} [ref_id]                    ficha vinculada
 * @property {string} [combatant_id]              combatiente del tracker
 * @property {string} [player_id]                 dueño (vista de jugador)
 * @property {number} [hp] [max_hp]
 * @property {number} [light_ft] [vision_ft]      luz emitida / radio de visión
 * @property {string} [image_url]                 retrato (vacío = iniciales)
 *
 * @typedef {Object} MapData
 * @property {number} cols @property {number} rows
 * @property {number} cell_ft                     pies por casilla (5 estándar)
 * @property {MapTokenData[]} tokens
 * @property {string[]} fog                       claves "x,y" ocultas
 * @property {Object<string,string>} marks        "x,y" → color de zona
 * @property {Object[]} pins                      {id,x,y,entity_id}
 * @property {string[]} walls                     bordes "x,y,E|S"
 * @property {string} [image_url] [music_url]
 *
 * @typedef {Object} CombatantData
 * @property {string} id @property {string} name
 * @property {'character'|'monster'|string} kind
 * @property {string} [ref_id]                    ficha si kind=character
 * @property {number} initiative
 * @property {number} [hp_current] [hp_max] [hp_temp]
 * @property {number} [ac]                        oculto en vista de jugador
 * @property {string[]} [conditions]
 * @property {Object} [stat_block]                oculto en vista de jugador
 */



/** Grid táctico estilo Owlbear: varios mapas/escenas por campaña,
    tokens movibles (auto-numeración, PG, renombrar), niebla de
    guerra, zonas pintadas y regla de distancia. Persiste en
    entidades 'map' de la campaña; con readOnly los tokens bajo
    niebla se ocultan (vista de jugador). */
export default function MapBoard({ campaign, size = CELL,
                                  readOnly = false, viewer = 'dm',
                                  entities = null,
                                  worldEntities = [],
                                  chars = [], myUid = null,
                                  ping = null,
                                  activeRef = null,
                                  activeName = null,
                                  turnOrder = {},
                                  combatants = [],
                                  combat = null }) {
  // entities externas → la lista la gestiona el padre (vista de
  // jugador: mantiene la escena elegida al refrescar por WS).
  // El padre pasa TODAS las entidades (npc, quest, scene…) — sin el
  // filtro el picker las listaba y elegir una no-mapa mostraba un
  // grid vacío de DEFAULTS
  const [ownMaps, setMaps] = useState(null)
  const maps = (entities ?? ownMaps)
    ?.filter((e) => e.kind === 'map' || e.kind == null) ?? null
  const [curId, setCurId] = useState(null)
  const [mode, setMode] = useState('move')  // move|fog|mark
  const [markColor, setMarkColor] = useState(MARK_COLORS[0])
  const [sel, setSel] = useState(null)      // token seleccionado
  const [selPin, setSelPin] = useState(null) // pin seleccionado
  const [pinEnt, setPinEnt] = useState('')   // entidad a enlazar (modo pin)
  const [measure, setMeasure] = useState(null) // {a:[x,y], b:[x,y]}
  const [drag, setDrag] = useState(null)    // pintar área {a,b,kind}
  const [dragTok, setDragTok] = useState(null) // arrastrar token {id,x,y}
  /* presupuesto de movimiento por turno (orientativo, no bloquea):
     acumula pies recorridos por token; se resetea cuando cambia el
     combatiente activo — la velocidad sale de la ficha/stat block */
  const [movedFt, setMovedFt] = useState({})
  const moveTurnRef = useRef(null)
  const turnKey = `${combat?.id ?? ''}:${activeName ?? ''}:${activeRef ?? ''}`
  useEffect(() => {
    if (moveTurnRef.current !== turnKey) {
      moveTurnRef.current = turnKey
      setMovedFt({})
    }
  }, [turnKey])
  const _tokSpeed = (tk) => {
    const lc = linkedChar(tk)
    if (lc?.speed) return lc.speed
    const sb = (_combatantOf(tk)?.stat_block || {}).speed
    if (typeof sb === 'number') return sb
    const w = sb?.walk ?? sb?.land
    if (w) return +String(w).replace(/[^\d.]/g, '') || 0
    return 0                      // desconocida → sin aviso
  }
  const [tokMoved, setTokMoved] = useState(false)
  const [tokDmg, setTokDmg] = useState(0)   // daño rápido al token
  const [zoneDmg, setZoneDmg] = useState(0) // daño a la zona marcada
  const [zoneDc, setZoneDc] = useState(0)   // CD de salvación (0=sin tirada)
  const [zoneSave, setZoneSave] = useState('dex')
  const [zoneDtype, setZoneDtype] = useState('') // tipo p/ res/imm
  const [zoneLog, setZoneLog] = useState(null)
  const [atkFrom, setAtkFrom] = useState(null)   // token atacante
  const [atkOpts, setAtkOpts] = useState([])     // armas/acciones
  const [atkIdx, setAtkIdx] = useState(0)
  const [suppress, setSuppress] = useState(false)
  const [speeds, setSpeeds] = useState(() => {
    try { return JSON.parse(localStorage.getItem('map.speeds')) ||
           { walk: 30, fly: 0, swim: 0, climb: 0 } }
    catch { return { walk: 30, fly: 0, swim: 0, climb: 0 } }
  })
  const { t, tf } = useT()
  /* versión del combate que sigue a cada op aplicada — la prop
     llega por props/WS y queda stale entre dos ops seguidas (409) */
  const combatVerRef = useRef(null)
  const cver = () => combatVerRef.current ?? combat?.version
  useEffect(() => { combatVerRef.current = null }, [combat?.id])

  const map = (maps || []).find((m) => m.id === curId) || null
  const d = map ? { ...DEFAULTS, ...(map.data || {}) } : DEFAULTS
  // endurecer contra datos antiguos con null explícito
  d.tokens = d.tokens || []
  d.fog = d.fog || []
  d.marks = d.marks || {}
  d.pins = d.pins || []

  useEffect(() => { if (!entities) load() }, [campaign?.id, entities])

  const load = async () => {
    let r = await api.listEntities(campaign.id, 'map', viewer)
    if (!r.entities.length && !readOnly) {
      await api.createEntity(campaign.id, {
        kind: 'map', name: 'Mapa', visibility: 'public',
        data: { ...DEFAULTS },
      })
      r = await api.listEntities(campaign.id, 'map', viewer)
    }
    setMaps(r.entities)
    setCurId((prev) => r.entities.find((e) => e.id === prev)
      ? prev : (r.entities[0]?.id ?? null))
  }

  // al cambiar de escena el token seleccionado deja de existir
  useEffect(() => {
    setSel(null); setMeasure(null); setSelPin(null); setAtkFrom(null)
  }, [curId])

  // escena por defecto: la primera disponible; conserva la elegida
  // mientras siga existiendo (también con entities externas)
  useEffect(() => {
    if (!maps?.length) return
    setCurId((prev) => maps.find((e) => e.id === prev)
      ? prev : maps[0].id)
  }, [maps])

  const save = async (data) => {
    /* optimistic lock: la escritura lleva la versión que leímos — un
       409 significa que otro cliente (jugador moviendo su token,
       otro DM) ganó la carrera; recargar en vez de pisar su cambio */
    try {
      await api.patchEntity(campaign.id, map.id,
        { data, expected_version: map?.version })
      // con `entities` prop ownMaps es null — antes ms.map sobre
      // null era un TypeError en cualquier save() futuro
      setMaps((ms) => (ms ?? []).map((m) => m.id === map.id
        ? { ...m, data, version: (m.version || 0) + 1 } : m))
    } catch (e) {
      setZoneLog(`⚠ ${e.message}`)
      load()                    // re-sincronizar la escena
      throw e
    }
  }

  const resize = (dim, delta) =>
    save({ ...d, [dim]: Math.max(4, d[dim] + delta) })

  const onCell = (x, y, e) => {
    if (mode === 'fog') {
      const k = `${x},${y}`
      save({ ...d, fog: d.fog.includes(k)
        ? d.fog.filter((f) => f !== k) : [...d.fog, k] })
    } else if (mode === 'wall') {
      /* borde más cercano al clic — clave canónica "x,y,E|S" (del
         borde derecho de la celda izquierda / inferior de la de arriba) */
      const r = e.currentTarget.getBoundingClientRect()
      const fx = (e.clientX - r.left) / size - x
      const fy = (e.clientY - r.top) / size - y
      const dist = { E: 1 - fx, S: 1 - fy, W: fx, N: fy }
      const side = Object.entries(dist)
        .sort((a2, b2) => a2[1] - b2[1])[0][0]
      const key = side === 'E' ? `${x},${y},E`
        : side === 'S' ? `${x},${y},S`
        : side === 'W' ? `${x - 1},${y},E`
        : `${x},${y - 1},S`
      const walls = (d.walls || []).includes(key)
        ? d.walls.filter((w2) => w2 !== key)
        : [...(d.walls || []), key]
      save({ ...d, walls })
    } else if (mode === 'mark' || mode === 'blast') {
      const k = `${x},${y}`
      const marks = { ...d.marks }
      if (marks[k] === markColor) delete marks[k]
      else marks[k] = markColor
      save({ ...d, marks })
    } else if (mode === 'pin' && pinEnt) {
      // pin ligado a una entidad del mundo (lugar, PNJ, misión…)
      save({ ...d, pins: [...d.pins,
        { id: `p${crypto.randomUUID()}`, x, y, entity_id: pinEnt }] })
    }
  }

  const addToken = () => {
    const name = prompt(t('map.tokenPrompt'))
    if (!name?.trim()) return
    // auto-numeración para nombres repetidos ("Goblin", "Goblin 2"…)
    const base = name.trim()
    const n = d.tokens.filter((tk) =>
      tk.name === base || tk.name.startsWith(`${base} `)).length
    const used = d.tokens.map((tk) => tk.color)
    const hue = [0, 40, 90, 140, 200, 260, 300, 330][used.length % 8]
    const token = {
      id: `t${crypto.randomUUID()}`,
      name: n ? `${base} ${n + 1}` : base, x: 0, y: 0,
      color: `hsl(${hue} 70% 50%)`,
    }
    save({ ...d, tokens: [...d.tokens, token] })
  }

  const patchTok = (patch, tok = sel) => {
    const tokens = d.tokens.map((tk) =>
      tk.id === tok.id ? { ...tk, ...patch } : tk)
    save({ ...d, tokens })
    if (tok.id === sel?.id) setSel((s) => ({ ...s, ...patch }))
  }

  // ficha vinculada al token: PG en vivo + el jugador mueve SU token
  const linkedChar = (tk) => tk.ref_id
    ? chars.find((c) => c.id === tk.ref_id) : null
  const tokOwner = (tk) => tk.player_id
    || linkedChar(tk)?.player_id
    // token vinculado a un NPC que el DM le delegó al jugador
    || (combatants.some((c) => c.id === tk.combatant_id
          && c.delegated_to === myUid) ? myUid : null)
  const canMoveTok = (tk) => !readOnly
    || (myUid != null && tokOwner(tk) === myUid)
  const moveTokRemote = (tk, x, y) => {
    if (!readOnly) { patchTok({ x, y }, tk); return }
    // el catch antes tragaba el rechazo en silencio: el token volvía
    // a su sitio al siguiente resync sin que el jugador supiera por qué
    api.moveToken(campaign.id, map.id, tk.id, x, y)
      .catch((e) => setZoneLog(`⚠ ${tk.name}: ${e.message}`))
  }

  const renameTok = () => {
    const name = prompt(t('map.renameTokPrompt'), sel.name)
    if (name?.trim()) patchTok({ name: name.trim() })
  }

  const setHp = () => {
    const mx = +prompt(t('map.tokenMaxHp'), sel.max_hp ?? 10)
    if (mx > 0) patchTok({ max_hp: mx, hp: mx })
  }

  const adjHp = (delta) => {
    if (sel.hp == null) return
    patchTok({ hp: Math.max(0, Math.min(sel.max_hp, sel.hp + delta)) })
  }

  /* daño de zona: cada token con alguna casilla pintada recibe el
     daño — vinculado a ficha va por op real (auditable); suelto baja
     sus PG de token. Cierra el bucle plantilla AoE → resolver daño. */
  const tokOnMark = (tk) => {
    const s = Math.max(1, +(tk.size || 1))
    for (let dy = 0; dy < s; dy++)
      for (let dx = 0; dx < s; dx++)
        if (d.marks[`${tk.x + dx},${tk.y + dy}`]) return true
    return false
  }
  /* salvación de zona: ficha vinculada → tirada por el motor
     (mods + ventaja/desventaja de condiciones); combatiente del
     tracker → combatant.save (stat block); token suelto → d20 seco */
  const _tokSave = async (tk, lc, cbt) => {
    if (lc) {
      const r = await api.characterRoll(
        lc.id, '1d20', `save:${zoneSave}`).catch(() => null)
      if (!r) return null
      return r.auto_fail ? -999 : r.total
    }
    if (cbt && combat) {
      const r = await api.applyOp(
        { id: combat.id, version: cver() }, 'combatant.save',
        { combatant_id: cbt.id, ability: zoneSave }, 'combat'
      ).catch(() => null)
      if (!r) return null
      combatVerRef.current = r.version   // la op bumpea la versión
      const ev = (r.events || []).find(
        (e) => e.type === 'dice.roll.created')
      if (!ev) return null
      return ev.payload.auto_fail ? -999 : ev.payload.total ?? null
    }
    const r = await api.roll('1d20').catch(() => null)
    return r?.total ?? null
  }

  const dmgZone = async () => {
    if (!zoneDmg) return
    const res = []
    let toks = d.tokens
    for (const tk of d.tokens) {
      if (!tokOnMark(tk)) continue
      const lc = linkedChar(tk)
      const cbt = tk.combatant_id
        ? combatants.find((cb) => cb.id === tk.combatant_id) : null
      let amount = zoneDmg
      let tag = ''
      if (zoneDc > 0) {
        const total = await _tokSave(tk, lc, cbt)
        if (total != null) {
          const passed = total >= zoneDc
          amount = passed ? Math.floor(zoneDmg / 2) : zoneDmg
          tag = ` ${zoneSave.toUpperCase()} ${total < 0 ? '✗auto' : total}` +
                ` ${passed ? '✓' : '✗'}`
        }
      }
      if (lc) {
        // op real sobre la ficha — idempotente y deshacible
        const r = await api.applyOp(lc, 'character.hp.damage',
                                    { amount }).catch(() => null)
        res.push(`${tk.name}:${tag} ${r ? amount : '✗'}`)
      } else if (cbt && combat) {
        // combatiente del tracker → op con res/imm del stat block
        const r = await api.applyOp(
          { id: combat.id, version: cver() }, 'combatant.damage',
          { combatant_id: cbt.id, amount,
            damage_type: zoneDtype || undefined }, 'combat'
        ).catch(() => null)
        if (r) combatVerRef.current = r.version
        res.push(`${tk.name}:${tag} ${r ? amount : '✗'}`)
      } else {
        const hp = Math.max(0, (tk.hp ?? 0) - amount)
        toks = toks.map((t2) => t2.id === tk.id ? { ...t2, hp } : t2)
        res.push(`${tk.name}:${tag} ${amount}`)
      }
    }
    if (toks !== d.tokens) save({ ...d, tokens: toks })
    setZoneLog(res.length ? res.join(' · ') : t('map.zoneEmpty'))
  }

  /* ── ataque token→token (bucle VTT completo) ────────────────────
     atacante: arma de la ficha vinculada o acción del stat block del
     combatiente; objetivo: CA real de la ficha/stat block; impacto →
     daño por op auditable sobre ficha o tracker, o PG del token. */
  const _cbOf = (tk) => tk.combatant_id
    ? combatants.find((cb) => cb.id === tk.combatant_id) : null

  /* alcance del arma/acción medido en el grid — distancia entre los
     bordes de los footprints (tokens grandes ocupan varias casillas) */
  const _tokDistFt = (a, b) => {
    const sa = Math.max(1, +(a.size || 1))
    const sb = Math.max(1, +(b.size || 1))
    const dCells = Math.hypot(b.x - a.x, b.y - a.y)
      - (sa - 1) / 2 - (sb - 1) / 2
    return Math.max(0, dCells * d.cell_ft)
  }

  /* alcance (ft): arma del inventario vía content DB (melee 5/10 por
     'reach', ranged normal/long) o texto del stat block ('reach 10
     ft.' / 'range 20/60 ft.'). null = no pudo determinarse → se
     permite el ataque sin chequeo. */
  const _optRange = async (opt) => {
    if (['grapple', 'shove', 'shove_push'].includes(opt.kind))
      return { normal: 5, long: 5 }          // cuerpo a cuerpo
    if (opt.kind === 'cbt') {
      const text = opt.text || ''
      const mR = text.match(/reach\s*(\d+)\s*ft/i)
      const mN = text.match(/range\s*(\d+)\s*\/\s*(\d+)\s*ft/i)
      if (mR) return { normal: +mR[1], long: +mR[1] }
      if (mN) return { normal: +mN[1], long: +mN[2] }
      return { normal: 5, long: 5 }          // cuerpo a cuerpo
    }
    if (opt.kind !== 'char' || !opt.source_id)
      return null
    const w = (await api.getEntity(opt.source_id)
      .catch(() => null))?.data
    if (!w) return null
    const props = (w.properties || []).map((p) =>
      String(p.index || p).toLowerCase())
    const rng = w.range || {}
    if (String(w.weapon_range || '').toLowerCase().includes('ranged')
        || rng.normal) {
      const n = rng.normal || 30
      return { normal: n, long: rng.long || n }
    }
    const reach = props.includes('reach') ? 10 : 5
    return { normal: reach, long: reach }
  }

  const startAttack = async (tk) => {
    const lc = linkedChar(tk)
    const cbt = _cbOf(tk)
    let opts = []
    if (lc) {
      // armas del inventario real — el endpoint valida el nombre
      const ch = await api.getCharacter(lc.id).catch(() => null)
      opts = ((ch?.data || ch || {}).inventory || [])
        .filter((i) => i.name)
        .map((i) => ({ label: i.name, kind: 'char', item: i.name,
                       source_id: i.source_id }))
    } else if (cbt) {
      opts = ((cbt.stat_block || {}).actions || [])
        .map((a, i2) => ({ label: a.name || `acción ${i2 + 1}`,
                           kind: 'cbt', action_index: i2,
                           text: a.text }))
    }
    /* unarmed strike (2024): empujón/agarrón — el servidor resuelve
       la CD (o la contestada 2014) según el ruleset del combate;
       cualquier combatiente puede intentarlo */
    if (combat && _combatantOf(tk)) {
      opts = [...opts,
              { label: t('map.optGrapple'), kind: 'grapple' },
              { label: t('map.optShove'),   kind: 'shove' },
              { label: t('map.optPush'),    kind: 'shove_push' }]
    }
    if (!opts.length) { setZoneLog(`⚠ ${tk.name}: ${t('map.atkNone')}`); return }
    setAtkFrom(tk); setAtkOpts(opts); setAtkIdx(0)
  }

  const _targetAc = async (tk) => {
    const tlc = linkedChar(tk)
    if (tlc) {
      const r = await api.derivedAll(tlc.id).catch(() => null)
      return r?.armor_class?.total ?? null
    }
    const tcbt = _cbOf(tk)
    if (tcbt) return tcbt.stat_block?.ac ?? null
    const v = +prompt(tf('map.atkAcPrompt', { name: tk.name }), 10)
    return Number.isFinite(v) && v > 0 ? v : null
  }

  const _combatantOf = (tk) => tk.combatant_id
    ? combatants.find((cb) => cb.id === tk.combatant_id)
    : combatants.find((cb) =>
        (tk.ref_id && cb.ref_id === tk.ref_id) || cb.name === tk.name)

  const resolveAtk = async (target) => {
    const atk = atkFrom
    setAtkFrom(null)
    if (!atk || target.id === atk.id) return
    const opt = atkOpts[atkIdx]
    /* alcance: fuera del máximo = imposible; un arma a distancia más
       allá de su alcance normal dispara con desventaja */
    const rng = await _optRange(opt)
    const distFt = rng ? _tokDistFt(atk, target) : 0
    if (rng && distFt > rng.long) {
      setZoneLog(tf('map.atkOutOfRange',
        { atk: atk.name, dist: distFt.toFixed(0),
          range: rng.long })); return
    }
    /* empujón/agarrón: una sola op auditable (el servidor decide
       save-vs-CD 2024 o contestada 2014); mismo camino para DM y
       jugador — combat.shove_grapple está en las excepciones */
    if (['grapple', 'shove', 'shove_push'].includes(opt.kind)) {
      if (!combat) return
      const atkCb = _combatantOf(atk)
      const tgtCb = _combatantOf(target)
      if (!atkCb || !tgtCb) {
        setZoneLog(t('map.atkNoTarget')); return }
      const r = await api.applyOp(
        { id: combat.id, version: cver() }, 'combat.shove_grapple',
        { attacker_combatant_id: atkCb.id,
          target_combatant_id: tgtCb.id,
          kind: opt.kind === 'grapple' ? 'grapple' : 'shove',
          ...(opt.kind === 'shove_push' ? { push: true } : {}) },
        'combat').catch((e) => {
        setZoneLog(`⚠ ${e.message}`); return null })
      if (!r) return
      combatVerRef.current = r.version
      const ev = (r.events || []).find(
        (e) => e.type === 'dice.roll.created') || {}
      const pl = ev.payload || {}
      setZoneLog(`${atk.name} → ${target.name}: ${opt.label} ` +
        (pl.hits
          ? (pl.push_ft
            ? `→ ${pl.push_ft}ft`
            : opt.kind === 'grapple' ? t('map.sgGrappled')
                                     : t('map.sgProne'))
          : t('map.sgResisted')) +
        (pl.dc ? ` (CD ${pl.dc})` : '') +
        (pl.save ? ` ${String(pl.save).toUpperCase()} ` +
                  `${pl.save_total}` : ''))
      return
    }
    const mode = rng && distFt > rng.normal ? 'dis' : 'normal'
    /* jugador: resolución server-side — combat.attack compara contra
       la CA real del objetivo en el backend (nunca llega la CA al
       cliente) y aplica el daño; idempotente y auditable */
    if (readOnly) {
      if (!combat) return
      const atkCb = _combatantOf(atk)
      const tgtCb = _combatantOf(target)
      if (!atkCb || !tgtCb) {
        setZoneLog(t('map.atkNoTarget')); return }
      const r = await api.applyOp(
        { id: combat.id, version: cver() }, 'combat.attack',
        { attacker_combatant_id: atkCb.id,
          target_combatant_id: tgtCb.id,
          item_name: opt.item, mode }, 'combat').catch((e) => {
        setZoneLog(`⚠ ${e.message}`); return null })
      if (!r) return
      combatVerRef.current = r.version
      const ev = (r.events || []).find(
        (e) => e.type === 'dice.roll.created') || {}
      setZoneLog(tf('map.atkResult', {
        atk: atk.name, tgt: target.name, opt: opt.label,
        hit: ev.payload?.total ?? '?', ac: '·',
        res: (ev.payload?.hits
          ? `−${ev.payload?.damage ?? '?'} PG`
          : t('map.atkMiss')) +
          (ev.payload?.mastery ? ` ⚒${ev.payload.mastery}` : '') +
          (ev.payload?.topple_save?.prone ? ' → prone' : '') +
          (ev.payload?.push_ft ? ` → ${ev.payload.push_ft}ft` : '')}))
      return
    }
    const ac = await _targetAc(target)
    let hitTotal = null, dmgTotal = null, hits = ac == null ? true : null
    if (opt.kind === 'char') {
      const r = await api.characterAttack(linkedChar(atk).id, opt.item,
                                        mode, ac).catch(() => null)
      if (!r) { setZoneLog(`⚠ ${atk.name}: ✗`); return }
      hitTotal = r.hit?.total
      dmgTotal = r.auto_fail ? 0 : r.damage?.total
      if (r.hit?.hits != null) hits = r.hit.hits
      if (r.auto_fail) hits = false
    } else {
      if (!combat) return
      const cbt = _cbOf(atk)
      const r = await api.applyOp(
        { id: combat.id, version: cver() }, 'combatant.action.roll',
        { combatant_id: cbt.id, action_index: opt.action_index,
          mode },
        'combat').catch(() => null)
      if (!r) { setZoneLog(`⚠ ${atk.name}: ✗`); return }
      combatVerRef.current = r.version
      const ev = (r.events || []).find(
        (e) => e.type === 'dice.roll.created') || {}
      hitTotal = ev.payload?.attack_total ?? null
      dmgTotal = ev.payload?.damage_total ?? null
      if (ac != null && hitTotal != null) hits = hitTotal >= ac
    }
    // impacto → daño por op auditable; fallo → solo el log
    let applied = null
    if (hits && dmgTotal != null) {
      const tlc = linkedChar(target)
      const tcbt = _cbOf(target)
      if (tlc) {
        applied = await api.applyOp(
          tlc, 'character.hp.damage', { amount: dmgTotal })
          .then(() => dmgTotal).catch(() => null)
      } else if (tcbt && combat) {
        applied = await api.applyOp(
          { id: combat.id, version: cver() }, 'combatant.damage',
          { combatant_id: tcbt.id, amount: dmgTotal }, 'combat')
          .then((r) => { combatVerRef.current = r.version
                         return dmgTotal }).catch(() => null)
      } else if (target.hp != null) {
        const hp = Math.max(0, target.hp - dmgTotal)
        save({ ...d, tokens: d.tokens.map((t2) =>
          t2.id === target.id ? { ...t2, hp } : t2) })
        applied = dmgTotal
      }
    }
    setZoneLog(tf('map.atkResult', {
      atk: atk.name, tgt: target.name, opt: opt.label,
      hit: hitTotal ?? '?', ac: ac ?? '?',
      res: hits ? `−${applied ?? dmgTotal} PG`
                : t('map.atkMiss') }))
  }

  const dropTok = () => {
    if (!confirm(tf('map.tokenDelConfirm', { name: sel.name }))) return
    save({ ...d, tokens: d.tokens.filter((tk) => tk.id !== sel.id) })
    setSel(null)
  }

  /* combate → mapa: un token por combatiente del tracker. El match es
     por ref_id (fichas), combatant_id (monstruos) o nombre — así un
     token colocado a mano no se duplica al sincronizar. Tamaño según
     el stat block (Large = 2×2, Huge = 3×3). */
  const _TOK_SIZE = { Tiny: 1, Small: 1, Medium: 1, Large: 2,
                      Huge: 3, Gargantuan: 4 }
  const _freeCell = (tokens, startX = 0, startY = 0) => {
    const used = new Set(tokens.map((tk) => `${tk.x},${tk.y}`))
    for (let y = startY; y < d.rows; y++)
      for (let x = startX; x < d.cols; x++)
        if (!used.has(`${x},${y}`)) return [x, y]
    return [d.cols - 1, d.rows - 1]       // mapa lleno: apilar abajo
  }
  const syncCombatants = () => {
    let tokens = [...d.tokens]
    for (const cb of combatants) {
      const hit = tokens.find((tk) =>
        (cb.ref_id && tk.ref_id === cb.ref_id) ||
        tk.combatant_id === cb.id ||
        tk.name === cb.name)
      if (hit) {
        // refrescar PG de token no vinculado (monstruos: la ficha no
        // existe y sus PG solo los lleva el combatiente)
        if (!hit.ref_id &&
            (hit.hp !== cb.hp_current || hit.max_hp !== cb.hp_max))
          tokens = tokens.map((tk) => tk.id === hit.id
            ? { ...tk, hp: cb.hp_current, max_hp: cb.hp_max } : tk)
        continue
      }
      const [x, y] = _freeCell(tokens)
      const lc = cb.ref_id
        ? chars.find((c2) => c2.id === cb.ref_id) : null
      const hue = (tokens.length * 47) % 360
      tokens = [...tokens, {
        id: `t${crypto.randomUUID()}`, name: cb.name,
        x, y, color: `hsl(${hue} 70% 50%)`,
        combatant_id: cb.id,
        ref_id: cb.ref_id || null,
        player_id: lc?.player_id || null,
        size: _TOK_SIZE[(cb.stat_block || {}).size] || 1,
        hp: cb.hp_current, max_hp: cb.hp_max,
      }]
    }
    save({ ...d, tokens })
  }

  const cellAt = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    // pantalla → mundo: el SVG lleva viewBox con zoom/pan
    const wx = view.x + (e.clientX - r.left) / r.width  * vw
    const wy = view.y + (e.clientY - r.top)  / r.height * vh
    return [Math.floor(wx / size), Math.floor(wy / size)]
  }

  /* zoom/pan — rueda acerca/aleja anclando el cursor, botón central
     o espacio arrastra la vista. Los botones ±/⛶ sirven en táctil. */
  const [view, setView] = useState({ x: 0, y: 0, z: 1 })
  const vw = d.cols * size / view.z, vh = d.rows * size / view.z
  const svgRef = useRef(null)
  const panRef = useRef(null)
  const zoomAt = (e, factor) => {
    const r = svgRef.current.getBoundingClientRect()
    const px = view.x + (e.clientX - r.left) / r.width  * vw
    const py = view.y + (e.clientY - r.top)  / r.height * vh
    const z = Math.min(4, Math.max(.35, view.z * factor))
    const nw = d.cols * size / z, nh = d.rows * size / z
    setView({ z,
      // el punto bajo el cursor no se mueve
      x: px - (e.clientX - r.left) / r.width  * nw,
      y: py - (e.clientY - r.top)  / r.height * nh })
  }
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    // listener nativo no-pasivo — React onWheel no puede
    // preventDefault (la página haría scroll)
    const onW = (e) => {
      e.preventDefault()
      zoomAt(e, e.deltaY < 0 ? 1.2 : 1 / 1.2)
    }
    el.addEventListener('wheel', onW, { passive: false })
    return () => el.removeEventListener('wheel', onW)
  })

  const onSvgClick = (e) => {
    if (tokMoved) { setTokMoved(false); return }
    if (suppress) { setSuppress(false); return }
    const [x, y] = cellAt(e)
    if (x < 0 || y < 0 || x >= d.cols || y >= d.rows) return
    // vista de jugador: solo mueve su propio token (click→destino)
    if (readOnly) {
      if (sel && canMoveTok(sel)) { moveTokRemote(sel, x, y); setSel(null) }
      return
    }
    if (mode === 'move' && sel) {
      patchTok({ x, y }); setSel(null); return
    }
    onCell(x, y, e)
  }

  /* pintar en área: arrastrar con la herramienta niebla/zona
     cubre (o limpia, si la celda ancla ya lo estaba) el
     rectángulo entero */
  const onSvgDown = (e) => {
    // botón central (rueda) → paneo de la vista
    if (e.button === 1) {
      const r = e.currentTarget.getBoundingClientRect()
      panRef.current = { cx: e.clientX, cy: e.clientY,
                         vx: view.x, vy: view.y, rw: r.width,
                         rh: r.height }
      e.preventDefault()
      return
    }
    if (readOnly || (mode !== 'fog' && mode !== 'mark' &&
                     mode !== 'blast' && mode !== 'cone' &&
                     mode !== 'line')) return
    const [x, y] = cellAt(e)
    if (x < 0 || y < 0 || x >= d.cols || y >= d.rows) return
    setDrag({ a: [x, y], b: [x, y], kind: mode })
  }

  // soltar fuera del SVG también pasa por aquí (onMouseLeave): sin
  // eso un drag de token quedaba fantasma — dragTok no commiteaba y
  // panRef seguía paneando al reentrar el puntero
  const onSvgUp = () => {
    panRef.current = null
    // soltar tras arrastrar un token → commit de la posición
    if (dragTok) {
      const tk = d.tokens.find((t2) => t2.id === dragTok.id)
      if (tk && (tk.x !== dragTok.x || tk.y !== dragTok.y)) {
        moveTokRemote(tk, dragTok.x, dragTok.y)
        setTokMoved(true)          // el click posterior no alterna selección
        // presupuesto de movimiento: acumula el tramo y avisa si el
        // token del turno se pasa de su velocidad
        const distFt = dragTok.ox != null
          ? cellDist(dragTok.ox, dragTok.oy,
                     dragTok.x, dragTok.y, d.cell_ft) : 0
        if (distFt > 0 && combat) {
          const isActive = (activeRef && tk.ref_id === activeRef) ||
                           (activeName && tk.name === activeName)
          if (isActive) {
            const total = (movedFt[tk.id] || 0) + distFt
            setMovedFt((m) => ({ ...m, [tk.id]: total }))
            const spd = _tokSpeed(tk)
            if (spd && total > spd)
              setZoneLog(tf('map.moveOverSpeed', {
                name: tk.name, ft: total.toFixed(0), speed: spd }))
          }
        }
      }
      setDragTok(null)
      return
    }
    if (!drag) return
    const [x1, y1] = drag.a, [x2, y2] = drag.b
    if (x1 !== x2 || y1 !== y2) {
      let keys
      if (drag.kind === 'blast') {
        // plantilla circular: el radio en casillas desde el ancla —
        // bola de fuego 20 ft = 4 casillas de 5 ft
        const rad = Math.hypot(x2 - x1, y2 - y1) + .5
        keys = []
        for (let y = Math.floor(y1 - rad); y <= Math.ceil(y1 + rad); y++)
          for (let x = Math.floor(x1 - rad); x <= Math.ceil(x1 + rad); x++)
            if (Math.hypot(x - x1, y - y1) <= rad)
              keys.push(`${x},${y}`)
      } else if (drag.kind === 'cone') {
        // cono 5e: ancho = largo en cada punto (53.13°) — inCone en
        // mapMath (unit-tested)
        const len = Math.hypot(x2 - x1, y2 - y1) + .5
        keys = [`${x1},${y1}`]              // el ápice siempre dentro
        const lo = Math.floor(-len), hi = Math.ceil(len)
        for (let yy = y1 + lo; yy <= y1 + hi; yy++)
          for (let xx = x1 + lo; xx <= x1 + hi; xx++)
            if (inCone(x1, y1, x2, y2, xx, yy)) keys.push(`${xx},${yy}`)
      } else if (drag.kind === 'line') {
        // línea 5e (relámpago, aliento lineal): supercover — toda celda
        // que atraviesa el segmento ancla→borde
        keys = []
        const steps = Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1), 1)
        for (let s = 0; s <= steps; s++) {
          const tx = x1 + (x2 - x1) * s / steps
          const ty = y1 + (y2 - y1) * s / steps
          const kx = Math.round(tx), ky = Math.round(ty)
          if (!keys.includes(`${kx},${ky}`)) keys.push(`${kx},${ky}`)
        }
      } else {
        const [xa, xb] = [Math.min(x1, x2), Math.max(x1, x2)]
        const [ya, yb] = [Math.min(y1, y2), Math.max(y1, y2)]
        keys = []
        for (let y = ya; y <= yb; y++)
          for (let x = xa; x <= xb; x++) keys.push(`${x},${y}`)
      }
      if (drag.kind === 'fog') {
        const clearing = d.fog.includes(`${x1},${y1}`)
        const fog = clearing
          ? d.fog.filter((k) => !keys.includes(k))
          : [...new Set([...d.fog, ...keys])]
        save({ ...d, fog })
      } else {
        const clearing = d.marks[`${x1},${y1}`] === markColor
        const marks = { ...d.marks }
        for (const k of keys)
          if (clearing) delete marks[k]
          else marks[k] = markColor
        save({ ...d, marks })
      }
      setSuppress(true)          // el click posterior no alterna
    }
    setDrag(null)
  }

  const onSvgMove = (e) => {
    if (panRef.current) {
      const p = panRef.current
      // arrastra la vista: px de pantalla → unidades de mundo
      setView((v) => ({ ...v,
        x: p.vx - (e.clientX - p.cx) / p.rw * vw,
        y: p.vy - (e.clientY - p.cy) / p.rh * vh }))
      return
    }
    const [x, y] = cellAt(e)
    if (x < 0 || y < 0 || x >= d.cols || y >= d.rows) return
    if (drag) setDrag((m) => ({ ...m, b: [x, y] }))
    if (dragTok) setDragTok((m) => ({ ...m, x, y }))
    if (measure) setMeasure((m) => ({ ...m, b: [x, y] }))
    else if (e.shiftKey && !dragTok) setMeasure({ a: [x, y], b: [x, y] })
  }

  const dist = measure
    ? Math.hypot(measure.b[0] - measure.a[0],
                 measure.b[1] - measure.a[1]) * d.cell_ft : 0

  const W = d.cols * size, H = d.rows * size
  const cells = []
  for (let y = 0; y < d.rows; y++)
    for (let x = 0; x < d.cols; x++) cells.push([x, y])

  /* visión en vista de jugador: la niebla cercana a un token PROPIO
     con vision_ft > 0 se abre (se ve el contenido, la celda sigue
     sombreada). Tokens/pins dentro se muestran. */
  const myToks = readOnly
    ? d.tokens.filter((tk) => tokOwner(tk) === myUid)
    : []
  const lit = (x, y) => myToks.some((tk) =>
    tk.vision_ft &&
    cellDist(tk.x, tk.y, x, y, d.cell_ft) <= tk.vision_ft + 0.01 &&
    // los muros bloquean la visión — nada de ver a través de paredes
    !blockedByWall(d.walls || [], tk.x, tk.y, x, y))
  /* iluminación: cualquier token con light_ft alumbra la niebla —
     no solo los propios (una antorcha ajena también revela el suelo).
     La celda queda semitransparente: se ve terreno pero no quién */
  const litByLight = (x, y) => (d.tokens || []).some((tk) =>
    tk.light_ft &&
    cellDist(tk.x, tk.y, x, y, d.cell_ft) <= tk.light_ft + 0.01 &&
    !blockedByWall(d.walls || [], tk.x, tk.y, x, y))

  const newMap = async () => {
    const name = prompt(t('map.newPrompt'), `Mapa ${maps.length + 1}`)
    if (!name?.trim()) return
    const r = await api.createEntity(campaign.id, {
      kind: 'map', name: name.trim(), visibility: 'public',
      data: { ...DEFAULTS },
    })
    await load()
    setCurId(r.id)
  }

  const renameMap = async () => {
    const name = prompt(t('map.renamePrompt'), map.name)
    if (!name?.trim() || name.trim() === map.name) return
    await api.patchEntity(campaign.id, map.id,
      { name: name.trim(), expected_version: map.version })
    load()
  }

  const delMap = async () => {
    if (!confirm(tf('map.delConfirm', { name: map.name }))) return
    await api.deleteEntity(campaign.id, map.id)
    setCurId(null)
    load()
  }

  if (!maps) return null

  return (
    <div className="mapboard">
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select value={curId ?? ''} aria-label={t('map.picker')}
                onChange={(e) => setCurId(e.target.value)}>
          {maps.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>))}
        </select>
        {!readOnly && <>
          <button className="ghost" onClick={newMap}
                  title={t('map.newTitle')}>＋ {t('map.newLbl')}</button>
          {map && <>
            <button className="ghost" onClick={renameMap}
                    title={t('map.renameTitle')}>✎ {t('map.renameLbl')}</button>
            <button className="ghost" onClick={delMap}
                    title={t('map.delTitle')}>🗑 {t('map.delLbl')}</button>
          </>}
        </>}
        {map && !readOnly && <>
          <span className="tb-sep" aria-hidden="true" />
          <select value={mode} aria-label={t('map.modeAria')}
                  onChange={(e) => setMode(e.target.value)}>
            <option value="move">{t('map.modeMove')}</option>
            <option value="fog">{t('map.modeFog')}</option>
            <option value="mark">{t('map.modeMark')}</option>
            <option value="blast">{t('map.modeBlast')}</option>
            <option value="cone">{t('map.modeCone')}</option>
            <option value="line">{t('map.modeLine')}</option>
            <option value="wall">{t('map.modeWall')}</option>
            <option value="pin">{t('map.modePin')}</option>
          </select>
          {mode === 'pin' && (
            <select value={pinEnt} aria-label={t('map.pinEntAria')}
                    onChange={(e) => setPinEnt(e.target.value)}>
              <option value="">{t('map.pinEntPh')}</option>
              {worldEntities.filter((e) => e.kind !== 'map')
                .map((e) => (
                  <option key={e.id} value={e.id}>{e.name}</option>))}
            </select>)}
          {(mode === 'mark' || mode === 'blast' || mode === 'cone' ||
            mode === 'line') && (
            <span className="row" style={{ gap: 2 }}>
              {MARK_COLORS.map((col) => (
                <button key={col} className="ghost"
                        aria-label={tf('map.markAria', { color: col })}
                        style={{ background: col, width: 18,
                                 height: 18, padding: 0, minWidth: 0,
                                 border: col === markColor
                                   ? '2px solid #fff' : undefined }}
                        onClick={() => setMarkColor(col)} />))}
            </span>)}
          {mode === 'fog' && d.fog.length > 0 && (
            <button className="ghost"
                    onClick={() => save({ ...d, fog: [] })}>
              {t('map.clearFog')}</button>)}
          {mode === 'wall' && (d.walls || []).length > 0 && (
            <button className="ghost"
                    onClick={() => save({ ...d, walls: [] })}>
              {t('map.clearWalls')}</button>)}
          {(mode === 'mark' || mode === 'blast' || mode === 'cone' ||
            mode === 'line') &&
              Object.keys(d.marks).length > 0 && (<>
            <button className="ghost"
                    onClick={() => save({ ...d, marks: {} })}>
              {t('map.clearMarks')}</button>
            {/* resolver daño sobre las casillas pintadas; CD>0 →
                tirada de salvación por afectado (mitad al superar) */}
            <input type="number" min="0" style={{ width: 52 }}
                   aria-label={t('map.zoneDmgAria')}
                   title={t('map.zoneDmgTitle')}
                   value={zoneDmg || ''}
                   onChange={(e) => setZoneDmg(+e.target.value || 0)} />
            <input type="number" min="0" style={{ width: 44 }}
                   aria-label={t('map.zoneDcAria')}
                   title={t('map.zoneDcTitle')}
                   placeholder="CD"
                   value={zoneDc || ''}
                   onChange={(e) => setZoneDc(+e.target.value || 0)} />
            {zoneDc > 0 && (<>
              <select value={zoneSave} aria-label={t('map.zoneSaveAria')}
                      style={{ maxWidth: 74 }}
                      onChange={(e) => setZoneSave(e.target.value)}>
                {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) =>
                  <option key={a} value={a}>{a.toUpperCase()}</option>)}
              </select>
              <input value={zoneDtype} style={{ width: 66 }}
                     aria-label={t('map.zoneDtypeAria')}
                     title={t('map.zoneDtypeTitle')}
                     placeholder={t('map.zoneDtypePh')}
                     onChange={(e) => setZoneDtype(
                       e.target.value.trim().toLowerCase())} />
            </>)}
            <button className="dmg" disabled={!zoneDmg}
                    title={t('map.zoneDmgTitle')}
                    onClick={dmgZone}>{t('map.zoneDmg')}</button>
          </>)}
          <span className="tb-sep" aria-hidden="true" />
          <button className="ghost" onClick={addToken}>
            {t('map.addToken')}</button>
          {/* combate → mapa: volcar los combatientes como tokens
              (los que ya están se actualizan, no se duplican) */}
          {combatants.length > 0 && (
            <button className="ghost" title={t('map.syncTokTitle')}
                    aria-label={t('map.syncTokTitle')}
                    onClick={syncCombatants}>
              ⚔ {t('map.syncTok')}</button>)}
          <span className="tb-sep" aria-hidden="true" />
          <button className="ghost" title={t('map.bgTitle')}
                  aria-label={t('map.bgTitle')}
                  onClick={() => {
            const u = prompt(t('map.bgPrompt'), d.image_url || '')
            if (u === null) return
            // '' — no undefined: el PATCH hace merge y un campo
            // undefined no se serializa (no llegaría a borrar)
            save({ ...d, image_url: u.trim() })
          }}>🖼 {t('map.bgLbl')}</button>
          <button className="ghost" title={t('map.musicTitle')}
                  aria-label={t('map.musicTitle')}
                  onClick={() => {
            const u = prompt(t('map.musicPrompt'), d.music_url || '')
            if (u === null) return
            save({ ...d, music_url: u.trim() })
          }}>♪ {t('map.musicLbl')}</button>
          <label className="muted">{t('map.cellFt')}
            <input type="number" min="1" max="50" defaultValue={d.cell_ft}
                   key={`${map.id}:${d.cell_ft}`}
                   style={{ width: 50 }}
                   aria-label={t('map.cellFtAria')}
                   onBlur={(e) => save({ ...d,
                     cell_ft: Math.max(1, +e.target.value || 5) })} />
          </label>
          <span className="tb-sep" aria-hidden="true" />
          <button className="ghost" title={t('map.colMinus')}
                  onClick={() => resize('cols', -1)}>−col</button>
          <button className="ghost" title={t('map.colPlus')}
                  onClick={() => resize('cols', +1)}>＋col</button>
          <button className="ghost" title={t('map.rowMinus')}
                  onClick={() => resize('rows', -1)}>−fil</button>
          <button className="ghost" title={t('map.rowPlus')}
                  onClick={() => resize('rows', +1)}>＋fil</button>
        </>}
        {/* zoom ±/⛶ — rueda en ratón; en táctil estos botones y
            el paneo con botón central */}
        {map && (
          <span className="row" style={{ gap: 0 }}>
            <span className="tb-sep" aria-hidden="true" />
            <button className="ghost" aria-label={t('map.zoomOut')}
                    onClick={() => setView((v) => ({
                      ...v, z: Math.max(.35, v.z / 1.25) }))}>−</button>
            <button className="ghost" title={t('map.zoomReset')}
                    aria-label={t('map.zoomReset')}
                    onClick={() => setView({ x: 0, y: 0, z: 1 })}>⛶</button>
            <button className="ghost" aria-label={t('map.zoomIn')}
                    onClick={() => setView((v) => ({
                      ...v, z: Math.min(4, v.z * 1.25) }))}>+</button>
          </span>)}
      </div>
      {!readOnly && sel && (
        <div className="row" style={{ fontSize: '.9rem',
                                      alignItems: 'center',
                                      flexWrap: 'wrap' }}>
          <strong>{sel.name}</strong>
          <button className="ghost" onClick={renameTok}
                  title={t('map.renameTok')}>✎</button>
          {sel.ref_id ? (
            <span className="muted">{t('map.linkedHp')}</span>
          ) : sel.hp != null ? <>
            <button className="ghost" aria-label={t('map.hpMinus')}
                    onClick={() => adjHp(-1)}>−</button>
            <span>{sel.hp}/{sel.max_hp}</span>
            <button className="ghost" aria-label={t('map.hpPlus')}
                    onClick={() => adjHp(+1)}>＋</button>
            {/* daño de una tacada desde el grid */}
            <input type="number" min="0" style={{ width: 56 }}
                   aria-label={t('map.dmgAria')} value={tokDmg || ''}
                   onChange={(e) => setTokDmg(+e.target.value || 0)} />
            <button className="ghost" disabled={!tokDmg}
                    onClick={() => adjHp(-tokDmg)}>−{t('com.damage') || 'dmg'}</button>
          </> : (
            <button className="ghost" onClick={setHp}>
              {t('map.tokenHp')}</button>)}
          {/* tamaño en casillas: 1 medio, 2 grande, 3 enorme… */}
          <label className="muted">{t('map.tokSize')}
            <select value={sel.size || 1} aria-label={t('map.tokSizeAria')}
                    onChange={(e) => patchTok({ size: +e.target.value })}>
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>{n}×{n}</option>))}
            </select>
          </label>
          {/* luz emitida (ft): una antorcha de 20ft alumbra la niebla
              para toda la mesa (respetando muros) */}
          <label className="muted">{t('map.lightFt')}
            <input type="number" min="0" max="300" step="5"
                   defaultValue={sel.light_ft || 0}
                   key={`${sel.id}:${sel.light_ft}`}
                   style={{ width: 52 }}
                   aria-label={t('map.lightFtAria')}
                   onBlur={(e) => patchTok({
                     light_ft: Math.max(0, +e.target.value || 0) })} />
          </label>
          {/* radio de visión (ft): abre la niebla alrededor del token
              en la vista del jugador */}
          <label className="muted">{t('map.visionFt')}
            <input type="number" min="0" max="300" step="5"
                   defaultValue={sel.vision_ft || 0}
                   key={`${sel.id}:${sel.vision_ft}`}
                   style={{ width: 52 }}
                   aria-label={t('map.visionFtAria')}
                   onBlur={(e) => patchTok({
                     vision_ft: Math.max(0, +e.target.value || 0) })} />
          </label>
          {Object.keys(speeds).map((k) => (
            <label key={k} className="muted">
              {t(`map.speed.${k}`)}
              <input type="number" min="0" max="300" step="5"
                     defaultValue={speeds[k]} style={{ width: 52 }}
                     aria-label={tf('map.speedAria',
                                    { kind: t(`map.speed.${k}`) })}
                     onBlur={(e) => {
                       const ns = { ...speeds,
                                    [k]: +e.target.value || 0 }
                       setSpeeds(ns)
                       localStorage.setItem('map.speeds',
                                            JSON.stringify(ns))
                     }} />
            </label>))}
          <span className="muted">
            {tf('map.range',
                { ft: Math.max(...Object.values(speeds)) })}</span>
          {/* color del token: sin campo, se asignaba por hue rotativo
              y no se podía ajustar — swatches fijos rápidos */}
          <span className="row" style={{ gap: 2, margin: 0 }}>
            {MARK_COLORS.map((col) => (
              <button key={col} className="ghost"
                      aria-label={tf('map.tokColorAria', { color: col })}
                      style={{ background: col, width: 18, height: 18,
                               padding: 0, minWidth: 0,
                               border: sel.color === col
                                 ? '2px solid #fff' : undefined }}
                      onClick={() => patchTok({ color: col })} />))}
          </span>
          {/* retrato del token: URL de imagen renderizada en el
              círculo (vacío = vuelve a iniciales+color) */}
          <button className="ghost" title={t('map.tokImg')}
                  onClick={() => {
                    const u = prompt(t('map.tokImgPrompt'),
                                     sel.image_url || '')
                    if (u !== null)
                      patchTok({ image_url: u.trim() || undefined })
                  }}>🖼</button>
          {/* atacar: arma de la ficha vinculada o acción del stat
              block — luego clic en el token objetivo */}
          {(linkedChar(sel) || _cbOf(sel)) && (
            <button className="ghost" title={t('map.atkTitle')}
                    onClick={() => startAttack(sel)}>⚔</button>)}
          {/* mapa → tracker: mete el token en el combate activo —
              iniciativa tirada por el servidor, PG de la ficha si
              está vinculado */}
          {combat && !combatants.some((cb) =>
            cb.id === sel.combatant_id ||
            (sel.ref_id && cb.ref_id === sel.ref_id) ||
            cb.name === sel.name) && (
            <button className="ghost" title={t('map.addToCombatTitle')}
                    onClick={async () => {
                      const lc = linkedChar(sel)
                      const r = await api.applyOp(
                        { id: combat.id, version: cver() },
                        'combatant.add',
                        { name: sel.name,
                          kind: lc ? 'character' : 'monster',
                          ref_id: sel.ref_id || undefined,
                          hp_max: lc ? undefined : sel.max_hp },
                        'combat').catch((e) => setZoneLog(`⚠ ${e.message}`))
                      if (!r) return
                      combatVerRef.current = r.version
                      // enlaza el token al combatiente recién creado
                      // (la prop combatants aún es stale → GET fresco)
                      const fresh = await api.getCombat(combat.id)
                        .catch(() => null)
                      const cbt = (fresh?.combat?.combatants || []).find(
                        (cb) => cb.name === sel.name &&
                                !d.tokens.some((t2) =>
                                  t2.combatant_id === cb.id))
                      if (cbt) patchTok({ combatant_id: cbt.id }, sel)
                    }}>＋⚔</button>)}
          {/* vincular a ficha: PG en vivo en el mapa y el jugador
              mueve SU token en la vista de jugador */}
          {chars.length > 0 && (
            <select value={sel.ref_id || ''} aria-label={t('map.linkChar')}
                    style={{ maxWidth: 140 }}
                    onChange={(e) => {
                      const ch = chars.find(
                        (c) => c.id === e.target.value) || null
                      patchTok({
                        ref_id: ch?.id || null,
                        player_id: ch?.player_id || null,
                        ...(ch ? { hp: ch.hp_current,
                                   max_hp: ch.hp_max } : {}),
                      })
                    }}>
              <option value="">{t('map.linkNone')}</option>
              {chars.map((ch) => (
                <option key={ch.id} value={ch.id}>{ch.name}</option>))}
            </select>)}
          <button className="ghost" onClick={dropTok}>
            {t('map.tokenDel')}</button>
        </div>
      )}
      {/* modo ataque: arma/acción elegida → clic en el objetivo */}
      {atkFrom && (
        <div className="row" style={{ fontSize: '.9rem',
                                      alignItems: 'center' }}>
          <strong>⚔ {atkFrom.name}</strong>
          <select value={atkIdx} aria-label={t('map.atkPickAria')}
                  onChange={(e) => setAtkIdx(+e.target.value)}>
            {atkOpts.map((o, i2) => (
              <option key={i2} value={i2}>{o.label}</option>))}
          </select>
          <span className="muted">{t('map.atkHint')}</span>
          <button className="ghost" onClick={() => setAtkFrom(null)}>
            ✕</button>
        </div>)}
      {/* vista de jugador: seleccionado su token — pista de destino
          y ⚔ para atacar desde el mapa (resolución server-side, la
          CA del objetivo no se expone) */}
      {readOnly && sel && (
        <p className="muted" style={{ fontSize: '.9rem' }}>
          <strong>{sel.name}</strong> — {t('map.moveHint')}
          {linkedChar(sel) && canMoveTok(sel) && combat && (
            <button className="ghost" title={t('map.atkTitle')}
                    onClick={() => startAttack(sel)}>⚔</button>)}
        </p>)}
      {/* música ambiental del mapa: url que el DM puso — en la vista
          de jugador aparece un reproductor; el autoplay lo decide el
          navegador (se muestra con controles propios) */}
      {/* es tu turno: un token tuyo es el activo en el tracker */}
      {readOnly && myToks.some((tk) =>
        (activeRef && tk.ref_id === activeRef) ||
        (activeName && tk.name === activeName)) && (
        <p className="notice" role="alert">{t('map.yourTurn')}</p>)}
      {d.music_url && (
        <audio key={d.music_url} controls preload="none" loop
               src={d.music_url}
               style={{ display: 'block', width: '100%', maxWidth: 320,
                        height: 30, opacity: .85 }} />)}
      {zoneLog && (
        <p className="muted" role="status" style={{ fontSize: '.85rem' }}
           onClick={() => setZoneLog(null)}>
          {zoneLog} — <em>×</em></p>)}
      {dist > 0 && (
        <p className="muted">{tf('map.dist', {
          ft: dist.toFixed(0),
          sq: Math.round(dist / d.cell_ft) })}</p>)}
      {/* regla en vivo al arrastrar un token: pies recorridos desde
          el origen — budget de movimiento de la criatura */}
      {dragTok && dragTok.ox != null && (
        <p className="muted">{tf('map.dragDist', {
          ft: cellDist(dragTok.ox, dragTok.oy,
                       dragTok.x, dragTok.y, d.cell_ft).toFixed(0) })}</p>)}
      {/* presupuesto de movimiento del turno: pies acumulados / velocidad */}
      {sel && movedFt[sel.id] != null && (
        <p className="muted">{tf('map.moveBudget', {
          ft: movedFt[sel.id].toFixed(0),
          speed: _tokSpeed(sel) || '?' })}</p>)}

      {/* cinta de iniciativa sobre el tablero: orden del tracker,
          turno activo dorado; clic → selecciona su token en el grid */}
      {combatants.length > 0 && Object.keys(turnOrder).length > 0 && (
        <InitiativeRibbon combatants={combatants} turnOrder={turnOrder}
            activeRef={activeRef} activeName={activeName}
            tokens={d.tokens} t={t} tf={tf}
            selectable={(tk) => !readOnly || canMoveTok(tk)}
            onSelect={setSel} />)}

      {map && (
      <svg ref={svgRef} width={W} height={H} role="application"
           tabIndex={0}
           viewBox={`${view.x} ${view.y} ${vw} ${vh}`}
           aria-label={t('map.canvasAria')}
           onKeyDown={(e) => {
             // flechas mueven el token seleccionado 1 casilla —
             // la única vía de teclado para mover en el grid
             if (!sel) return
             if (e.key === 'Escape') { setSel(null); return }
             const DIRS = { ArrowUp: [0, -1], ArrowDown: [0, 1],
                            ArrowLeft: [-1, 0], ArrowRight: [1, 0] }
             const dv = DIRS[e.key]
             if (!dv) return
             e.preventDefault()
             const nx = sel.x + dv[0], ny = sel.y + dv[1]
             if (nx < 0 || ny < 0 || nx >= d.cols || ny >= d.rows) return
             if (readOnly ? canMoveTok(sel) : mode === 'move')
               moveTokRemote(sel, nx, ny)
           }}
           onClick={onSvgClick} onMouseMove={onSvgMove}
           onMouseDown={onSvgDown} onMouseUp={onSvgUp}
           onContextMenu={(e) => {
             // botón derecho = ping compartido (clásico VTT)
             e.preventDefault()
             const [px, py] = cellAt(e)
             if (px < 0 || py < 0 || px >= d.cols || py >= d.rows) return
             api.ping(campaign.id, map.id, px, py).catch(() => {})
           }}
           onMouseLeave={onSvgUp}
           style={{ background: '#223', borderRadius: 6,
                    maxWidth: '100%', touchAction: 'manipulation',
                    display: 'block', margin: '0 auto' }}>
        {/* imagen de fondo opcional (mapa dibujado, estilo VTT) */}
        {d.image_url && (
          <image href={d.image_url} width={W} height={H}
                 preserveAspectRatio="none" opacity=".75" />)}
        {/* celdas + zonas pintadas + niebla */}
        {cells.map(([x, y]) => {
          const k = `${x},${y}`
          const mk = d.marks[k]
          // la visión del propio token abre la niebla; una luz ajena
          // la deja en penumbra (se ve el terreno, todo atenuado)
          const fogged = d.fog.includes(k)
          const litFull = lit(x, y)
          const litDim = !litFull && litByLight(x, y)
          const fog = fogged && (!readOnly || (!litFull && !litDim))
          const dimFog = readOnly && fogged && litDim
          // el DM ve la niebla translúcida (sabe qué hay debajo);
          // el jugador: opaca, penumbra (.55) o despejada
          return (
            <rect key={k} x={x * size} y={y * size}
                  width={size} height={size}
                  fill={fog ? (readOnly ? 'rgba(0,0,0,.95)'
                                       : 'rgba(0,0,0,.5)')
                        : dimFog ? 'rgba(0,0,0,.55)'
                        : mk || 'transparent'}
                  fillOpacity={mk && !fog ? .4 : 1}
                  stroke="#445" strokeWidth="1" />)
        })}

        {/* muros: líneas de bloqueo sobre los bordes de celda —
            "x,y,E" borde derecho / "x,y,S" borde inferior */}
        {(d.walls || []).map((w) => {
          const [wx, wy, ws] = w.split(',')
          const X = +wx, Y = +wy
          return ws === 'E'
            ? <line key={w} x1={(X + 1) * size} y1={Y * size}
                    x2={(X + 1) * size} y2={(Y + 1) * size}
                    stroke="#e8b033" strokeWidth="3" />
            : <line key={w} x1={X * size} y1={(Y + 1) * size}
                    x2={(X + 1) * size} y2={(Y + 1) * size}
                    stroke="#e8b033" strokeWidth="3" />
        })}

        {/* alcance del token seleccionado: velocidad máx. (azul) y,
            si tiene acciones melé, el alcance mayor (rojo suave —
            zona de amenaza visible sin abrir el stat block) */}
        {!readOnly && sel && (
          <circle cx={(sel.x + (Math.max(1, +(sel.size || 1)) * .5)) * size}
                  cy={(sel.y + (Math.max(1, +(sel.size || 1)) * .5)) * size}
                  r={Math.max(...Object.values(speeds)) / d.cell_ft * size}
                  fill="none" stroke="#4da3ff" strokeWidth="2"
                  strokeDasharray="6 4" opacity=".6" />)}
        {!readOnly && sel && (() => {
          const cbt = _cbOf(sel)
          const acts = (cbt?.stat_block || {}).actions || []
          const reach = Math.max(0, ...acts.map((a) => {
            const m = (a.text || '').match(/reach\s*(\d+)\s*ft/i)
            return m ? +m[1] : 0 }))
          return reach > 0 && (
            <circle cx={(sel.x + (Math.max(1, +(sel.size || 1)) * .5)) * size}
                    cy={(sel.y + (Math.max(1, +(sel.size || 1)) * .5)) * size}
                    r={reach / d.cell_ft * size}
                    fill="#e74c3c" opacity=".12" pointerEvents="none" />)
        })()}

        {/* preview del área al arrastrar: rect para niebla/zona,
            círculo para la plantilla de explosión */}
        {drag && (drag.kind === 'line'
          ? <line x1={(drag.a[0] + .5) * size}
                  y1={(drag.a[1] + .5) * size}
                  x2={(drag.b[0] + .5) * size}
                  y2={(drag.b[1] + .5) * size}
                  stroke={markColor} strokeWidth={size * .35}
                  opacity=".35" pointerEvents="none" />
          : drag.kind === 'cone'
          ? <polygon
              points={(() => {
                const ax = (drag.a[0] + .5) * size
                const ay = (drag.a[1] + .5) * size
                const len = Math.hypot(drag.b[0] - drag.a[0],
                                       drag.b[1] - drag.a[1]) * size
                const ang = Math.atan2(drag.b[1] - drag.a[1],
                                       drag.b[0] - drag.a[0])
                const h = Math.atan(.5)
                const p = (a2) => `${ax + Math.cos(a2) * len},${ay +
                  Math.sin(a2) * len}`
                return `${ax},${ay} ${p(ang - h)} ${p(ang)} ${p(ang + h)}`
              })()}
              fill={markColor} opacity=".35" pointerEvents="none" />
          : drag.kind === 'blast'
          ? <circle cx={(drag.a[0] + .5) * size}
                    cy={(drag.a[1] + .5) * size}
                    r={(Math.hypot(drag.b[0] - drag.a[0],
                                   drag.b[1] - drag.a[1]) + .5) * size}
                    fill={markColor} opacity=".35"
                    pointerEvents="none" />
          : <rect x={Math.min(drag.a[0], drag.b[0]) * size}
                y={Math.min(drag.a[1], drag.b[1]) * size}
                width={(Math.abs(drag.b[0] - drag.a[0]) + 1) * size}
                height={(Math.abs(drag.b[1] - drag.a[1]) + 1) * size}
                fill={drag.kind === 'fog' ? '#000' : markColor}
                opacity=".35" pointerEvents="none" />)}

        {/* ping compartido: anillo que pulsa ~1.5s en la celda */}
        {ping && ping.entity_id === map?.id && (
          <g pointerEvents="none">
            <circle cx={(ping.x + .5) * size} cy={(ping.y + .5) * size}
                    r={size * .25} fill="none"
                    stroke="#ffd700" strokeWidth="3">
              <animate attributeName="r" values={`${size * .15};${size * .7}`}
                       dur=".6s" repeatCount="3" />
              <animate attributeName="opacity" values=".9;0"
                       dur=".6s" repeatCount="3" />
            </circle>
            <text x={(ping.x + .5) * size} y={(ping.y - .3) * size}
                  textAnchor="middle" fill="#ffd700"
                  stroke="#000" strokeWidth={size * .01}
                  fontSize={size * .3}>{ping.by}</text>
          </g>)}

        {/* regla: shift para medir */}
        {measure && (
          <line x1={(measure.a[0] + .5) * size}
                y1={(measure.a[1] + .5) * size}
                x2={(measure.b[0] + .5) * size}
                y2={(measure.b[1] + .5) * size}
                stroke="#ffd700" strokeWidth="2" />)}

        {/* tokens (bajo niebla → ocultos en vista de jugador) */}
        {d.tokens.map((tk) => {
          if (readOnly && d.fog.includes(`${tk.x},${tk.y}`) &&
              !lit(tk.x, tk.y) && !litByLight(tk.x, tk.y))
            return null
          const lx = dragTok?.id === tk.id ? dragTok.x : tk.x
          const ly = dragTok?.id === tk.id ? dragTok.y : tk.y
          const lc = linkedChar(tk)
          // PG en vivo por prioridad: ficha vinculada → combatiente
          // del tracker (monstruos sincronizados) → valor del token
          const cbt = tk.combatant_id
            ? combatants.find((cb) => cb.id === tk.combatant_id)
            : null
          const hp = lc ? lc.hp_current
            : cbt ? cbt.hp_current : tk.hp
          const hpMax = lc ? lc.hp_max
            : cbt ? cbt.hp_max : tk.max_hp
          const movable = canMoveTok(tk)
          const isActive = (activeRef && tk.ref_id === activeRef) ||
                           (activeName && tk.name === activeName)
          const conds = (lc?.conditions?.length ? lc.conditions : null)
            ?? (cbt?.conditions?.length ? cbt.conditions : null)
          return (
            <MapToken key={tk.id}
                tk={{ ...tk, _cellFt: d.cell_ft }} size={size}
                lx={lx} ly={ly} movable={movable}
                dragging={dragTok?.id === tk.id}
                selected={sel?.id === tk.id} active={isActive}
                zoneColor={tokOnMark(tk)
                  ? d.marks[`${tk.x},${tk.y}`] || '#e67e22' : null}
                order={turnOrder[tk.ref_id || tk.name]}
                conds={conds} hp={hp} hpMax={hpMax}
                onDown={(e) => {
                  // arrastrar = mover (modo move del DM o token propio);
                  // ox/oy = origen para la regla de distancia en vivo
                  if (movable && (mode === 'move' || readOnly)) {
                    e.stopPropagation()
                    setDragTok({ id: tk.id, x: tk.x, y: tk.y,
                                 ox: tk.x, oy: tk.y })
                  }
                }}
                onClick={(e) => {
                  e.stopPropagation()
                  if (tokMoved) { setTokMoved(false); return }
                  // modo ataque: el clic en otro token lo resuelve
                  // como objetivo en vez de seleccionarlo
                  if (atkFrom && tk.id !== atkFrom.id) {
                    resolveAtk(tk); return }
                  if (movable)
                    setSel(sel?.id === tk.id ? null : tk)
                }} />)
        })}

        {/* pins ligados a entidades del mundo — atlas estilo
            LegendKeeper: 📍 + nombre; clic abre nombre/notas */}
        {d.pins.map((p) => {
          const ent = worldEntities.find((e) => e.id === p.entity_id)
          // pin a una entidad que el jugador no conoce → oculto
          if (readOnly && !ent) return null
          if (readOnly && d.fog.includes(`${p.x},${p.y}`) &&
              !lit(p.x, p.y) && !litByLight(p.x, p.y)) return null
          return (
            <MapPin key={p.id} p={p} ent={ent} size={size}
                selected={selPin?.id === p.id}
                onClick={(e) => {
                  e.stopPropagation()
                  setSelPin(selPin?.id === p.id ? null : p)
                }} />)
        })}
      </svg>)}

      {/* ficha del pin seleccionado: nombre + notas con wiki-links;
          el DM puede quitarlo */}
      {selPin && (() => {
        const ent = worldEntities.find((e) => e.id === selPin.entity_id)
        return (
          <div className="row" style={{ fontSize: '.9rem',
                                        alignItems: 'baseline',
                                        flexWrap: 'wrap' }}>
            <strong>📍 {ent?.name || t('map.pinUnlinked')}</strong>
            {ent?.data?.notes && (
              <span className="muted">
                <WikiText text={ent.data.notes}
                          entities={worldEntities} /></span>)}
            {!readOnly && (
              <button className="ghost" onClick={() => {
                save({ ...d,
                       pins: d.pins.filter((p) => p.id !== selPin.id) })
                setSelPin(null)
              }}>{t('map.pinDel')}</button>)}
          </div>)
      })()}

      {!readOnly && (
        <p className="muted" style={{ fontSize: '.8rem' }}>
          {t('map.hint')}
        </p>)}
    </div>
  )
}
