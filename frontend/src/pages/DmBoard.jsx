import { useState } from 'react'
import { api } from '../api.js'

export default function DmBoard() {
  const [campaign, setCampaign] = useState(null)
  const [campName, setCampName] = useState('')
  const [combat, setCombat] = useState(null)   // {id, version, combat}
  const [combatName, setCombatName] = useState('')
  const [query, setQuery] = useState('')
  const [monsters, setMonsters] = useState([])
  const [manual, setManual] = useState({ name: '', hp_max: 10, initiative: 10 })
  const [dmg, setDmg] = useState({})
  const [err, setErr] = useState(null)

  const refresh = (id, version) =>
    api.getCombat(id).then((r) => setCombat(r)).catch((e) => setErr(e.message))

  const cop = async (type, payload) => {
    try {
      await api.applyOp({ id: combat.id, version: combat.version },
                        type, payload, 'combat')
      refresh(combat.id)
    } catch (e) { setErr(e.message); refresh(combat.id) }
  }

  const searchMonsters = async (e) => {
    e.preventDefault()
    const r = await api.search(query, 'monster')
    setMonsters(r.results)
  }

  const ordered = combat
    ? [...combat.combat.combatants].sort((a, b) => b.initiative - a.initiative)
    : []
  const activeIdx = combat ? combat.combat.turn_index % Math.max(1, ordered.length) : 0

  return (
    <main>
      <h1>Mesa del DM</h1>
      {err && <p className="error">{err}</p>}

      <section className="card">
        <h2>Campaña</h2>
        {!campaign ? (
          <form className="row" onSubmit={async (e) => {
            e.preventDefault()
            const r = await api.createCampaign(campName || 'Campaña')
            setCampaign(r)
          }}>
            <input value={campName} onChange={(e) => setCampName(e.target.value)}
                   placeholder="Nombre de campaña" />
            <button type="submit">Crear</button>
          </form>
        ) : (
          <p>{campName || 'Campaña'} — código invitación:
            <strong> {campaign.invite_code}</strong></p>
        )}
      </section>

      {campaign && !combat && (
        <section className="card">
          <h2>Nuevo combate</h2>
          <form className="row" onSubmit={async (e) => {
            e.preventDefault()
            const r = await api.createCombat(combatName || 'Encuentro', campaign.id)
            refresh(r.id)
          }}>
            <input value={combatName} onChange={(e) => setCombatName(e.target.value)}
                   placeholder="Nombre del encuentro" />
            <button type="submit">Empezar</button>
          </form>
        </section>
      )}

      {combat && (
        <>
          <section className="card">
            <h2>{combat.combat.name} — ronda {combat.combat.round}</h2>
            <div className="row">
              <button onClick={() => cop('combat.next_turn', {})}>Siguiente turno</button>
              <button onClick={() => cop('combat.prev_turn', {})}>Anterior</button>
              <button className="dmg" onClick={() => cop('combat.end', {})}>Terminar</button>
            </div>
          </section>

          <section className="card">
            <h2>Añadir combatiente</h2>
            <form onSubmit={searchMonsters} className="row">
              <input value={query} onChange={(e) => setQuery(e.target.value)}
                     placeholder="Buscar monstruo (goblin, orc…)" />
              <button type="submit">Buscar</button>
            </form>
            {monsters.map((m) => (
              <div key={m.id} className="row">
                <span>{m.name}</span>
                <button onClick={() =>
                  cop('combatant.add', { content_entity_id: m.id })}>+</button>
              </div>
            ))}
            <div className="row">
              <input value={manual.name} placeholder="NPC manual"
                     onChange={(e) => setManual({ ...manual, name: e.target.value })} />
              <input type="number" style={{ maxWidth: 70 }} value={manual.hp_max}
                     onChange={(e) => setManual({ ...manual, hp_max: +e.target.value })} />
              <input type="number" style={{ maxWidth: 70 }} value={manual.initiative}
                     onChange={(e) => setManual({ ...manual, initiative: +e.target.value })} />
              <button disabled={!manual.name}
                      onClick={() => cop('combatant.add', {
                        name: manual.name, hp_max: manual.hp_max,
                        initiative: manual.initiative, kind: 'npc',
                      })}>Añadir</button>
            </div>
          </section>

          <section className="card">
            <h2>Iniciativa</h2>
            {ordered.map((c, i) => (
              <div key={c.id} className={`row combatant ${i === activeIdx && combat.combat.status === 'active' ? 'active' : ''}`}>
                <span className="init">{c.initiative}</span>
                <span className="cname">{c.name}
                  {c.conditions.map((x) => <em key={x} className="chip">{x}</em>)}
                </span>
                <span className="hp">{c.hp_current}/{c.hp_max}</span>
                <input type="number" style={{ maxWidth: 70 }}
                       value={dmg[c.id] || ''}
                       onChange={(e) => setDmg({ ...dmg, [c.id]: +e.target.value })} />
                <button className="dmg" disabled={!dmg[c.id]}
                        onClick={() => cop('combatant.damage', { combatant_id: c.id, amount: dmg[c.id] })}>-</button>
                <button className="heal" disabled={!dmg[c.id]}
                        onClick={() => cop('combatant.heal', { combatant_id: c.id, amount: dmg[c.id] })}>+</button>
                <button onClick={() => cop('combatant.remove', { combatant_id: c.id })}>×</button>
              </div>
            ))}
          </section>
        </>
      )}
    </main>
  )
}
