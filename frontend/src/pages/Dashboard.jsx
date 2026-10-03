import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { currentUser, loadJSON } from '../session.js'
import { useT, opLabel } from '../i18n.jsx'
import { trackTask } from '../metrics.js'

/** Inicio: responde "¿qué quieres hacer ahora?" — continuar donde
    lo dejaste, acciones rápidas, actividad reciente y favoritos. */
export default function Dashboard() {
  const { t, lang } = useT()
  const user = currentUser()
  const [chars, setChars] = useState(null)
  const [camps, setCamps] = useState(null)
  const [activity, setActivity] = useState([])
  const [expr, setExpr] = useState('1d20')
  const [rollResult, setRollResult] = useState(null)

  const lastChar = loadJSON('dnd-last-char')
  const lastCamp = loadJSON('dnd-last-campaign')
  const favs = loadJSON('dnd-favs', [])

  useEffect(() => {
    api.listCharacters()
      .then((r) => setChars(r.characters)).catch(() => setChars([]))
    api.listCampaigns()
      .then((r) => setCamps(r.campaigns)).catch(() => setCamps([]))
  }, [])

  // actividad reciente: últimas operaciones de la ficha más reciente
  useEffect(() => {
    if (!lastChar?.id) return
    api.opHistory(lastChar.id)
      .then((r) => setActivity((r.operations || []).slice(0, 6)))
      .catch(() => {})
  }, [])

  const hour = new Date().getHours()
  const greet = lang === 'en'
    ? (hour < 12 ? 'Good morning' : hour < 20 ? 'Good afternoon'
                                              : 'Good evening')
    : (hour < 12 ? 'Buenos días' : hour < 20 ? 'Buenas tardes'
                                            : 'Buenas noches')

  const quickRoll = async (e) => {
    e.preventDefault()
    if (!expr.trim()) return
    try {
      const r = await api.roll(expr.trim())
      setRollResult(`${r.expression} → ${r.rolls?.join('+') || ''} = ${r.total}`)
      trackTask('roll', true)
    } catch (e2) { setRollResult(`⚠ ${e2.message}`); trackTask('roll', false) }
  }

  const relTime = (ts) => {
    const mins = Math.round((Date.now() - new Date(ts)) / 60000)
    if (mins < 1) return t('dash.now')
    if (mins < 60) return `${mins} min`
    if (mins < 1440) return `${Math.round(mins / 60)} h`
    return new Date(ts).toLocaleDateString()
  }

  return (
    <main>
      <section className="hero card">
        <h1 style={{ marginTop: 0 }}>
          {greet}{user ? `, ${user.username}` : ''}</h1>
        <div className="dash-continue">
          {lastChar && (
            <Link to={`/character/${lastChar.id}`}
                  className="card dash-card">
              <span className="muted">🧝 {t('dash.continueChar')}</span>
              <strong style={{ fontSize: '1.15rem' }}>{lastChar.name}</strong>
              <span className="muted">{relTime(lastChar.at)}</span>
            </Link>)}
          {lastCamp && (
            <Link to={`/campaign/${lastCamp.id}`}
                  className="card dash-card">
              <span className="muted">🗺 {t('dash.continueCamp')}</span>
              <strong style={{ fontSize: '1.15rem' }}>{lastCamp.name}</strong>
              <span className="muted">{relTime(lastCamp.at)}</span>
            </Link>)}
          {!lastChar && !lastCamp && (
            <div className="empty" style={{ textAlign: 'left' }}>
              <p style={{ fontSize: '1.05rem', marginTop: 0 }}>
                🎲 <strong>{t('dash.firstTime')}</strong></p>
              <div className="row">
                <Link to="/new"><button className="primary">
                  🧝 {t('create.character')}</button></Link>
                <Link to="/dm"><button className="ghost">
                  🏰 {t('create.campaign')}</button></Link>
              </div>
            </div>)}
        </div>
      </section>

      <section className="card">
        <h2>{t('dash.quick')}</h2>
        <div className="quick-grid">
          <Link to="/new"><button className="primary">
            🧝 {t('create.character')}</button></Link>
          <Link to="/dm"><button>🏰 {t('create.campaign')}</button></Link>
          <Link to="/characters"><button>👥 {t('nav.sheets')}</button></Link>
          <Link to="/search"><button>📚 {t('nav.compendium')}</button></Link>
        </div>
        <form onSubmit={quickRoll} className="row"
              style={{ marginTop: '.6rem' }}>
          <input value={expr} onChange={(e) => setExpr(e.target.value)}
                 placeholder="1d20, 2d6+3…" aria-label={t('dash.quickRoll')}
                 style={{ maxWidth: 140 }} />
          <button type="submit">🎲 {t('dash.roll')}</button>
          {rollResult && <strong role="status"
            className="result-pill">{rollResult}</strong>}
        </form>
      </section>

      {(chars?.length > 0 || camps?.length > 0) && (
        <section className="card">
          <h2>{t('dash.overview')}</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {chars != null && (
              <Link to="/characters" className="stat-tile">
                <span className="stat-num">{chars.length}</span>
                <span className="muted">{t('nav.sheets')}</span></Link>)}
            {camps != null && (
              <Link to="/campaigns" className="stat-tile">
                <span className="stat-num">{camps.length}</span>
                <span className="muted">{t('nav.campaigns')}</span></Link>)}
          </div>
        </section>)}

      {activity.length > 0 && (
        <section className="card">
          <h2>{t('dash.activity')}</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            {lastChar?.name}</p>
          {activity.map((o) => (
            <div key={o.operation_id} className="row">
              <span className="muted">
                {o.timestamp?.slice(11, 19)}</span>
              <span style={{ flex: 1 }}>{opLabel(t, o.operation_type)}</span>
            </div>))}
        </section>)}

      {favs.length > 0 && (
        <section className="card">
          <h2>★ {t('dash.favs')}</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {favs.slice(0, 10).map((f) => (
              <Link key={f.id || f}
                    to={`/content/${encodeURIComponent(f.id || f)}`}
                    className="chip"
                    style={{ textDecoration: 'none', color: 'inherit' }}>
                {f.name || (f.id || f).split(':').pop()}</Link>))}
          </div>
        </section>)}
    </main>
  )
}
