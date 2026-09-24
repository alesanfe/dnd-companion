import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api.js'

export default function CharacterSheet() {
  const { id } = useParams()
  const [char, setChar] = useState(null)
  const [amount, setAmount] = useState(1)
  const [expr, setExpr] = useState('1d20')
  const [rollType, setRollType] = useState('check')
  const [rollLog, setRollLog] = useState([])
  const [err, setErr] = useState(null)
  const [history, setHistory] = useState(null)
  const [newItem, setNewItem] = useState('')
  const [newCond, setNewCond] = useState('')
  const [coin, setCoin] = useState('gp')
  const [actions, setActions] = useState(null)
  const [focus, setFocus] = useState(false)   // modo concentración

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
    const ws = new WebSocket(`${proto}://${location.host}/ws/campaign/${char.campaign_id}`)
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
      await api.applyOp(char, type, payload)
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
          {focus ? 'Salir del modo mesa' : 'Modo mesa'}
        </button>
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
          <button className="ghost" onClick={() => setRollRequest(null)}>Descartar</button>
        </section>
      )}

      <div className="row">
        <span className="muted">PX: {d.xp || 0}</span>
        <input type="number" min="0" style={{ maxWidth: 90 }} value={xpAdd}
               onChange={(e) => setXpAdd(+e.target.value)} />
        <button disabled={!xpAdd} onClick={() => {
          op('character.xp.add', { amount: xpAdd }); setXpAdd(0)
        }}>+XP</button>
        {d.concentrating_on && (
          <span className="chip">
            ⭑ {d.concentrating_on}
            <button aria-label="Romper concentración" onClick={() =>
              op('character.concentration.break', {})}>×</button>
          </span>
        )}
      </div>

      {history && (
        <section className="card optional">
          <h2>Historial <span className="muted">(reversible)</span></h2>
          {history.map((h) => (
            <div key={h.operation_id} className="row">
              <span className="muted">{h.timestamp.slice(11, 19)}</span>
              <span style={{ flex: 1 }}>{h.operation_type}</span>
              {h.reversible ? (
                <button onClick={async () => {
                  await api.undoOp(h.operation_id)
                  setHistory(null)
                  load()
                }}>Deshacer</button>
              ) : <span className="muted">—</span>}
            </div>
          ))}
        </section>
      )}

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

      <section className="card optional">
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

      <section className="card">
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
              </li>))}
            </ul>
          </div>
        ))}
      </section>

      <section className="card optional">
        <h2>Condiciones</h2>
        <div className="row">
          <input value={newCond} onChange={(e) => setNewCond(e.target.value)}
                 placeholder="poisoned, stunned…" />
          <button disabled={!newCond.trim()} onClick={() => {
            op('character.condition.apply', { condition: newCond.trim() })
            setNewCond('')
          }}>Aplicar</button>
        </div>
        {(d.conditions || []).map((c) => (
          <span key={c} className="chip">
            {c}
            <button onClick={() => op('character.condition.remove', { condition: c })}>×</button>
          </span>
        ))}
      </section>

      <section className="card optional">
        <h2>Inventario</h2>
        <div className="row">
          <input value={newItem} onChange={(e) => setNewItem(e.target.value)}
                 placeholder="Objeto nuevo" />
          <button disabled={!newItem.trim()} onClick={() => {
            op('character.inventory.add', { name: newItem.trim() })
            setNewItem('')
          }}>Añadir</button>
        </div>
        {(d.inventory || []).map((it) => (
          <div key={it.id} className="row">
            <span style={{ flex: 1 }}>{it.name} ×{it.quantity}</span>
            <button onClick={() => op('character.inventory.remove',
                                      { item_id: it.id, quantity: 1 })}>-</button>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>Dados</h2>
        <form onSubmit={doRoll} className="row">
          <input value={expr} onChange={(e) => setExpr(e.target.value)}
                 placeholder="2d6+3, 1d20adv, 4d6kh3" />
          <select value={rollType} onChange={(e) => setRollType(e.target.value)}>
            {['check', 'attack', 'save', 'damage'].map((t) => (
              <option key={t} value={t}>{t}</option>))}
          </select>
          <button type="submit">Tirar</button>
        </form>
        <ul className="log">{rollLog.map((l, i) => <li key={i}>{l}</li>)}</ul>
      </section>
    </main>
  )
}
