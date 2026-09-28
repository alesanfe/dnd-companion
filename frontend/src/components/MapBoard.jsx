import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useT } from '../i18n.jsx'
import WikiText from './WikiText.jsx'

const CELL = 44
const MARK_COLORS = ['#27ae60', '#2980b9', '#c0392b', '#f39c12',
                     '#8e44ad', '#7f8c8d']
const DEFAULTS = { cols: 16, rows: 10, cell_ft: 5, tokens: [],
                   fog: [], marks: {}, pins: [], walls: [] }

// distancia en pies entre el centro de dos celdas
const cellDist = (x1, y1, x2, y2, ft) =>
  Math.hypot(x2 - x1, y2 - y1) * ft

// segmento (p→q) cruza segmento (a→b)? test de orientación estándar
const _cross = (o, a, b) =>
  (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
const segsCross = (p, q, a, b) => {
  const d1 = _cross(a, b, p), d2 = _cross(a, b, q)
  const d3 = _cross(p, q, a), d4 = _cross(p, q, b)
  return (d1 > 0 && d2 < 0 || d1 < 0 && d2 > 0) &&
         (d3 > 0 && d4 < 0 || d3 < 0 && d4 > 0)
}
// el segmento token→celda cruza algún muro? coordenadas de celda
const blockedByWall = (walls, x1, y1, x2, y2) =>
  walls.some((w) => {
    const [wx, wy, ws] = w.split(',')
    const X = +wx, Y = +wy
    const [a, b] = ws === 'E'
      ? [[X + 1, Y], [X + 1, Y + 1]]
      : [[X, Y + 1], [X + 1, Y + 1]]
    return segsCross([x1 + .5, y1 + .5], [x2 + .5, y2 + .5], a, b)
  })

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
                                  turnOrder = {} }) {
  // entities externas → la lista la gestiona el padre (vista de
  // jugador: mantiene la escena elegida al refrescar por WS)
  const [ownMaps, setMaps] = useState(null)
  const maps = entities ?? ownMaps
  const [curId, setCurId] = useState(null)
  const [mode, setMode] = useState('move')  // move|fog|mark
  const [markColor, setMarkColor] = useState(MARK_COLORS[0])
  const [sel, setSel] = useState(null)      // token seleccionado
  const [selPin, setSelPin] = useState(null) // pin seleccionado
  const [pinEnt, setPinEnt] = useState('')   // entidad a enlazar (modo pin)
  const [measure, setMeasure] = useState(null) // {a:[x,y], b:[x,y]}
  const [drag, setDrag] = useState(null)    // pintar área {a,b,kind}
  const [dragTok, setDragTok] = useState(null) // arrastrar token {id,x,y}
  const [tokMoved, setTokMoved] = useState(false)
  const [tokDmg, setTokDmg] = useState(0)   // daño rápido al token
  const [zoneDmg, setZoneDmg] = useState(0) // daño a la zona marcada
  const [zoneLog, setZoneLog] = useState(null)
  const [suppress, setSuppress] = useState(false)
  const [speeds, setSpeeds] = useState(() => {
    try { return JSON.parse(localStorage.getItem('map.speeds')) ||
           { walk: 30, fly: 0, swim: 0, climb: 0 } }
    catch { return { walk: 30, fly: 0, swim: 0, climb: 0 } }
  })
  const { t, tf } = useT()

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
    setSel(null); setMeasure(null); setSelPin(null)
  }, [curId])

  // escena por defecto: la primera disponible; conserva la elegida
  // mientras siga existiendo (también con entities externas)
  useEffect(() => {
    if (!maps?.length) return
    setCurId((prev) => maps.find((e) => e.id === prev)
      ? prev : maps[0].id)
  }, [maps])

  const save = async (data) => {
    await api.patchEntity(campaign.id, map.id, { data })
    setMaps((ms) => ms.map((m) =>
      m.id === map.id ? { ...m, data } : m))
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
        { id: `p${Date.now()}`, x, y, entity_id: pinEnt }] })
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
      id: `t${Date.now()}`,
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
    || linkedChar(tk)?.player_id || null
  const canMoveTok = (tk) => !readOnly
    || (myUid != null && tokOwner(tk) === myUid)
  const moveTokRemote = (tk, x, y) => {
    if (!readOnly) { patchTok({ x, y }, tk); return }
    api.moveToken(campaign.id, map.id, tk.id, x, y).catch(() => {})
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
  const dmgZone = async () => {
    if (!zoneDmg) return
    const res = []
    let toks = d.tokens
    for (const tk of d.tokens) {
      if (!tokOnMark(tk)) continue
      const lc = linkedChar(tk)
      if (lc) {
        // op real sobre la ficha — idempotente y deshacible
        const r = await api.applyOp(lc, 'character.hp.damage',
                                    { amount: zoneDmg }).catch(() => null)
        res.push(`${tk.name}: ${r ? zoneDmg : '✗'}`)
      } else {
        const hp = Math.max(0, (tk.hp ?? 0) - zoneDmg)
        toks = toks.map((t2) => t2.id === tk.id ? { ...t2, hp } : t2)
        res.push(`${tk.name}: ${zoneDmg}`)
      }
    }
    if (toks !== d.tokens) save({ ...d, tokens: toks })
    setZoneLog(res.length ? res.join(' · ') : t('map.zoneEmpty'))
  }

  const dropTok = () => {
    if (!confirm(tf('map.tokenDelConfirm', { name: sel.name }))) return
    save({ ...d, tokens: d.tokens.filter((tk) => tk.id !== sel.id) })
    setSel(null)
  }

  const cellAt = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    return [Math.floor((e.clientX - r.left) / size),
            Math.floor((e.clientY - r.top) / size)]
  }

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
    if (readOnly || (mode !== 'fog' && mode !== 'mark' &&
                     mode !== 'blast' && mode !== 'cone' &&
                     mode !== 'line')) return
    const [x, y] = cellAt(e)
    if (x < 0 || y < 0 || x >= d.cols || y >= d.rows) return
    setDrag({ a: [x, y], b: [x, y], kind: mode })
  }

  const onSvgUp = () => {
    // soltar tras arrastrar un token → commit de la posición
    if (dragTok) {
      const tk = d.tokens.find((t2) => t2.id === dragTok.id)
      if (tk && (tk.x !== dragTok.x || tk.y !== dragTok.y)) {
        moveTokRemote(tk, dragTok.x, dragTok.y)
        setTokMoved(true)          // el click posterior no alterna selección
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
        // cono 5e: el ancho igual a la longitud en cada punto —
        // celda dentro si está a ≤ alcance y a ≤26.6° del eje
        const len = Math.hypot(x2 - x1, y2 - y1) + .5
        const ang = Math.atan2(y2 - y1, x2 - x1)
        const half = Math.atan(.5)          // 53.13°/2 — cono D&D
        keys = [`${x1},${y1}`]              // el ápice siempre dentro
        const lo = Math.floor(-len), hi = Math.ceil(len)
        for (let yy = y1 + lo; yy <= y1 + hi; yy++)
          for (let xx = x1 + lo; xx <= x1 + hi; xx++) {
            const dd = Math.hypot(xx - x1, yy - y1)
            if (dd < 0.01 || dd > len) continue
            let da = Math.atan2(yy - y1, xx - x1) - ang
            while (da > Math.PI) da -= 2 * Math.PI
            while (da < -Math.PI) da += 2 * Math.PI
            if (Math.abs(da) <= half + .02) keys.push(`${xx},${yy}`)
          }
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
    await api.patchEntity(campaign.id, map.id, { name: name.trim() })
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
                  title={t('map.newTitle')}>＋</button>
          {map && <>
            <button className="ghost" onClick={renameMap}
                    title={t('map.renameTitle')}>✎</button>
            <button className="ghost" onClick={delMap}
                    title={t('map.delTitle')}>🗑</button>
          </>}
        </>}
        {map && !readOnly && <>
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
            {/* resolver daño sobre las casillas pintadas */}
            <input type="number" min="0" style={{ width: 52 }}
                   aria-label={t('map.zoneDmgAria')}
                   title={t('map.zoneDmgTitle')}
                   value={zoneDmg || ''}
                   onChange={(e) => setZoneDmg(+e.target.value || 0)} />
            <button className="dmg" disabled={!zoneDmg}
                    title={t('map.zoneDmgTitle')}
                    onClick={dmgZone}>{t('map.zoneDmg')}</button>
          </>)}
          <button className="ghost" onClick={addToken}>
            {t('map.addToken')}</button>
          <button className="ghost" title={t('map.bgTitle')}
                  aria-label={t('map.bgTitle')}
                  onClick={() => {
            const u = prompt(t('map.bgPrompt'), d.image_url || '')
            if (u === null) return
            // '' — no undefined: el PATCH hace merge y un campo
            // undefined no se serializa (no llegaría a borrar)
            save({ ...d, image_url: u.trim() })
          }}>🖼</button>
          <label className="muted">{t('map.cellFt')}
            <input type="number" min="1" max="50" defaultValue={d.cell_ft}
                   key={`${map.id}:${d.cell_ft}`}
                   style={{ width: 50 }}
                   aria-label={t('map.cellFtAria')}
                   onBlur={(e) => save({ ...d,
                     cell_ft: Math.max(1, +e.target.value || 5) })} />
          </label>
          <button className="ghost" title={t('map.colMinus')}
                  onClick={() => resize('cols', -1)}>−col</button>
          <button className="ghost" title={t('map.colPlus')}
                  onClick={() => resize('cols', +1)}>＋col</button>
          <button className="ghost" title={t('map.rowMinus')}
                  onClick={() => resize('rows', -1)}>−fil</button>
          <button className="ghost" title={t('map.rowPlus')}
                  onClick={() => resize('rows', +1)}>＋fil</button>
        </>}
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
      {/* vista de jugador: seleccionado su token — pista de destino */}
      {readOnly && sel && (
        <p className="muted" style={{ fontSize: '.9rem' }}>
          <strong>{sel.name}</strong> — {t('map.moveHint')}
        </p>)}
      {zoneLog && (
        <p className="muted" role="status" style={{ fontSize: '.85rem' }}
           onClick={() => setZoneLog(null)}>
          {zoneLog} — <em>×</em></p>)}
      {dist > 0 && (
        <p className="muted">{tf('map.dist', {
          ft: dist.toFixed(0),
          sq: Math.round(dist / d.cell_ft) })}</p>)}

      {map && (
      <svg width={W} height={H} role="img"
           aria-label={t('map.canvasAria')}
           onClick={onSvgClick} onMouseMove={onSvgMove}
           onMouseDown={onSvgDown} onMouseUp={onSvgUp}
           onContextMenu={(e) => {
             // botón derecho = ping compartido (clásico VTT)
             e.preventDefault()
             const [px, py] = cellAt(e)
             if (px < 0 || py < 0 || px >= d.cols || py >= d.rows) return
             api.ping(campaign.id, map.id, px, py).catch(() => {})
           }}
           onMouseLeave={() => setDrag(null)}
           style={{ background: '#223', borderRadius: 6,
                    maxWidth: '100%', touchAction: 'manipulation' }}>
        {/* imagen de fondo opcional (mapa dibujado, estilo VTT) */}
        {d.image_url && (
          <image href={d.image_url} width={W} height={H}
                 preserveAspectRatio="none" opacity=".75" />)}
        {/* celdas + zonas pintadas + niebla */}
        {cells.map(([x, y]) => {
          const k = `${x},${y}`
          const mk = d.marks[k]
          // la visión del propio token abre la niebla cercana
          const fog = d.fog.includes(k) && (!readOnly || !lit(x, y))
          // el DM ve la niebla translúcida (sabe qué hay debajo);
          // el jugador la ve casi opaca
          return (
            <rect key={k} x={x * size} y={y * size}
                  width={size} height={size}
                  fill={fog ? (readOnly ? 'rgba(0,0,0,.95)'
                                       : 'rgba(0,0,0,.5)')
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

        {/* alcance del token seleccionado */}
        {!readOnly && sel && (
          <circle cx={(sel.x + .5) * size} cy={(sel.y + .5) * size}
                  r={Math.max(...Object.values(speeds)) / d.cell_ft * size}
                  fill="none" stroke="#4da3ff" strokeWidth="2"
                  strokeDasharray="6 4" opacity=".6" />)}

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
              !lit(tk.x, tk.y))
            return null
          const lx = dragTok?.id === tk.id ? dragTok.x : tk.x
          const ly = dragTok?.id === tk.id ? dragTok.y : tk.y
          const lc = linkedChar(tk)
          // PG: vinculado a ficha → en vivo; suelto → hp del token
          const hp = lc ? lc.hp_current : tk.hp
          const hpMax = lc ? lc.hp_max : tk.max_hp
          const movable = canMoveTok(tk)
          // size = casillas que ocupa (grande 2×2, enorme 3×3…) —
          // el anchor es la esquina sup. izquierda del footprint
          const tsize = Math.max(1, +(tk.size || 1))
          const tr = tsize * size * .5 - 2
          return (
            <g key={tk.id}
               onMouseDown={(e) => {
                 // arrastrar = mover (modo move del DM o token propio)
                 if (movable && (mode === 'move' || readOnly)) {
                   e.stopPropagation()   // no arranca pintura de niebla
                   setDragTok({ id: tk.id, x: tk.x, y: tk.y })
                 }
               }}
               onClick={(e) => {
                 e.stopPropagation()
                 if (tokMoved) { setTokMoved(false); return }
                 if (movable)
                   setSel(sel?.id === tk.id ? null : tk)
               }}
               opacity={dragTok?.id === tk.id ? .55 : 1}
               style={{ cursor: movable ? 'grab' : 'default' }}>
              <circle cx={(lx + tsize * .5) * size}
                      cy={(ly + tsize * .5) * size}
                      r={tr} fill={tk.color}
                      stroke={sel?.id === tk.id ? '#fff'
                        : (activeRef && tk.ref_id === activeRef)
                          ? '#ffd700' : '#111'}
                      strokeWidth={sel?.id === tk.id ||
                                   (activeRef && tk.ref_id === activeRef)
                        ? 3 : 1} />
              {/* posición en la iniciativa: número sobre el token si
                  el combatiente está en el tracker activo */}
              {tk.ref_id && turnOrder[tk.ref_id] && (
                <text x={(lx + tsize * .5 - tsize * .45) * size}
                      y={(ly + tsize * .5 - tsize * .4) * size + size * .18}
                      fill="#9cf" fontSize={size * .26}
                      fontWeight="bold" pointerEvents="none">
                  {turnOrder[tk.ref_id]}</text>)}
              {/* turno activo en el tracker → anillo dorado pulsante */}
              {activeRef && tk.ref_id === activeRef && (
                <circle cx={(lx + tsize * .5) * size}
                        cy={(ly + tsize * .5) * size}
                        r={tr + 3} fill="none" stroke="#ffd700"
                        strokeWidth={1.5}>
                  <animate attributeName="opacity" values="1;.3;1"
                           dur="1.2s" repeatCount="indefinite" />
                </circle>)}
              <text x={(lx + tsize * .5) * size}
                    y={(ly + tsize * .5) * size + tr * .5}
                    textAnchor="middle" fill="#fff"
                    fontSize={tr * .72} pointerEvents="none">
                {tk.name.slice(0, 2).toUpperCase()}</text>
              {/* insignia de condiciones: la ficha vinculada lleva
                  estados activos → punto naranja en la esquina */}
              {lc && (lc.conditions || []).length > 0 && (
                <circle cx={(lx + tsize * .92) * size}
                        cy={(ly + tsize * .08) * size}
                        r={size * .13} fill="#e67e22"
                        stroke="#111" strokeWidth={1}>
                  <title>{lc.conditions.join(', ')}</title>
                </circle>)}
              {hp != null && hpMax != null && (
                <g>
                  <rect x={lx * size + 2} y={ly * size + 2}
                        width={tsize * size - 4} height={4} rx={2}
                        fill="#000" opacity=".6" />
                  <rect x={lx * size + 2} y={ly * size + 2}
                        width={(tsize * size - 4) *
                               Math.max(0, hp / hpMax)}
                        height={4} rx={2}
                        fill={hp / hpMax > .5 ? '#27ae60'
                              : hp > 0 ? '#e67e22' : '#c0392b'} />
                </g>)}
            </g>)
        })}

        {/* pins ligados a entidades del mundo — atlas estilo
            LegendKeeper: 📍 + nombre; clic abre nombre/notas */}
        {d.pins.map((p) => {
          const ent = worldEntities.find((e) => e.id === p.entity_id)
          // pin a una entidad que el jugador no conoce → oculto
          if (readOnly && !ent) return null
          if (readOnly && d.fog.includes(`${p.x},${p.y}`) &&
              !lit(p.x, p.y)) return null
          return (
            <g key={p.id}
               onClick={(e) => {
                 e.stopPropagation()
                 setSelPin(selPin?.id === p.id ? null : p)
               }}
               style={{ cursor: 'pointer' }}>
              <text x={(p.x + .5) * size} y={(p.y + .58) * size}
                    textAnchor="middle" fontSize={size * .55}>
                📍</text>
              {ent && (
                <text x={(p.x + .5) * size} y={(p.y + .98) * size}
                      textAnchor="middle" fill="#fff"
                      stroke="#000" strokeWidth={size * .012}
                      fontSize={size * .26} pointerEvents="none">
                  {ent.name.slice(0, 16)}</text>)}
            </g>)
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
