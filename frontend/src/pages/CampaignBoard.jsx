import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import { currentUser } from '../session.js'
import { useT } from '../i18n.jsx'

/** Vista de jugador: solo entidades públicas/reveladas de la campaña. */
export default function CampaignBoard() {
  const { id } = useParams()
  const { t } = useT()
  const [entities, setEntities] = useState(null)
  const [chars, setChars] = useState([])
  const [code, setCode] = useState('')
  const [err, setErr] = useState(null)
  const [pend, setPend] = useState([])
  const [camp, setCamp] = useState(null)
  const [rolls, setRolls] = useState([])
  // el formulario de unirse solo ocupa espacio si todavía no estás dentro
  const [joined, setJoined] = useState(
    () => localStorage.getItem(`dnd-joined-${id}`) === '1')

  const load = () => {
    fetch(`/api/campaigns/${id}`).then((r) => r.ok ? r.json() : null)
      .then(setCamp).catch(() => {})
    api.listEntities(id, null, 'player')
      .then((r) => setEntities(r.entities))
      .catch((e) => setErr(e.message))
    api.listCharacters(id).then((r) => {
      setChars(r.characters)
      if (r.characters.length) {
        setJoined(true)
        localStorage.setItem(`dnd-joined-${id}`, '1')
        api.pendingRolls(id, r.characters.map((c) => c.id))
          .then((x) => setPend(x.pending || [])).catch(() => {})
      }
    }).catch(() => {})
  }
  useEffect(load, [id])

  // en vivo: cuando el DM revela entidades o pide tiradas, el jugador
  // lo ve sin recargar
  useEffect(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const uid = currentUser()?.user_id
    const ws = new WebSocket(
      `${proto}://${location.host}/ws/campaign/${id}` +
      (uid ? `?user_id=${uid}` : ''))
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      const ev = msg.event || msg
      if (ev?.type === 'dice.roll.requested' ||
          ev?.type?.startsWith('campaign.') ||
          ev?.type?.startsWith('combat.')) load()
      // tiradas públicas (las secretas nunca llegan a este socket)
      if (ev?.type === 'dice.roll.created') {
        setRolls((l) => [ev.payload, ...l].slice(0, 10))
      }
    }
    return () => ws.close()
  }, [id])

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
    npc: 'PNJ', location: 'Lugares', quest: 'Misiones',
    faction: 'Facciones', note: 'Notas', event: 'Eventos',
    map: 'Mapas', shop: 'Tiendas', scene: 'Escenas',
  }

  return (
    <main>
      <h1>{camp?.name || t('camp.title')}</h1>
      {camp && (
        <p className="muted">
          {camp.ruleset?.replace('dnd5e-', 'Reglas ') || ''}
          {' · '}Código: <code>{camp.invite_code}</code></p>)}
      {err && <p className="error">{err}</p>}

      {/* peticiones de tirada del DM para mis personajes */}
      {pend.map((p) => (
        <div key={p.character_id + p.at} className="notice" role="alert">
          <span><strong>{chars.find((c) => c.id === p.character_id)?.name}</strong>:
            {' '}tirada {p.expression}{p.reason && ` — ${p.reason}`}</span>
          <Link to={`/character/${p.character_id}`}>
            <button>Ir a la ficha</button></Link>
        </div>))}

      {!joined && (
        <form onSubmit={join} className="row">
          <input value={code} onChange={(e) => setCode(e.target.value)}
                 placeholder={t('camp.invite')} />
          <button type="submit">{t('camp.join')}</button>
        </form>)}

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
          {chars.map((c) => (
            <div key={c.id} className="row">
              <Link to={`/character/${c.id}`}>{c.name}</Link>
            </div>
          ))}
        </section>
      )}

      {entities === null ? <p className="muted">Cargando…</p> : (
        Object.entries(byKind).map(([kind, list]) => (
          <section key={kind} className="card">
            <h2>{KIND_LABEL[kind] || kind}</h2>
            {list.map((e) => (
              <div key={e.id}>
                <div className="row">
                  <span>{e.name}</span>
                  {e.data?.notes && <span className="muted">{e.data.notes}</span>}
                </div>
                {e.data?.image_url && (
                  <img src={e.data.image_url} alt={e.name}
                       style={{ maxWidth: '100%', borderRadius: 8 }} />
                )}
              </div>
            ))}
          </section>
        ))
      )}
      {entities && entities.length === 0 && (
        <p className="muted">{t('camp.nothingRevealed')}</p>
      )}
    </main>
  )
}
