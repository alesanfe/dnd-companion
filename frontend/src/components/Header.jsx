import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { pendingOps } from '../db.js'
import { clearAuth, currentUser, getPrefs, setAuth, setPref }
  from '../session.js'

export default function Header() {
  const [user, setUser] = useState(currentUser())
  const [creds, setCreds] = useState({ u: '', p: '' })
  const [online, setOnline] = useState(navigator.onLine)
  const [pending, setPending] = useState(0)
  const [prefs, setPrefs] = useState(getPrefs())
  const [showSettings, setShowSettings] = useState(false)
  const [showLogin, setShowLogin] = useState(false)
  const [showSync, setShowSync] = useState(false)

  useEffect(() => {
    const tick = async () => {
      setOnline(navigator.onLine)
      setPending((await pendingOps()).length)
    }
    tick()
    const t = setInterval(tick, 5000)
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setShowSettings(false); setShowLogin(false); setShowSync(false)
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
      <Link to="/">Personajes</Link>
      <Link to="/search">Compendio</Link>
      <Link to="/dm">Mesa DM</Link>
      <Link to="/new" className="btn-create">+ Crear</Link>
      <span className="spacer" />
      <button className={`ghost sync ${online ? 'on' : 'off'}`}
              role="status" aria-live="polite"
              aria-label="Estado de sincronización"
              onClick={() => setShowSync(!showSync)}>
        {online ? 'en línea' : 'offline'}
        {pending > 0 && ` · ${pending}`}
      </button>
      <button className="ghost" aria-label="Ajustes"
              onClick={() => setShowSettings(!showSettings)}>⚙</button>
      {user
        ? <><span className="muted">{user.username}</span>
            <button className="ghost" onClick={() => { clearAuth(); setUser(null) }}>Salir</button></>
        : <button className="ghost" onClick={() => setShowLogin(!showLogin)}>Entrar</button>}

      {showLogin && !user && (
        <div className="popover">
          <input placeholder="usuario" value={creds.u} autoFocus
                 onChange={(e) => setCreds({ ...creds, u: e.target.value })} />
          <input placeholder="contraseña" type="password" value={creds.p}
                 onChange={(e) => setCreds({ ...creds, p: e.target.value })} />
          <div className="row">
            <button onClick={() => auth(api.login)}>Entrar</button>
            <button className="ghost" onClick={() => auth(api.register)}>Registrar</button>
          </div>
        </div>
      )}

      {showSync && (
        <div className="popover" role="dialog" aria-label="Sincronización">
          <strong>Sincronización</strong>
          <span className={online ? '' : 'muted'}>
            {online ? 'En línea' : 'Sin conexión — los cambios se guardan localmente'}
          </span>
          {pending > 0
            ? <span className="muted">
                {pending} cambio{pending > 1 ? 's' : ''} pendiente{pending > 1 ? 's' : ''}
                {' '}de subir — se reintentan solos al volver la conexión.</span>
            : <span className="muted">Todo sincronizado.</span>}
          <button className="ghost"
                  onClick={() => setShowSync(false)}>Cerrar</button>
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
