import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
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
  const [dmTab, setDmTab] = useState('sesion')
  const [entities, setEntities] = useState([])
  const [entForm, setEntForm] = useState({ kind: 'npc', name: '', notes: '', monsters: '' })
  const [partyLevels, setPartyLevels] = useState('3,3,3,3')
  const [crs, setCrs] = useState('')
  const [difficulty, setDifficulty] = useState(null)
  const [rollReq, setRollReq] = useState({ character_id: '', expression: '1d20', reason: '' })
  const [dmgType, setDmgType] = useState('')
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

  // feed en vivo: tiradas de los jugadores en la sala
  useEffect(() => {
    if (!campaign) return undefined
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(
      `${proto}://${location.host}/ws/campaign/${campaign.id}`)
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      const ev = msg.event
      if (ev?.type === 'dice.roll.created') {
        setRollFeed((f) => [ev.payload, ...f].slice(0, 20))
        // si el DM está leyendo eventos antiguos no le movemos el
        // scroll — cuenta "N nuevos" hasta que vuelva arriba
        if ((feedRef.current?.scrollTop ?? 0) > 40)
          setNewRolls((n) => n + 1)
      }
    }
    return () => ws.close()
  }, [campaign?.id])

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
    const r = await api.search(query, 'monster')
    setMonsters(r.results)
  }

  const ordered = combat
    ? [...combat.combat.combatants].sort((a, b) => b.initiative - a.initiative)
    : []
  const activeIdx = combat ? combat.combat.turn_index % Math.max(1, ordered.length) : 0
  const sel = ordered.find((c) => c.id === selId)
    || ordered[activeIdx] || null   // por defecto: el del turno

  return (
    <main className="dm">
      <h1>Mesa del DM</h1>
      <div className="dm-shell">
      <aside className="dm-side">
        <nav role="tablist" aria-label="Mesa DM">
          {[['sesion', 'Sesión'], ['combate', 'Combate'],
            ['campana', 'Campaña']].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={dmTab === k}
                    onClick={() => setDmTab(k)}>{label}</button>))}
        </nav>
        {campaign && (
          <p className="muted" style={{ fontSize: '.8rem' }}>
            {campaign.name}
            {combat && <> · ronda {combat.combat.round}</>}
            {rollFeed.length > 0 && <> · {rollFeed.length} tiradas</>}
          </p>)}
      </aside>
      <div className="dm-main">
      {err && <p className="error">{err}</p>}

      <section className="card" hidden={dmTab !== 'sesion'}>
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
        <section className="card" hidden={dmTab !== 'sesion'}>
          <h2>Tiradas de la mesa</h2>
          <div className="row" role="group" aria-label="Filtrar tiradas">
            {['todas', 'check', 'save', 'attack', 'damage'].map((f) => (
              <button key={f} className="ghost"
                      aria-pressed={feedFilter === f}
                      style={{ borderColor: feedFilter === f
                        ? 'var(--accent)' : undefined }}
                      onClick={() => setFeedFilter(f)}>{f}</button>))}
          </div>
          {newRolls > 0 && (
            <button className="ghost" role="status"
                    onClick={() => {
                      feedRef.current?.scrollTo({ top: 0 })
                      setNewRolls(0)
                    }}>{newRolls} evento{newRolls > 1 ? 's' : ''} nuevo{newRolls > 1 ? 's' : ''} ↑</button>)}
          <div ref={feedRef}
               style={{ maxHeight: '18rem', overflowY: 'auto' }}
               onScroll={(e) => {
                 if (e.target.scrollTop <= 40) setNewRolls(0)
               }}>
          {rollFeed.filter((r) => feedFilter === 'todas' ||
                r.roll_type === feedFilter).map((r, i) => (
            <div key={i} className="row">
              <span>{r.secret ? '🔒 ' : ''}{r.character}</span>
              <span className="muted">
                {r.secret ? 'privada · ' : ''}
                {r.roll_type} · {r.expression}</span>
              <strong>{r.total}</strong>
            </div>
          ))}
          </div>
        </section>
      )}

      {campaign && (
        <section className="card" hidden={dmTab !== 'campana'}>
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
        <section className="card" hidden={dmTab !== 'combate'}>
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
        <section className="card" hidden={dmTab !== 'sesion'}>
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
        <section className="card" hidden={dmTab !== 'sesion'}>
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
        <section className="card" hidden={dmTab !== 'combate'}>
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
        <div className="dm-combat-grid">
          <section className="card" hidden={dmTab !== 'combate'}>
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
              <button className="ghost" onClick={async () =>
                setDifficulty(await api.combatDifficulty(combat.id))
              }>Dificultad</button>
              <button className="ghost" aria-expanded={!!areaDmg}
                      onClick={() => setAreaDmg(areaDmg ? null : {})}>
                Daño en área</button>
              <button className="dmg" onClick={() => cop('combat.end', {})}>Terminar</button>
            </div>
            {areaDmg && (
              <div className="card" role="dialog"
                   aria-label="Aplicar daño a varios objetivos"
                   style={{ background: 'var(--card-raised)' }}>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  {ordered.map((c) => (
                    <label key={c.id} className="chip"
                           style={{ cursor: 'pointer' }}>
                      <input type="checkbox"
                             checked={!!areaDmg[c.id]}
                             onChange={(e) => setAreaDmg({
                               ...areaDmg, [c.id]: e.target.checked })} />
                      {' '}{c.name}</label>))}
                </div>
                <div className="row">
                  <input type="number" min="1" value={areaAmt}
                         onChange={(e) => setAreaAmt(+e.target.value)}
                         aria-label="Cantidad" />
                  <select value={areaType}
                          onChange={(e) => setAreaType(e.target.value)}
                          aria-label="Tipo de daño">
                    <option value="">sin tipo</option>
                    {['fire', 'cold', 'lightning', 'poison', 'acid',
                      'necrotic', 'radiant', 'psychic', 'thunder',
                      'force', 'bludgeoning', 'piercing',
                      'slashing'].map((t) =>
                      <option key={t} value={t}>{t}</option>)}
                  </select>
                  <button className="dmg" onClick={async () => {
                    const targets = ordered.filter((c) => areaDmg[c.id])
                    let ver = combat.version
                    const res = []
                    for (const c of targets) {
                      const r = await api.applyOp(
                        { id: combat.id, version: ver },
                        'combatant.damage',
                        { combatant_id: c.id, amount: areaAmt,
                          damage_type: areaType }, 'combat')
                      ver = r.version ?? ver + 1
                      const ev = (r.events || []).find(
                        (e) => e.type === 'character.hp.changed')
                      res.push(`${c.name}: ${areaAmt} → ${
                        ev?.payload?.amount ?? areaAmt}${
                        ev?.payload?.note ? ` (${ev.payload.note})` : ''}`)
                    }
                    setAreaResults(res)
                    refresh(combat.id)
                  }}>Aplicar</button>
                </div>
                {(areaResults || []).length > 0 && (
                  <ul style={{ margin: '.4rem 0 0' }}>
                    {areaResults.map((r, i) => <li key={i}>{r}</li>)}
                  </ul>)}
              </div>)}
            {difficulty && (
              <p>
                <span className="chip">{difficulty.rating}</span>{' '}
                <span className="muted">
                  {difficulty.raw_xp} XP brutos · {difficulty.adjusted_xp} ajustados
                  {difficulty.warnings.map((w) => ` · ${w}`)}
                </span>
              </p>)}
          </section>

          <section className="card" hidden={dmTab !== 'combate'}>
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

          <section className="card" hidden={dmTab !== 'combate'}>
            <h2>Iniciativa</h2>
            <div className="row">
              <select value={dmgType}
                      onChange={(e) => setDmgType(e.target.value)}
                      style={{ maxWidth: 160 }}
                      aria-label="Tipo de daño">
                <option value="">daño sin tipo</option>
                {['fire', 'cold', 'lightning', 'poison', 'acid',
                  'necrotic', 'radiant', 'psychic', 'thunder',
                  'force', 'bludgeoning', 'piercing', 'slashing']
                  .map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <span className="muted">
                se aplica resistencia/inmunidad/vulnerabilidad del stat block
              </span>
            </div>
            {ordered.map((c, i) => {
              const isTurn = i === activeIdx &&
                combat.combat.status === 'active'
              return (
              <div key={c.id}
                   className={`row combatant${isTurn ? ' turn' : ''}`}
                   aria-current={isTurn ? 'true' : undefined}>
                <span className="init">{c.initiative}</span>
                <span className="cname"
                      role="button" tabIndex={0}
                      style={{ cursor: 'pointer' }}
                      onClick={() => setSelId(c.id)}
                      onKeyDown={(e) => e.key === 'Enter' &&
                        setSelId(c.id)}>
                  {isTurn && <span className="turn-tag">turno </span>}
                  {c.name}
                  {c.conditions.map((x) => <em key={x} className="chip">{x}</em>)}
                </span>
                <span className="hp">{c.hp_current}/{c.hp_max}</span>
                <input type="number" style={{ maxWidth: 70 }}
                       value={dmg[c.id] || ''}
                       onChange={(e) => setDmg({ ...dmg, [c.id]: +e.target.value })} />
                <button className="dmg" disabled={!dmg[c.id]}
                        onClick={() => cop('combatant.damage', {
                          combatant_id: c.id, amount: dmg[c.id],
                          damage_type: dmgType || undefined })}>-</button>
                <button className="heal" disabled={!dmg[c.id]}
                        onClick={() => cop('combatant.heal', { combatant_id: c.id, amount: dmg[c.id] })}>+</button>
                <button onClick={() => cop('combatant.remove', { combatant_id: c.id })}>×</button>
              </div>
            )})}
          </section>

          {/* Panel contextual: click en un combatiente → sus acciones
             y stat block (ataque/daño/CD/recharge parseados) */}
          {sel && (sel.stat_block?.actions?.length > 0) && (
            <section className="card" hidden={dmTab !== 'combate'}
                     aria-label={`Acciones de ${sel.name}`}>
              <h2>{sel.name}
                <span className="muted" style={{ fontSize: '.8em' }}>
                  {' '}CA {sel.stat_block.ac} · CR {sel.stat_block.cr}
                  {sel.stat_block.spellcasting?.spells?.length > 0 &&
                    ` · ${sel.stat_block.spellcasting.spells.length} conjuros`}
                </span>
                <button className="ghost" style={{ float: 'right' }}
                        onClick={() => setSelId(null)}>×</button>
              </h2>
              {sel.stat_block.actions.map((a, ai) => (
                <div key={ai} className="row">
                  <button onClick={() =>
                    cop('combatant.action.roll',
                        { combatant_id: sel.id, action_index: ai })
                  }>{a.name}</button>
                  <span className="muted" style={{ fontSize: '0.8em' }}>
                    {a.category !== 'action' && `[${a.category}] `}
                    {a.text?.slice(0, 110)}{a.text?.length > 110 && '…'}
                  </span>
                </div>))}
            </section>)}

          {/* Vista DM del personaje: CA/PG/condiciones + acciones de
              mesa sin abrir la ficha completa */}
          {sel && sel.kind === 'character' && (
            <section className="card" hidden={dmTab !== 'combate'}
                     aria-label={`Resumen DM de ${sel.name}`}>
              <h2>{sel.name}
                <span className="muted" style={{ fontSize: '.8em' }}>
                  {' '}jugador · CA {sel.ac}</span>
                <button className="ghost" style={{ float: 'right' }}
                        onClick={() => setSelId(null)}>×</button>
              </h2>
              <p>
                PG {sel.hp_current}/{sel.hp_max}
                {sel.hp_temp > 0 && ` (+${sel.hp_temp} temp)`}
              </p>
              {sel.conditions.length > 0 && (
                <p className="muted">
                  Condiciones: {sel.conditions.join(' · ')}</p>)}
              {(sel.death_saves?.success > 0 ||
                sel.death_saves?.fail > 0) && (
                <p className="muted">
                  Muerte: ✓{sel.death_saves.success}{' '}
                  ✗{sel.death_saves.fail}</p>)}
              <div className="row">
                {sel.ref_id && (
                  <Link to={`/character/${sel.ref_id}`}>
                    <button className="ghost">Ficha →</button></Link>)}
                {sel.ref_id && (
                  <button className="ghost" onClick={() => {
                    setRollReq({ character_id: sel.ref_id,
                                 expression: '1d20', reason: '' })
                    setDmTab('sesion')
                  }}>Solicitar tirada</button>)}
              </div>
            </section>)}
        </div>
        </>
      )}
      </div>{/* dm-main */}
      </div>{/* dm-shell */}
    </main>
  )
}
