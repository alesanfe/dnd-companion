import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'

/** Vista de jugador: solo entidades públicas/reveladas de la campaña. */
export default function CampaignBoard() {
  const { id } = useParams()
  const [entities, setEntities] = useState(null)
  const [chars, setChars] = useState([])
  const [code, setCode] = useState('')
  const [err, setErr] = useState(null)

  const load = () => {
    api.listEntities(id, null, 'player')
      .then((r) => setEntities(r.entities))
      .catch((e) => setErr(e.message))
    api.listCharacters(id).then((r) => setChars(r.characters))
      .catch(() => {})
  }
  useEffect(load, [id])

  const join = async (e) => {
    e.preventDefault()
    try {
      await api.joinCampaign(code.trim())
      setCode('')
      setErr(null)
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
      <h1>Campaña</h1>
      {err && <p className="error">{err}</p>}

      <form onSubmit={join} className="row">
        <input value={code} onChange={(e) => setCode(e.target.value)}
               placeholder="Código de invitación" />
        <button type="submit">Unirse</button>
      </form>

      {chars.length > 0 && (
        <section className="card">
          <h2>Personajes de la campaña</h2>
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
        <p className="muted">El DM aún no ha revelado nada.</p>
      )}
    </main>
  )
}
