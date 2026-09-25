import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

/** Lista de campañas del usuario — hub entre fichas y mesa. */
export default function CampaignList() {
  const [camps, setCamps] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.listCampaigns()
      .then((r) => setCamps(r.campaigns))
      .catch((e) => setErr(e.message))
  }, [])

  const ROLE = { owner: 'DM', dm: 'DM', player: 'Jugador' }
  return (
    <main>
      <h1>Campañas</h1>
      {err && <p className="error">{err}</p>}
      {camps === null && <p className="muted">Cargando…</p>}
      {camps && camps.length === 0 && (
        <div className="card empty">
          <p><strong>Sin campañas todavía</strong></p>
          <p>Crea una desde la Mesa DM o únete con un código de
             invitación.</p>
          <Link to="/dm"><button className="primary">Mesa DM</button></Link>
        </div>)}
      {(camps || []).map((c) => (
        <Link key={c.id} to={`/campaign/${c.id}`}
              style={{ textDecoration: 'none', color: 'inherit' }}>
          <div className="card" style={{ cursor: 'pointer' }}>
            <div className="row">
              <strong style={{ flex: 1, fontSize: '1.1rem' }}>
                {c.name}</strong>
              <span className="chip">{ROLE[c.role] || c.role}</span>
            </div>
            <p className="muted" style={{ margin: 0 }}>
              {c.ruleset.replace('dnd5e-', 'Reglas ')}</p>
          </div>
        </Link>))}
    </main>
  )
}
