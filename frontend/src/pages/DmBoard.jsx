import { useEffect, useState } from 'react'
import { api } from '../api.js'
import MapBoard from '../components/MapBoard.jsx'

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
  const [entForm, setEntForm] = useState({ kind: 'npc', name: '', notes: '', monsters: '' })
  const [partyLevels, setPartyLevels] = useState('3,3,3,3')
  const [crs, setCrs] = useState('')
  const [difficulty, setDifficulty] = useState(null)
  const [rollReq, setRollReq] = useState({ character_id: '', expression: '1d20', reason: '' })
  const [sessions, setSessions] = useState([])
  const [sessTitle, setSessTitle] = useState('')
  const [timeline, setTimeline] = useState(null)
  const [rollFeed, setRollFeed] = useState([])
  const [eventFeed, setEventFeed] = useState(null)

  // feed en vivo: tiradas de los jugadores en la sala
  useEffect(() => {
    if (!campaign) return undefined
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(
      `${proto}://${location.host}/ws/campaign/${campaign.id}`)
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      const ev = msg.event
      if (ev?.type === 'dice.roll.created')
        setRollFeed((f) => [ev.payload, ...f].slice(0, 20))
    }
    return () => ws.close()
  }, [campaign?.id])

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
          <>
            <p>{campName || 'Campaña'} — código invitación:
              <strong> {campaign.invite_code}</strong></p>
            <div className="row">
              <button className="ghost" onClick={async () => {
                const ex = await api.exportCampaign(campaign.id)
                const blob = new Blob([JSON.stringify(ex, null, 2)],
                                      { type: 'application/json' })
                const a = document.createElement('a')
                a.href = URL.createObjectURL(blob)
                a.download = 'campania.json'
                a.click()
              }}>Exportar backup</button>
              <button className="ghost" onClick={async () =>
                setEventFeed(eventFeed ? null
                  : (await api.campaignEvents(campaign.id)).events)
              }>Auditoría</button>
            </div>
            {eventFeed && eventFeed.map((e) => (
              <div key={e.event_id} className="row">
                <span className="muted">{e.occurred_at.slice(11, 19)}</span>
                <span>{e.type}</span>
              </div>
            ))}
          </>
        )}
      </section>

      {campaign && rollFeed.length > 0 && (
        <section className="card">
          <h2>Tiradas de la mesa</h2>
          {rollFeed.map((r, i) => (
            <div key={i} className="row">
              <span>{r.character}</span>
              <span className="muted">{r.roll_type} · {r.expression}</span>
              <strong>{r.total}</strong>
            </div>
          ))}
        </section>
      )}

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
            {entForm.kind === 'scene' && (
              <input value={entForm.monsters}
                     placeholder="monstruos: goblin, orc"
                     onChange={(e) => setEntForm({ ...entForm, monsters: e.target.value })} />
            )}
            <button disabled={!entForm.name} onClick={async () => {
              const data = { notes: entForm.notes }
              if (entForm.kind === 'scene' && entForm.monsters.trim()) {
                // resuelve nombres a ids de contenido (primer resultado)
                const ids = []
                for (const term of entForm.monsters.split(',')) {
                  const s = await api.search(term.trim(), 'monster')
                  if (s.results[0]) ids.push(s.results[0].id)
                }
                data.monsters = ids
              }
              await api.createEntity(campaign.id, {
                kind: entForm.kind, name: entForm.name,
                data, visibility: 'dm',
              })
              setEntForm({ ...entForm, name: '', notes: '', monsters: '' })
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
              <button className="ghost" aria-label={`Borrar ${e.name}`}
                      onClick={async () => {
                if (!confirm(`¿Borrar "${e.name}"?`)) return
                await fetch(
                  `/api/campaigns/${campaign.id}/entities/${e.id}`,
                  { method: 'DELETE' })
                api.listEntities(campaign.id).then((r) => setEntities(r.entities))
              }}>×</button>
              {e.kind === 'scene' && (e.data.monsters || []).length > 0 && (
                <button style={{ minHeight: 32 }} onClick={async () => {
                  const r = await api.startScene(campaign.id, e.id)
                  refresh(r.combat_id)
                }}>▶ combate</button>
              )}
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
              <div className="row">
                <strong>#{s.number} {s.title}</strong>
                <span className="muted">· {s.status}</span>
                {s.status !== 'done' && (
                  <button style={{ minHeight: 32 }} onClick={async () => {
                    await fetch(
                      `/api/campaigns/${campaign.id}/sessions/${s.id}`,
                      { method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          status: s.status === 'prep' ? 'active' : 'done' }) })
                    api.listSessions(campaign.id).then((r) => setSessions(r.sessions))
                  }}>{s.status === 'prep' ? 'Iniciar' : 'Cerrar'}</button>
                )}
              </div>
              <ul>
                {s.scenes.map((sc) => (
                  <li key={sc.id} className="row">
                    {sc.data.order}. {sc.name}
                    {(sc.data.monsters || []).length > 0 && (
                      <button style={{ minHeight: 32 }}
                              onClick={async () => {
                        const r = await api.startScene(campaign.id, sc.id)
                        refresh(r.combat_id)
                      }}>▶ combate</button>
                    )}
                  </li>
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

      {campaign && <MapBoard campaign={campaign} />}

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
              <button onClick={async () => {
                await fetch(`/api/combat/${combat.id}/add-party`,
                            { method: 'POST' })
                refresh(combat.id)
              }}>+ Grupo</button>
              <button onClick={async () => {
                for (const c of combat.combat.combatants)
                  await api.applyOp({ id: combat.id, version: combat.version },
                                    'combatant.initiative.roll',
                                    { combatant_id: c.id }, 'combat')
                refresh(combat.id)
              }}>Tirar inits</button>
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
