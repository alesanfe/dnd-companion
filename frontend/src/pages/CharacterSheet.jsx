import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api.js'

export default function CharacterSheet() {
  const { id } = useParams()
  const [char, setChar] = useState(null)
  const [amount, setAmount] = useState(1)
  const [expr, setExpr] = useState('1d20')
  const [rollLog, setRollLog] = useState([])
  const [err, setErr] = useState(null)

  const load = () => api.getCharacter(id).then(setChar).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [id])

  // Sync en vivo: si el personaje está en una campaña, escucha eventos
  // de la sala y recarga cuando algo lo toca.
  useEffect(() => {
    if (!char?.campaign_id) return undefined
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/campaign/${char.campaign_id}`)
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type === 'event' && msg.event?.aggregate_id === id) load()
    }
    return () => ws.close()
  }, [char?.campaign_id, id])

  const op = async (type, payload) => {
    try {
      await api.applyOp(char, type, payload)
      load()
    } catch (e) {
      setErr(e.message)
      load() // resync on conflict
    }
  }

  const doRoll = async (e) => {
    e.preventDefault()
    const r = await api.roll(expr)
    setRollLog((l) => [`${r.expression} → ${r.kept.join('+')}${r.modifier ? `${r.modifier}` : ''} = ${r.total}`, ...l].slice(0, 10))
  }

  if (err && !char) return <main><p className="error">{err}</p></main>
  if (!char) return <main><p>Cargando…</p></main>

  const d = char.data
  const hp = d.hp || { current: 0, max: 0, temp: 0 }
  const slots = d.spell_slots || {}

  return (
    <main>
      <h1>{char.name}</h1>
      {err && <p className="error">{err}</p>}

      <section className="card">
        <h2>Puntos de golpe</h2>
        <div className="hp-big">
          {hp.current} / {hp.max}
          {hp.temp > 0 && <span className="temp"> +{hp.temp} temp</span>}
        </div>
        <div className="row">
          <input type="number" min="1" value={amount}
                 onChange={(e) => setAmount(+e.target.value)} />
          <button className="dmg" onClick={() => op('character.hp.damage', { amount })}>Daño</button>
          <button className="heal" onClick={() => op('character.hp.heal', { amount })}>Curar</button>
        </div>
      </section>

      <section className="card">
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
        <section className="card">
          <h2>Espacios de conjuro</h2>
          {Object.entries(slots).map(([lvl, s]) => (
            <div key={lvl} className="row">
              <span>Nivel {lvl}: {s.total - s.used}/{s.total}</span>
              <button disabled={s.used >= s.total}
                      onClick={() => op('character.spell_slot.use', { level: +lvl })}>
                Usar
              </button>
            </div>
          ))}
        </section>
      )}

      {(d.resources || []).length > 0 && (
        <section className="card">
          <h2>Recursos</h2>
          {d.resources.map((r) => (
            <div key={r.id} className="row">
              <span>{r.name}: {r.current}/{r.max} <em className="muted">({r.reset_on})</em></span>
              <button disabled={r.current <= 0}
                      onClick={() => op('character.resource.consume', { resource_id: r.id })}>
                Usar
              </button>
            </div>
          ))}
        </section>
      )}

      {(d.conditions || []).length > 0 && (
        <section className="card">
          <h2>Condiciones</h2>
          {d.conditions.map((c) => (
            <span key={c} className="chip">
              {c}
              <button onClick={() => op('character.condition.remove', { condition: c })}>×</button>
            </span>
          ))}
        </section>
      )}

      <section className="card">
        <h2>Dados</h2>
        <form onSubmit={doRoll} className="row">
          <input value={expr} onChange={(e) => setExpr(e.target.value)}
                 placeholder="2d6+3, 1d20adv, 4d6kh3" />
          <button type="submit">Tirar</button>
        </form>
        <ul className="log">{rollLog.map((l, i) => <li key={i}>{l}</li>)}</ul>
      </section>
    </main>
  )
}
