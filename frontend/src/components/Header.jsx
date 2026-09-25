import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { pendingOps } from '../db.js'
import { clearAuth, currentUser, getPrefs, setAuth, setPref }
  from '../session.js'
import { useT } from '../i18n.jsx'

export default function Header() {
  const { t, lang, setLang } = useT()
  const [user, setUser] = useState(currentUser())
  const [creds, setCreds] = useState({ u: '', p: '' })
  const [online, setOnline] = useState(navigator.onLine)
  const [pending, setPending] = useState(0)
  const [notifs, setNotifs] = useState([])      // peticiones de tirada
  const [showNotifs, setShowNotifs] = useState(false)
  const [prefs, setPrefs] = useState(getPrefs())
  const [showSettings, setShowSettings] = useState(false)
  const [showLogin, setShowLogin] = useState(false)
  const [showSync, setShowSync] = useState(false)

  useEffect(() => {
    const tick = async () => {
      setOnline(navigator.onLine)
      setPending((await pendingOps()).length)
      // peticiones de tirada del DM sobre mis personajes en campaña
      try {
        const chars = (await api.listCharacters()).characters || []
        const byCamp = {}
        for (const c of chars)
          if (c.campaign_id)
            (byCamp[c.campaign_id] ||= []).push(c)
        const out = []
        for (const [campId, cs] of Object.entries(byCamp)) {
          const r = await api.pendingRolls(campId, cs.map((c) => c.id))
          for (const p of r.pending || [])
            out.push({ ...p, name: cs.find((c) => c.id === p.character_id)?.name })
        }
        setNotifs(out)
      } catch { setNotifs([]) }
    }
    tick()
    const t = setInterval(tick, 5000)
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setShowSettings(false); setShowLogin(false); setShowSync(false)
        setShowNotifs(false)
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('online', tick)
    window.addEventListener('offline', tick)
    return () => { clearInterval(t)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('online', tick)
      window.removeEventListener('offline', tick) }
  }, [])

  const auth = async (fn) => {
    const r = await fn(creds.u, creds.p)
    setAuth(r.token, { user_id: r.user_id, username: creds.u })
    setUser(currentUser()); setCreds({ u: '', p: '' }); setShowLogin(false)
  }

  const pref = (k, v) => { setPref(k, v); setPrefs(getPrefs()) }

  return (
    <header className="nav">
      <Link to="/">{t('nav.sheets')}</Link>
      <Link to="/campaigns">{t('nav.campaigns')}</Link>
      <Link to="/search">{t('nav.compendium')}</Link>
      <Link to="/dm">{t('nav.dm')}</Link>
      <Link to="/new" className="btn-create">+ {t('nav.create')}</Link>
      <span className="spacer" />
      <button className="ghost lang" aria-label="Language / Idioma"
              title="ES / EN"
              onClick={() => setLang(lang === 'es' ? 'en' : 'es')}>
        {lang.toUpperCase()}</button>
      <button className={`ghost sync ${online ? 'on' : 'off'}`}
              role="status" aria-live="polite"
              aria-label="Estado de sincronización"
              onClick={() => setShowSync(!showSync)}>
        {online ? t('sync.online') : t('sync.offline')}
        {pending > 0 && ` · ${pending}`}
      </button>
      {notifs.length > 0 && (
        <button className="ghost" aria-label={`${notifs.length} avisos`}
                aria-live="polite" onClick={() => setShowNotifs(!showNotifs)}>
          🔔{notifs.length}</button>)}
      <button className="ghost" aria-label="Ajustes"
              onClick={() => setShowSettings(!showSettings)}>⚙</button>
      {user
        ? <><span className="muted">{user.username}</span>
            <button className="ghost" onClick={() => { clearAuth(); setUser(null) }}>{t('account.logout')}</button></>
        : <button className="ghost" onClick={() => setShowLogin(!showLogin)}>{t('account.login')}</button>}

      {showLogin && !user && (
        <div className="popover">
          <input placeholder={t('account.user')} value={creds.u} autoFocus
                 onChange={(e) => setCreds({ ...creds, u: e.target.value })} />
          <input placeholder={t('account.pass')} type="password" value={creds.p}
                 onChange={(e) => setCreds({ ...creds, p: e.target.value })} />
          <div className="row">
            <button onClick={() => auth(api.login)}>{t('account.login')}</button>
            <button className="ghost" onClick={() => auth(api.register)}>Register</button>
          </div>
        </div>
      )}

      {showNotifs && notifs.length > 0 && (
        <div className="popover" role="dialog" aria-label="Avisos">
          <strong>Avisos del DM</strong>
          {notifs.map((n) => (
            <div key={n.character_id + n.at} className="notice">
              <span><strong>{n.name}</strong>: tirada {n.expression}
                {n.reason && ` — ${n.reason}`}
                {n.secret && <span className="muted"> (secreta)</span>}</span>
              <Link to={`/character/${n.character_id}`}>
                <button>Ir</button></Link>
            </div>))}
          <button className="ghost"
                  onClick={() => setShowNotifs(false)}>Cerrar</button>
        </div>
      )}

      {showSync && (
        <div className="popover" role="dialog" aria-label="Sincronización">
          <strong>{t('sync.online') === 'online' ? 'Sync' : 'Sincronización'}</strong>
          <span className={online ? '' : 'muted'}>
            {online ? t('sync.online') : t('sync.offline')}</span>
          {pending > 0
            ? <span className="muted">{pending} {t('sync.pending')}</span>
            : <span className="muted">{t('charlist.synced')} ✓</span>}
          <SyncConflicts />
          <button className="ghost"
                  onClick={() => setShowSync(false)}>{t('common.close')}</button>
        </div>
      )}

      {showSettings && (
        <div className="popover" role="dialog" aria-label="Ajustes">
          <label>Tema
            <select value={prefs.theme} onChange={(e) => pref('theme', e.target.value)}>
              <option value="dark">Oscuro</option>
              <option value="light">Claro</option>
              <option value="sepia">Sepia</option>
              <option value="hc">Alto contraste</option>
            </select>
          </label>
          <label>Texto
            <select value={prefs.font} onChange={(e) => pref('font', e.target.value)}>
              <option value="sm">Pequeño</option>
              <option value="md">Normal</option>
              <option value="lg">Grande</option>
              <option value="xl">Muy grande</option>
            </select>
          </label>
          <label>Densidad
            <select value={prefs.density}
                    onChange={(e) => pref('density', e.target.value)}>
              <option value="comfortable">Cómoda</option>
              <option value="normal">Normal</option>
              <option value="compact">Compacta</option>
            </select>
          </label>
          <label>
            <input type="checkbox" checked={prefs.motion === 'off'}
                   onChange={(e) => pref('motion', e.target.checked ? 'off' : 'on')} />
            Reducir movimiento
          </label>
        </div>
      )}
    </header>
  )
}

/** Operaciones rechazadas por optimistic locking — se muestran en el
    popover de sync con enlace a la entidad para revisar manualmente. */
function SyncConflicts() {
  const [rows, setRows] = useState(null)
  useEffect(() => {
    fetch('/api/operations/conflicts')
      .then((r) => r.ok ? r.json() : { conflicts: [] })
      .then((r) => setRows(r.conflicts))
      .catch(() => setRows([]))
  }, [])
  if (!rows?.length) return null
  return (
    <div role="alert">
      <strong>⚠ {rows.length} conflicto{rows.length > 1 ? 's' : ''}
      </strong>
      <span className="muted">
        Datos modificados en dos dispositivos — revísalos:</span>
      <ul style={{ margin: '.3rem 0', paddingLeft: '1rem' }}>
        {rows.map((r) => (
          <li key={r.operation_id}>
            <Link to={`/character/${r.entity_id}/actividad`}>
              {r.operation_type}</Link>
            <span className="muted">
              {' '}· {r.timestamp?.slice(11, 19)}</span>
          </li>))}
      </ul>
    </div>
  )
}
