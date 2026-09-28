import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import { campaignSocket } from '../ws.js'
import { useT } from '../i18n.jsx'
import MapBoard from '../components/MapBoard.jsx'
import WikiText from '../components/WikiText.jsx'
import { currentUser } from '../session.js'

/** Vista de jugador: espacio de la campaña con pestañas —
    Resumen (actividad y personajes), Mundo (entidades reveladas)
    y Sesiones (preparación visible). */
export default function CampaignBoard() {
  const { id } = useParams()
  const { t, tf } = useT()
  const [entities, setEntities] = useState(null)
  const [chars, setChars] = useState([])
  const [code, setCode] = useState('')
  const [err, setErr] = useState(null)
  const [pend, setPend] = useState([])
  const [camp, setCamp] = useState(null)
  const [rolls, setRolls] = useState([])
  const [sessions, setSessions] = useState([])
  const [rels, setRels] = useState([])
  const [combatView, setCombatView] = useState(null) // vista jugador
  const [undoSave, setUndoSave] = useState(null)    // op_id deshacer
  const [campTab, setCampTab] = useState('resumen')
  const [presence, setPresence] = useState([]) // quién está en la sala
  const [ping, setPing] = useState(null)       // ping de mapa en vivo
  const me = currentUser() // para el botón "reclamar ficha"
  // el formulario de unirse solo ocupa espacio si todavía no estás dentro
  const [joined, setJoined] = useState(
    () => localStorage.getItem(`dnd-joined-${id}`) === '1')

  const load = () => {
    api.getCampaign(id)
      .then((cp) => {
        setCamp(cp)
        // "continuar campaña" del dashboard
        if (cp?.name) localStorage.setItem('dnd-last-campaign',
          JSON.stringify({ id, name: cp.name, at: Date.now() }))
      }).catch(() => {})
    api.listEntities(id, null, 'player')
      .then((r) => setEntities(r.entities))
      .catch((e) => setErr(e.message))
    api.listSessions(id)
      .then((r) => setSessions(r.sessions || []))
      .catch(() => {})
    api.listRelationships(id, null, 'player')
      .then((r) => setRels(r.relationships || []))
      .catch(() => {})
    api.listCharacters(id).then((r) => {
      setChars(r.characters)
      if (r.characters.length) {
        setJoined(true)
        localStorage.setItem(`dnd-joined-${id}`, '1')
        api.pendingRolls(id, r.characters.map((c) => c.id))
          .then((x) => setPend(x.pending || [])).catch(() => {})
      }
    }).catch(() => {})
    // combate activo en vista de jugador (sin PG exactos)
    api.listCombats(id, 'active')
      .then((r) => r.combats?.length
                  ? api.getCombat(r.combats[0].id, false) : null)
      .then((c) => setCombatView(c))
      .catch(() => setCombatView(null))
  }
  useEffect(load, [id])

  // en vivo: cuando el DM revela entidades o pide tiradas, el jugador
  // lo ve sin recargar
  useEffect(() => {
    // resync tras cada (re)conexión: snapshot de un solo viaje
    // (personajes + combates + últimos 50 eventos) y luego load()
    // para entidades/sesiones/relaciones
    const resync = () => api.campaignState(id).then((r) => {
      const cs = r.characters || []
      setChars(cs)
      if (cs.length) {
        setJoined(true)
        api.pendingRolls(id, cs.map((c) => c.id))
          .then((x) => setPend(x.pending || [])).catch(() => {})
      }
      const rolls = (r.events || [])
        .filter((e) => e.type === 'dice.roll.created' &&
                       !e.payload?.secret)
        .map((e) => e.payload)
      if (rolls.length) setRolls(rolls.slice(0, 10))
      if (r.presence) setPresence(r.presence)
    }).catch(() => {}).finally(load)
    const sock = campaignSocket(id, {
      onOpen: resync,
      onMessage: (msg) => {
        const ev = msg.event || msg
        if (ev?.type === 'dice.roll.requested' ||
            (ev?.type?.startsWith('campaign.') &&
             ev?.type !== 'campaign.presence' &&
             ev?.type !== 'campaign.map.ping') ||
            ev?.type?.startsWith('combat.')) load()
        // tiradas públicas (las secretas nunca llegan a este socket)
        if (ev?.type === 'dice.roll.created') {
          setRolls((l) => [ev.payload, ...l].slice(0, 10))
        }
        if (ev?.type === 'campaign.map.ping') {
          setPing({ ...ev.payload, k: Date.now() })
        }
        if (ev?.type === 'campaign.presence') {
          setPresence(ev.payload?.members || [])
        }
      },
    })
    return () => sock.close()
  }, [id])

  // deep-link desde el omnibox o un wiki-link: /campaign/:id#ent-<id>
  // abre la pestaña Mundo y centra la entidad (el CSS :target la
  // resalta sola)
  useEffect(() => {
    if (location.hash.startsWith('#ent-')) setCampTab('mundo')
  }, [id])
  useEffect(() => {
    if (campTab !== 'mundo' || !entities ||
        !location.hash.startsWith('#ent-')) return
    document.getElementById(location.hash.slice(1))
      ?.scrollIntoView({ block: 'center' })
  }, [campTab, entities])

  const join = async (e) => {
    e.preventDefault()
    try {
      await api.joinCampaign(code.trim())
      setCode(''); setErr(null)
      setJoined(true)
      localStorage.setItem(`dnd-joined-${id}`, '1')
      load()
    } catch (ex) { setErr(ex.message) }
  }

  const byKind = {}
  for (const e of entities || [])
    (byKind[e.kind] ||= []).push(e)

  const KIND_LABEL = {
    npc: 'camp.k.npc', location: 'camp.k.location', quest: 'camp.k.quest',
    faction: 'camp.k.faction', note: 'camp.k.note', event: 'camp.k.event',
    map: 'camp.k.map', shop: 'camp.k.shop', scene: 'camp.k.scene',
  }

  return (
    <main>
      <h1>{camp?.name || t('camp.title')}</h1>
      {camp && (
        <p className="muted">
          {camp.ruleset ? t(`ruleset.${camp.ruleset}`) : ''}
          {' · '}{t('ses.invite')}: <code>{camp.invite_code}</code></p>)}
      {/* presencia estilo Discord: quién está en la sala ahora */}
      {presence.length > 0 && (
        <p className="muted">
          🟢 {t('camp.online')}: {presence.map((m) =>
            m.count
              ? `+${m.count} ${t('camp.guests')}`
              : m.name +
                (['owner', 'dm', 'co_dm'].includes(m.role)
                  ? ` (${t('camp.roleDm')})` : '')
          ).join(' · ')}</p>)}
      {err && <p className="error">{err}</p>}

      {/* peticiones de tirada del DM para mis personajes */}
      {pend.map((p) => (
        <div key={p.character_id + p.at} className="notice" role="alert">
          <span><strong>{chars.find((c) => c.id === p.character_id)?.name}</strong>:
            {' '}{t('cb.rollTag')} {p.expression}{p.reason && ` — ${p.reason}`}</span>
          <Link to={`/character/${p.character_id}`}>
            <button>{t('cb.goSheet')}</button></Link>
        </div>))}

      {!joined && (
        <form onSubmit={join} className="row">
          <input value={code} onChange={(e) => setCode(e.target.value)}
                 placeholder={t('camp.invite')} />
          <button type="submit">{t('camp.join')}</button>
        </form>)}

      <nav className="tabs" role="tablist" aria-label={t('camp.title')}>
        {[['resumen', t('camp.tab.summary')],
          ['mundo', t('camp.tab.world')],
          ...(byKind.map?.length ? [['mapa', t('camp.tab.map')]] : []),
          ['sesiones', t('camp.tab.sessions')]].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={campTab === k}
                  onClick={() => setCampTab(k)}>{l}</button>))}
      </nav>

      {/* mapa táctico en vivo: solo lectura, niebla opaca y tokens
          bajo niebla ocultos; las entidades vienen del padre y se
          refrescan con los eventos campaign.* del WebSocket */}
      {campTab === 'mapa' && byKind.map?.length > 0 && (
        <section className="card">
          <MapBoard campaign={{ id }} readOnly viewer="player"
                    size={30} entities={byKind.map}
                    worldEntities={entities || []}
                    chars={chars} myUid={me?.user_id}
                    ping={ping} />
        </section>)}

      {campTab === 'resumen' && (<>
        {/* deshacer la salvación recién tirada (click erróneo) */}
        {undoSave && (
          <p className="notice" role="status">
            {t('sheet.opApplied')}
            <button onClick={async () => {
              await api.undoOp(undoSave).catch(() => {})
              setUndoSave(null)
              if (combatView)
                api.getCombat(combatView.id, false)
                  .then(setCombatView).catch(() => {})
            }}>{t('sheet.undoBtn')}</button>
            <button className="ghost" onClick={() => setUndoSave(null)}>✕</button>
          </p>)}
        {/* tracker de combate en vivo — vista jugador: orden real
            (los muertos/inconscientes se apartan como en Combat.ordered
            del backend), turno activo y estado aproximado (sin PG) */}
        {combatView?.combat?.combatants?.length > 0 && (() => {
          const OUT = new Set(['muerto', 'inconsciente', 'estable',
                               'dead', 'unconscious', 'stable'])
          const isOut = (cb) => (cb.conditions || [])
            .some((cn) => OUT.has(cn))
            // monstruo a 0 sin marca 'muerto': hp_state='caído' es lo
            // único que ve el jugador (los números van ocultos)
            || (cb.hp_state === 'caído' && cb.kind !== 'character')
          const alive = combatView.combat.combatants
            .filter((cb) => !isOut(cb))
            .sort((a, b) => b.initiative - a.initiative)
          const down = combatView.combat.combatants.filter(isOut)
          const turn = combatView.combat.turn_index %
                       Math.max(1, alive.length)
          const mine = new Set(chars.map((c) => c.id))
          const row = (cb, i) => (
            <div key={cb.id} className="row"
                 style={i === turn
                   ? { outline: '1px solid var(--accent)',
                       borderRadius: 6, padding: '2px 4px' }
                   : undefined}>
              <strong style={{ flex: 1 }}>
                {i === turn && '▶ '}{cb.name}</strong>
              <span className="muted" title={t('com.init')}>
                {cb.initiative}</span>
              {(cb.conditions || [])
                .filter((cn) => !OUT.has(cn)).map((cond) => (
                  <span key={cond} className="chip">{cond}</span>))}
              <span className="chip" title={t('cb.hpHint')}>
                {t(`cb.hp.${cb.hp_state || 'ileso'}`) !==
                 `cb.hp.${cb.hp_state || 'ileso'}`
                  ? t(`cb.hp.${cb.hp_state || 'ileso'}`)
                  : cb.hp_state}</span>
              {i === turn && cb.kind === 'character' &&
               mine.has(cb.ref_id) && (
                <Link to={`/character/${cb.ref_id}`}>
                  <button className="primary">
                    {t('cb.yourTurn')}</button></Link>)}
              {/* a 0 PG la salvación de muerte la tira el jugador
                  (única op de combate abierta a no-DM) */}
              {cb.kind === 'character' && mine.has(cb.ref_id) &&
               cb.hp_state === 'caído' && (
                <button onClick={() =>
                  api.applyOp(combatView, 'combatant.death_save_roll',
                              { combatant_id: cb.id }, 'combat')
                    .then((r) => {
                      if (r?.operation_id) setUndoSave(r.operation_id)
                      api.getCombat(combatView.id, false)
                        .then(setCombatView).catch(() => {})
                    })
                    .catch(() => {})}>
                  {t('com.deathRoll')}</button>)}
            </div>)
          return (
            <section className="card">
              <h2>{combatView.combat.name || t('dm.combat')}
                {' · '}{t('com.round')} {combatView.combat.round}</h2>
              {alive.map(row)}
              {down.length > 0 && (
                <div className="row muted"
                     style={{ marginTop: '.3rem', fontSize: '.85rem' }}>
                  {down.map((cb) => (
                    <span key={cb.id} className="chip">
                      ✝ {cb.name}</span>))}
                </div>)}
            </section>)
        })()}
        {rolls.length > 0 && (
          <section className="card">
            <h2>{t('camp.rolls')}</h2>
            {rolls.map((r, i) => (
              <div key={i} className="row">
                <span>{r.character}</span>
                <span className="muted">{r.roll_type} · {r.expression}</span>
                <strong>{r.total}</strong>
              </div>))}
          </section>)}

        {chars.length > 0 && (
          <section className="card">
            <h2>{t('camp.characters')}</h2>
            {/* party tracker: estado del grupo de un vistazo,
                como la página de campaña de Beyond o The 20 */}
            {chars.map((c) => {
              const pct = c.hp_max
                ? Math.round(100 * (c.hp_current ?? 0) / c.hp_max) : 0
              return (
                <div key={c.id} className="card" style={{ padding: '.7rem' }}>
                  <div className="row">
                    <Link to={`/character/${c.id}`} style={{ flex: 1 }}>
                      <strong>{c.name}</strong>
                      <span className="muted"> · {c.class_names?.join(' · ')}
                        {' '}{t('sheet.lvlShort')}{c.level}</span>
                    </Link>
                    {me && c.player_id === me.user_id && (
                      <span className="chip">{t('camp.yours')}</span>)}
                    {me && !c.player_id && (
                      <button className="ghost" style={{ minHeight: 26 }}
                              onClick={() =>
                                api.patchCharacter(c.id,
                                    { player_id: me.user_id })
                                  .then(load).catch(() => {})}>
                        {t('camp.claim')}</button>)}
                    {c.player_name && (
                      <span className="muted" style={{ fontSize: '.8rem' }}>
                        👤 {c.player_name}</span>)}
                  </div>
                  {c.hp_max != null && (
                    <div className="row">
                      <div className="hp-bar" style={{ flex: 1 }} role="img"
                           aria-label={tf('cb.hpAria',
                                          { name: c.name,
                                            cur: c.hp_current,
                                            max: c.hp_max })}>
                        <div style={{ width: `${pct}%` }} /></div>
                      <span className="muted" style={{ fontSize: '.8rem' }}>
                        {c.hp_current}/{c.hp_max}
                        {c.hp_temp > 0 ? ` (+${c.hp_temp})` : ''} PG</span>
                    </div>)}
                  {(c.conditions?.length > 0 || c.concentrating_on) && (
                    <div className="row" style={{ flexWrap: 'wrap' }}>
                      {(c.conditions || []).map((cn) => (
                        <span key={cn} className="chip">{cn}
                          {c.condition_stacks?.[cn] > 0 &&
                            ` ×${c.condition_stacks[cn]}`}</span>))}
                      {c.concentrating_on && (
                        <span className="chip">⭑ {c.concentrating_on}</span>)}
                    </div>)}
                </div>)
            })}
          </section>)}
      </>)}

      {campTab === 'mundo' && (<>
        {entities === null ? <p className="muted">{t('common.loading')}</p> : (
          Object.entries(byKind).map(([kind, list]) => (
            <section key={kind} className="card">
              <h2>{KIND_LABEL[kind] ? t(KIND_LABEL[kind]) : kind}</h2>
              {list.map((e) => (
                <div key={e.id} id={`ent-${e.id}`}>
                  <div className="row">
                    <span>{e.name}</span>
                    {e.data?.notes && (
                      <span className="muted">
                        <WikiText text={e.data.notes}
                                  entities={entities} /></span>)}
                  </div>
                  {e.data?.image_url && (
                    <img src={e.data.image_url} alt={e.name}
                         style={{ maxWidth: '100%', borderRadius: 8 }} />
                  )}
                  {/* relaciones públicas: "posada → dueña → tabernera" */}
                  {rels.filter((r) => r.from_id === e.id ||
                                      r.to_id === e.id).map((r) => (
                    <p key={r.id} className="muted"
                       style={{ fontSize: '.85rem', margin: '.1rem 0' }}>
                      🔗 {r.from_id === e.id
                        ? <>—<i>{r.type}</i>→ {entities.find(
                            (x) => x.id === r.to_id)?.name}</>
                        : <>{entities.find(
                            (x) => x.id === r.from_id)?.name} —<i>{
                            r.type}</i>→ {e.name}</>}
                    </p>))}
                </div>
              ))}
            </section>
          ))
        )}
        {entities && entities.length === 0 && (
          <p className="muted">{t('camp.nothingRevealed')}</p>)}
      </>)}

      {campTab === 'sesiones' && (
        <section className="card">
          <h2>{t('camp.tab.sessions')}</h2>
          {sessions.length === 0 && (
            <p className="muted">{t('camp.noSessions')}</p>)}
          {sessions.map((s) => (
            <div key={s.id}>
              <div className="row">
                <strong>#{s.number} {s.title}</strong>
                <span className="muted">· {s.status}</span>
              </div>
              <ul>
                {(s.scenes || [])
                  .filter((sc) => sc.visibility === 'public' ||
                                  sc.visibility == null)
                  .map((sc) => (
                  <li key={sc.id}>
                    {sc.data?.order}. {sc.name}
                    {sc.data?.notes && (
                      <span className="muted"> — <WikiText
                        text={sc.data.notes} entities={entities} /></span>)}
                  </li>))}
              </ul>
            </div>))}
        </section>)}
    </main>
  )
}
