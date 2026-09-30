import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { api } from '../api.js'
import { pendingOps } from '../db.js'
import { currentUser, clearAuth, getToken } from '../session.js'
import { useT } from '../i18n.jsx'

export default function Header() {
  const { t, tf } = useT()
  const [user, setUser] = useState(currentUser())
  const [online, setOnline] = useState(navigator.onLine)
  const [pending, setPending] = useState(0)
  const [notifs, setNotifs] = useState([])      // peticiones de tirada
  const [showNotifs, setShowNotifs] = useState(false)

  useEffect(() => {
    const tick = async () => {
      setOnline(navigator.onLine)
      setUser(currentUser())   // refleja login/logout hechos en /settings
      setPending((await pendingOps()).length)
      // sesión: valida el token contra /auth/me — si caducó, fuera
      if (getToken()) {
        try {
          const u = await api.me()
          if (JSON.stringify(u) !==
              JSON.stringify(currentUser())) {
            localStorage.setItem('dc.user', JSON.stringify(u))
            setUser(u)
          }
        } catch (e) {
          // solo el 401 cierra sesión — un error de red/offline
          // no debe revocar el token local
          if (e.status === 401) { clearAuth(); setUser(null) }
        }
      }
      // peticiones de tirada del DM sobre mis personajes en campaña
      try {
        const chars = (await api.listCharacters()).characters || []
        const byCamp = {}
        for (const c of chars)
          if (c.campaign_id)
            (byCamp[c.campaign_id] ||= []).push(c)
        const out = []
        for (const [campId, cs] of Object.entries(byCamp)) {
          try {
            const r = await api.pendingRolls(campId, cs.map((c) => c.id))
            for (const p of r.pending || [])
              out.push({ ...p, name: cs.find((c) => c.id === p.character_id)?.name })
          } catch { /* campaña inaccesible — seguir con el resto */ }
        }
        setNotifs(out)
      } catch { setNotifs([]) }
    }
    tick()
    const t = setInterval(tick, 5000)
    const onKey = (e) => {
      if (e.key === 'Escape') setShowNotifs(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('online', tick)
    window.addEventListener('offline', tick)
    return () => { clearInterval(t)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('online', tick)
      window.removeEventListener('offline', tick) }
  }, [])

  return (
    <header className="nav">
      <Link to="/" className="brand">D&D Companion</Link>
      <NavLink to="/" end>{t('nav.home')}</NavLink>
      <NavLink to="/characters">{t('nav.sheets')}</NavLink>
      <NavLink to="/campaigns">{t('nav.campaigns')}</NavLink>
      <NavLink to="/search">{t('nav.compendium')}</NavLink>
      <NavLink to="/dm">{t('nav.dm')}</NavLink>
      <Link to="/new" className="btn-create">+ {t('nav.create')}</Link>
      <span className="spacer" />
      <Link to="/settings#sync"
            className={`ghost sync ${online ? 'on' : 'off'}`}
            role="status" aria-live="polite"
            aria-label={t('hdr.syncAria')}
            style={{ textDecoration: 'none' }}>
        {online ? t('sync.online') : t('sync.offline')}
        {pending > 0 && ` · ${pending}`}
      </Link>
      {notifs.length > 0 && (
        <button className="ghost"
                aria-label={tf('hdr.notifsAria', { n: notifs.length })}
                aria-live="polite" onClick={() => setShowNotifs(!showNotifs)}>
          🔔{notifs.length}</button>)}
      <Link to="/settings" className="ghost"
            aria-label={t('set.title')}
            style={{ textDecoration: 'none' }}>⚙</Link>
      <Link to="/settings" className="ghost"
            style={{ textDecoration: 'none' }}>
        {user ? user.username : t('account.login')}</Link>

      {showNotifs && notifs.length > 0 && (
        <div className="popover" role="dialog" aria-label={t('hdr.notifs')}>
          <strong>{t('hdr.notifsTitle')}</strong>
          {notifs.map((n, i) => (
            <div key={n.character_id + (n.at ?? i)} className="notice">
              <span><strong>{n.name}</strong>: {t('cb.rollTag')} {n.expression}
                {n.reason && ` — ${n.reason}`}
                {n.secret &&
                  <span className="muted"> ({t('hdr.secretTag')})</span>}</span>
              <Link to={`/character/${n.character_id}`}>
                <button>{t('hdr.go')}</button></Link>
            </div>))}
          <button className="ghost"
                  onClick={() => setShowNotifs(false)}>
            {t('common.close')}</button>
        </div>
      )}
    </header>
  )
}
