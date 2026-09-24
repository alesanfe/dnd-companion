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
  const [entities, setEntities] = useState([])
  const [entForm, setEntForm] = useState({ kind: 'npc', name: '', notes: '' })
  const [partyLevels, setPartyLevels] = useState('3,3,3,3')
  const [crs, setCrs] = useState('')
  const [difficulty, setDifficulty] = useState(null)
  const [rollReq, setRollReq] = useState({ character_id: '', expression: '1d20', reason: '' })
  const [sessions, setSessions] = useState([])
  const [sessTitle, setSessTitle] = useState('')
  const [timeline, setTimeline] = useState(null)

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

      {campaign && (
        <section className="card">
          <h2>Entidades de campaña</h2>
          <div className="row">
            <select value={entForm.kind}
                    onChange={(e) => setEntForm({ ...entForm, kind: e.target.value })}>
              <option value="npc">NPC</option>
              <option value="location">Lugar</option>
              <option value="quest">Misión</option>
              <option value="faction">Facción</option>
              <option value="scene">Escena</option>
              <option value="note">Nota</option>
            </select>
            <input value={entForm.name} placeholder="Nombre"
                   onChange={(e) => setEntForm({ ...entForm, name: e.target.value })} />
            <button disabled={!entForm.name} onClick={async () => {
              await api.createEntity(campaign.id, {
                kind: entForm.kind, name: entForm.name,
                data: { notes: entForm.notes }, visibility: 'dm',
              })
              setEntForm({ ...entForm, name: '', notes: '' })
              api.listEntities(campaign.id).then((r) => setEntities(r.entities))
            }}>Crear (privado)</button>
          </div>
          <button onClick={() =>
            api.listEntities(campaign.id).then((r) => setEntities(r.entities))
          }>Cargar lista</button>
          {entities.map((e) => (
            <div key={e.id} className="row">
              <span className="muted">{e.kind}</span>
              <span style={{ flex: 1 }}>{e.name}</span>
              {e.visibility === 'dm' && (
                <button onClick={async () => {
                  await api.revealEntity(campaign.id, e.id)
                  api.listEntities(campaign.id).then((r) => setEntities(r.entities))
                }}>Revelar</button>
              )}
            </div>
          ))}
        </section>
      )}

      {campaign && (
        <section className="card">
          <h2>Dificultad de encuentro</h2>
          <div className="row">
            <input value={partyLevels} placeholder="niveles: 3,3,4"
                   onChange={(e) => setPartyLevels(e.target.value)} />
            <input value={crs} placeholder="CRs: 1/4,1/2,2"
                   onChange={(e) => setCrs(e.target.value)} />
            <button onClick={async () => {
              const lv = partyLevels.split(',').map((x) => +x.trim()).filter(Boolean)
              const cr = crs.split(',').map((x) => x.trim()).filter(Boolean)
              setDifficulty(await api.encounterDifficulty(lv, cr))
            }}>Calcular</button>
          </div>
          {difficulty && (
            <p>
              <strong>{difficulty.rating.toUpperCase()}</strong>
              {' '}· XP ajustado: {difficulty.adjusted_xp} (base {difficulty.raw_xp})
              {difficulty.warnings.map((w) => <em key={w} className="error"><br />{w}</em>)}
            </p>
          )}
        </section>
      )}

      {campaign && (
        <section className="card">
          <h2>Sesiones y preparación</h2>
          <div className="row">
            <input value={sessTitle} placeholder="Título de sesión"
                   onChange={(e) => setSessTitle(e.target.value)} />
            <button disabled={!sessTitle} onClick={async () => {
              await fetch(`/api/campaigns/${campaign.id}/sessions`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: sessTitle,
                  number: sessions.length + 1 }),
              })
              setSessTitle('')
              const r = await fetch(`/api/campaigns/${campaign.id}/sessions`).then((x) => x.json())
              setSessions(r.sessions)
            }}>Crear</button>
            <button onClick={async () => {
              const r = await fetch(`/api/campaigns/${campaign.id}/timeline`).then((x) => x.json())
              setTimeline(timeline ? null : r.timeline)
            }}>Cronología</button>
          </div>
          {sessions.map((s) => (
            <div key={s.id}>
              <strong>#{s.number} {s.title}</strong>
              <span className="muted"> · {s.status}</span>
              <ul>
                {s.scenes.map((sc) => (
                  <li key={sc.id}>{sc.data.order}. {sc.name}</li>
                ))}
              </ul>
            </div>
          ))}
          {timeline && timeline.map((t) => (
            <div key={t.id} className="row">
              <span className="muted">{t.world_date || '—'}</span>
              <span>{t.name}</span>
            </div>
          ))}
        </section>
      )}

      {campaign && (
        <section className="card">
          <h2>Pedir tirada a un jugador</h2>
          <div className="row">
            <input value={rollReq.character_id} placeholder="character_id"
                   onChange={(e) => setRollReq({ ...rollReq, character_id: e.target.value })} />
            <input value={rollReq.expression} style={{ maxWidth: 90 }}
                   onChange={(e) => setRollReq({ ...rollReq, expression: e.target.value })} />
            <input value={rollReq.reason} placeholder="motivo"
                   onChange={(e) => setRollReq({ ...rollReq, reason: e.target.value })} />
            <button disabled={!rollReq.character_id}
                    onClick={() => api.requestRoll(campaign.id, rollReq)}>
              Pedir
            </button>
          </div>
        </section>
      )}

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
