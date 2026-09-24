import { useEffect, useState } from 'react'
import { api } from '../api.js'

const CELL = 34
const COLORS = ['#c0392b', '#2980b9', '#27ae60', '#f39c12', '#8e44ad']

/** Mapa táctico mínimo: grid + tokens + distancias + niebla de guerra.
    Estado persistido en una campaign_entity kind='map' (data JSON). */
export default function MapBoard({ campaign }) {
  const [map, setMap] = useState(null)   // {id, data:{cols,rows,tokens,fog,cell_ft}}
  const [mode, setMode] = useState('move')     // move|measure|fog
  const [selected, setSelected] = useState(null)  // token id o primera celda medida
  const [measure, setMeasure] = useState(null)
  const [tokenName, setTokenName] = useState('')
  const [pending, setPending] = useState(false)   // colocando token nuevo

  const load = async () => {
    const r = await api.listEntities(campaign.id, 'map')
    if (r.entities.length) setMap(r.entities[0])
    else {
      const r2 = await api.createEntity(campaign.id, {
        kind: 'map', name: 'Mapa', visibility: 'public',
        data: { cols: 16, rows: 10, cell_ft: 5, tokens: [], fog: [] },
      })
      const r3 = await api.listEntities(campaign.id, 'map')
      setMap(r3.entities.find((e) => e.id === r2.id))
    }
  }
  useEffect(() => { load() }, [campaign.id])

  const save = (data) => {
    setMap({ ...map, data })
    api.patchEntity(campaign.id, map.id, { data })
  }

  const onCell = (x, y) => {
    const d = map.data
    if (mode === 'fog') {
      const key = `${x},${y}`
      const fog = d.fog.includes(key)
        ? d.fog.filter((k) => k !== key) : [...d.fog, key]
      save({ ...d, fog })
      return
    }
    if (mode === 'measure') {
      if (!measure) { setMeasure({ x, y }); return }
      const dist = Math.max(Math.abs(x - measure.x),
                            Math.abs(y - measure.y)) * d.cell_ft
      alert(`Distancia: ${dist} ft (${Math.max(Math.abs(x - measure.x), Math.abs(y - measure.y))} casillas)`)
      setMeasure(null)
      return
    }
    // move: colocar token nuevo o mover seleccionado
    if (pending && tokenName) {
      const t = { id: crypto.randomUUID(), name: tokenName, x, y,
                  color: COLORS[d.tokens.length % COLORS.length] }
      save({ ...d, tokens: [...d.tokens, t] })
      setPending(false); setTokenName('')
      return
    }
    if (selected) {
      save({ ...d, tokens: d.tokens.map((t) =>
        t.id === selected ? { ...t, x, y } : t) })
      setSelected(null)
    }
  }

  const onToken = (e, t) => {
    e.stopPropagation()
    if (mode === 'move') setSelected(selected === t.id ? null : t.id)
  }

  if (!map) return null
  const d = map.data
  const W = d.cols * CELL, H = d.rows * CELL
  const cells = []
  for (let y = 0; y < d.rows; y++)
    for (let x = 0; x < d.cols; x++)
      cells.push({ x, y, fog: d.fog.includes(`${x},${y}`) })

  return (
    <section className="card">
      <h2>Mapa</h2>
      <div className="row">
        {['move', 'measure', 'fog'].map((m) => (
          <button key={m} className={mode === m ? '' : 'ghost'}
                  onClick={() => { setMode(m); setSelected(null); setMeasure(null) }}>
            {m === 'move' ? 'Mover' : m === 'measure' ? 'Medir' : 'Niebla'}
          </button>
        ))}
      </div>
      <div className="row">
        <input value={tokenName} placeholder="Nombre token"
               onChange={(e) => setTokenName(e.target.value)} />
        <button disabled={!tokenName || pending}
                onClick={() => setPending(true)}>
          {pending ? 'Toca una casilla' : 'Añadir token'}
        </button>
      </div>
      {measure && <p className="map-info">Toca la segunda casilla…</p>}
      <svg className="map-grid" width={W} height={H} role="grid"
           aria-label="Mapa táctico">
        {cells.map((c) => (
          <rect key={`${c.x},${c.y}`} className={`map-cell ${c.fog ? 'fog' : ''}`}
                x={c.x * CELL} y={c.y * CELL} width={CELL} height={CELL}
                fill="transparent" stroke="#444" strokeWidth="0.5"
                onClick={() => onCell(c.x, c.y)} />
        ))}
        {measure && (
          <rect x={measure.x * CELL} y={measure.y * CELL}
                width={CELL} height={CELL} fill="none"
                stroke="#ffd700" strokeWidth="2" />
        )}
        {d.tokens.map((t) => (
          <g key={t.id} className="map-token" onClick={(e) => onToken(e, t)}>
            <circle cx={t.x * CELL + CELL / 2} cy={t.y * CELL + CELL / 2}
                    r={CELL * 0.4} fill={t.color}
                    stroke={selected === t.id ? '#ffd700' : '#fff'}
                    strokeWidth={selected === t.id ? 3 : 1} />
            <text x={t.x * CELL + CELL / 2} y={t.y * CELL + CELL / 2}>
              {t.name.slice(0, 3).toUpperCase()}
            </text>
          </g>
        ))}
      </svg>
      <p className="muted">Casilla = {d.cell_ft} ft · niebla solo visible para el DM</p>
    </section>
  )
}
