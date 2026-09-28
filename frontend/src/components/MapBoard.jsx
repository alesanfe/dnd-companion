import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useT } from '../i18n.jsx'
import WikiText from './WikiText.jsx'

const CELL = 44
const MARK_COLORS = ['#27ae60', '#2980b9', '#c0392b', '#f39c12',
                     '#8e44ad', '#7f8c8d']
const DEFAULTS = { cols: 16, rows: 10, cell_ft: 5, tokens: [],
                   fog: [], marks: {}, pins: [] }

// distancia en pies entre el centro de dos celdas
const cellDist = (x1, y1, x2, y2, ft) =>
  Math.hypot(x2 - x1, y2 - y1) * ft

/** Grid táctico estilo Owlbear: varios mapas/escenas por campaña,
    tokens movibles (auto-numeración, PG, renombrar), niebla de
    guerra, zonas pintadas y regla de distancia. Persiste en
    entidades 'map' de la campaña; con readOnly los tokens bajo
    niebla se ocultan (vista de jugador). */
export default function MapBoard({ campaign, size = CELL,
                                  readOnly = false, viewer = 'dm',
                                  entities = null,
                                  worldEntities = [],
                                  chars = [], myUid = null }) {
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

  const onCell = (x, y) => {
    if (mode === 'fog') {
      const k = `${x},${y}`
      save({ ...d, fog: d.fog.includes(k)
        ? d.fog.filter((f) => f !== k) : [...d.fog, k] })
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
    onCell(x, y)
  }

  /* pintar en área: arrastrar con la herramienta niebla/zona
     cubre (o limpia, si la celda ancla ya lo estaba) el
     rectángulo entero */
  const onSvgDown = (e) => {
    if (readOnly || (mode !== 'fog' && mode !== 'mark' &&
                     mode !== 'blast')) return
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
  const lit = (x, y) => myToks.some((tk) => tk.vision_ft &&
    cellDist(tk.x, tk.y, x, y, d.cell_ft) <= tk.vision_ft + 0.01)

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
          {(mode === 'mark' || mode === 'blast') && (
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
          {(mode === 'mark' || mode === 'blast') &&
              Object.keys(d.marks).length > 0 && (
            <button className="ghost"
                    onClick={() => save({ ...d, marks: {} })}>
              {t('map.clearMarks')}</button>)}
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
      {dist > 0 && (
        <p className="muted">{tf('map.dist', {
          ft: dist.toFixed(0),
          sq: Math.round(dist / d.cell_ft) })}</p>)}

      {map && (
      <svg width={W} height={H} role="img"
           aria-label={t('map.canvasAria')}
           onClick={onSvgClick} onMouseMove={onSvgMove}
           onMouseDown={onSvgDown} onMouseUp={onSvgUp}
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

        {/* alcance del token seleccionado */}
        {!readOnly && sel && (
          <circle cx={(sel.x + .5) * size} cy={(sel.y + .5) * size}
                  r={Math.max(...Object.values(speeds)) / d.cell_ft * size}
                  fill="none" stroke="#4da3ff" strokeWidth="2"
                  strokeDasharray="6 4" opacity=".6" />)}

        {/* preview del área al arrastrar: rect para niebla/zona,
            círculo para la plantilla de explosión */}
        {drag && (drag.kind === 'blast'
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
                      stroke={sel?.id === tk.id ? '#fff' : '#111'}
                      strokeWidth={sel?.id === tk.id ? 3 : 1} />
              <text x={(lx + tsize * .5) * size}
                    y={(ly + tsize * .5) * size + tr * .5}
                    textAnchor="middle" fill="#fff"
                    fontSize={tr * .72} pointerEvents="none">
                {tk.name.slice(0, 2).toUpperCase()}</text>
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
