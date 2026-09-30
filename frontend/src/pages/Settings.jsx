import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, flushQueue } from '../api.js'
import { conflictedOps, deadOps, dropOp, markOp,
         pendingOps } from '../db.js'
import { clearAuth, currentUser, getPrefs, setAuth, setPref }
  from '../session.js'
import { useT } from '../i18n.jsx'

/** Ajustes consolidados: cuenta, apariencia, accesibilidad y
    estado de sincronización — antes repartidos en el header. */
export default function Settings() {
  const { t, lang, setLang } = useT()
  const [user, setUser] = useState(currentUser())
  const [creds, setCreds] = useState({ u: '', p: '' })
  const [prefs, setPrefs] = useState(getPrefs())
  const [online, setOnline] = useState(navigator.onLine)
  const [pending, setPending] = useState(0)

  const tick = async () => {
    setOnline(navigator.onLine)
    setPending((await pendingOps()).length)
  }

  useEffect(() => {
    tick()
    window.addEventListener('online', tick)
    window.addEventListener('offline', tick)
    return () => {
      window.removeEventListener('online', tick)
      window.removeEventListener('offline', tick)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const auth = async (fn) => {
    const r = await fn(creds.u, creds.p)
    setAuth(r.token, { user_id: r.user_id, username: creds.u })
    setUser(currentUser()); setCreds({ u: '', p: '' })
  }
  const pref = (k, v) => { setPref(k, v); setPrefs(getPrefs()) }

  return (
    <main>
      <h1>{t('set.title')}</h1>

      <section className="card">
        <h2>{t('set.account')}</h2>
        {user ? (
          <div className="row">
            <span style={{ flex: 1 }}>{user.username}</span>
            <button className="ghost" onClick={async () => {
              // revoca el token en el servidor antes de limpiar
              // local — si falla la red se limpia igual
              try { await api.logout() } catch { /* offline */ }
              clearAuth(); setUser(null)
            }}>{t('account.logout')}</button>
          </div>) : (
          <>
            <div className="row">
              <input placeholder={t('account.user')} value={creds.u}
                     onChange={(e) =>
                       setCreds({ ...creds, u: e.target.value })} />
              <input placeholder={t('account.pass')} type="password"
                     value={creds.p}
                     onChange={(e) =>
                       setCreds({ ...creds, p: e.target.value })} />
            </div>
            <div className="row">
              <button onClick={() => auth(api.login)}>
                {t('account.login')}</button>
              <button className="ghost" onClick={() => auth(api.register)}>
                {t('account.register')}</button>
            </div>
            <p className="muted">{t('set.accountHint')}</p>
          </>)}
      </section>

      <section className="card set-list">
        <h2>{t('set.appearance')}</h2>
        <label>{t('set.lang')}
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            <option value="es">Español</option>
            <option value="en">English</option>
          </select>
        </label>
        <label>{t('set.theme')}
          <select value={prefs.theme}
                  onChange={(e) => pref('theme', e.target.value)}>
            <option value="dark">{t('set.themeDark')}</option>
            <option value="light">{t('set.themeLight')}</option>
            <option value="sepia">{t('set.themeSepia')}</option>
            <option value="hc">{t('set.themeHc')}</option>
          </select>
        </label>
        <label>{t('set.font')}
          <select value={prefs.font}
                  onChange={(e) => pref('font', e.target.value)}>
            <option value="sm">{t('set.fontSm')}</option>
            <option value="md">{t('set.fontMd')}</option>
            <option value="lg">{t('set.fontLg')}</option>
            <option value="xl">{t('set.fontXl')}</option>
          </select>
        </label>
        <label>{t('set.density')}
          <select value={prefs.density}
                  onChange={(e) => pref('density', e.target.value)}>
            <option value="comfortable">{t('set.densComfort')}</option>
            <option value="normal">{t('set.densNormal')}</option>
            <option value="compact">{t('set.densCompact')}</option>
          </select>
        </label>
        <label>
          <input type="checkbox" checked={prefs.motion === 'off'}
                 onChange={(e) =>
                   pref('motion', e.target.checked ? 'off' : 'on')} />
          {' '}{t('set.motion')}
        </label>
        <label>
          <input type="checkbox" checked={prefs.dyslexia === 'on'}
                 onChange={(e) =>
                   pref('dyslexia', e.target.checked ? 'on' : 'off')} />
          {' '}{t('set.dyslexia')}
        </label>
      </section>

      <section className="card" id="sync">
        <h2>{t('set.sync')}</h2>
        <div className="row">
          <span className={online ? '' : 'muted'}>
            {online ? t('sync.online') : t('sync.offline')}</span>
          {pending > 0
            ? <span className="muted">{pending} {t('sync.pending')}</span>
            : <span className="muted">{t('charlist.synced')} ✓</span>}
        </div>
        <SyncQueue onChanged={tick} />
        <SyncConflicts />
      </section>

      <PushCard user={user} />
      <PackagesCard />
    </main>
  )
}

/** Notificaciones push PWA: suscripción Web Push por dispositivo —
    el roll-request del DM llega con la app cerrada (VAPID). */
function PushCard({ user }) {
  const { t } = useT()
  const [status, setStatus] = useState('idle')   // idle|on|off|denied
  const [msg, setMsg] = useState(null)
  useEffect(() => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      setStatus('off'); return
    }
    navigator.serviceWorker.ready
      .then((r) => r.pushManager.getSubscription())
      .then((s) => setStatus(s ? 'on' : 'idle'))
      .catch(() => setStatus('off'))
  }, [])

  const urlB64 = (s) =>
    Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')),
                   (c) => c.charCodeAt(0))

  const subscribe = async () => {
    try {
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') { setStatus('denied'); return }
      const { public_key } = await api.vapidKey()
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64(public_key),
      })
      await api.pushSubscribe(sub)
      setStatus('on'); setMsg('✓')
    } catch (e) { setMsg(`⚠ ${e.message}`) }
  }
  const unsubscribe = async () => {
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        await api.pushUnsubscribe(sub.endpoint).catch(() => {})
        await sub.unsubscribe()
      }
      setStatus('idle')
    } catch (e) { setMsg(`⚠ ${e.message}`) }
  }

  if (status === 'off') return null
  return (
    <section className="card">
      <h2>{t('push.title')}</h2>
      <p className="muted" style={{ fontSize: '.85rem' }}>
        {t('push.hint')}</p>
      {status === 'denied' && (
        <p className="muted" role="alert">{t('push.denied')}</p>)}
      {status !== 'on'
        ? <button disabled={!user}
                  title={!user ? t('push.needAccount') : undefined}
                  onClick={subscribe}>{t('push.enable')}</button>
        : <button className="ghost"
                  onClick={unsubscribe}>{t('push.disable')}</button>}
      {!user && <p className="muted">{t('push.needAccount')}</p>}
      {msg && <p className="muted" role="status">{msg}</p>}
    </section>
  )
}

/** Paquetes de contenido instalables (manifest + entidades) —
    las fuentes instaladas salen como 'pkg:<id>' en el compendio. */
function PackagesCard() {
  const { t, tf } = useT()
  const [pkgs, setPkgs] = useState(null)
  const [msg, setMsg] = useState(null)
  const load = () => api.listPackages()
    .then((r) => setPkgs(r.packages || []))
    .catch(() => setPkgs([]))
  useEffect(() => { load() }, [])
  const onFile = async (e) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    try {
      const body = JSON.parse(await f.text())
      const r = await api.installPackage(body)
      setMsg(`✓ ${r.package}: ${r.entities} ${t('pkg.entities')}`)
      load()
    } catch (ex) { setMsg(`⚠ ${ex.message}`) }
  }
  return (
    <section className="card">
      <h2>{t('pkg.title')}</h2>
      <label className="ghost" role="button" tabIndex={0}
             style={{ cursor: 'pointer' }}>
        {t('pkg.install')}
        <input type="file" accept=".json" hidden onChange={onFile} />
      </label>
      {msg && <p className="muted" role="status">{msg}</p>}
      {(pkgs || []).map((p) => (
        <div key={p.id} className="row" style={{ flexWrap: 'wrap' }}>
          <span style={{ flex: 1 }}>
            <strong>{p.name}</strong>{' '}
            <span className="muted">v{p.version}</span>
            {p.attribution_text && (
              <span className="muted" style={{ display: 'block',
                                               fontSize: '.8rem' }}>
                {p.attribution_text}</span>)}
          </span>
          {/* desglose por tipo: "12 conjuros · 3 objetos" */}
          {p.entities > 0 && (
            <span className="muted" style={{ fontSize: '.8rem' }}>
              {Object.entries(p.by_type || {})
                .map(([ty, n]) => `${n} ${t(`search.${ty}`) !==
                  `search.${ty}` ? t(`search.${ty}`) : ty}`)
                .join(' · ')}
            </span>)}
          <span className="chip">{p.license}</span>
          {!p.distribution_allowed && (
            <span className="chip" title={t('pkg.privateTitle')}>
              {t('pkg.private')}</span>)}
          <button className="ghost" style={{ minHeight: 24 }}
                  title={t('pkg.uninstall')}
                  aria-label={`${t('pkg.uninstall')} ${p.name}`}
                  onClick={async () => {
                    if (!confirm(tf('pkg.uninstallConfirm',
                                    { name: p.name }))) return
                    try {
                      const r = await api.uninstallPackage(p.id)
                      setMsg(`✓ ${r.entities} ${t('pkg.entities')}`)
                      load()
                    } catch (ex) { setMsg(`⚠ ${ex.message}`) }
                  }}>✕</button>
        </div>))}
      {pkgs?.length === 0 && <p className="muted">{t('pkg.empty')}</p>}
      <p className="muted" style={{ fontSize: '.8rem' }}>
        {t('pkg.hint')}</p>
    </section>
  )
}

/** Operaciones encoladas offline: qué falta por sincronizar, con
    reintento manual y descarte — el 'pending N' del header por fin
    lleva a algo accionable. */
function SyncQueue({ onChanged }) {
  const { t } = useT()
  const [ops, setOps] = useState(null)
  const [dead, setDead] = useState(null)
  const [confl, setConfl] = useState(null)
  const load = () => {
    pendingOps().then(setOps).catch(() => setOps([]))
    deadOps().then(setDead).catch(() => setDead([]))
    conflictedOps().then(setConfl).catch(() => setConfl([]))
  }
  useEffect(() => { load() }, [])
  if (!ops?.length && !dead?.length && !confl?.length) return null
  return (<div>
    <strong>{t('sync.queueTitle')}</strong>
    <ul style={{ margin: '.3rem 0', paddingLeft: '1rem' }}>
      {(ops || []).map((o) => (
        <li key={o.id} className="row">
          {o.payload.entity_kind === 'character' ? (
            <Link to={`/character/${o.payload.entity_id}/actividad`}>
              {o.payload.operation_type}</Link>
          ) : <span>{o.payload.operation_type}</span>}
          <span className="muted">
            {' '}· {new Date(o.created_at).toLocaleTimeString()}</span>
          <button className="ghost" style={{ minHeight: 24 }}
                  title={t('sync.discard')}
                  aria-label={t('sync.discard')}
                  onClick={async () => {
                    await dropOp(o.id); load(); onChanged?.()
                  }}>✕</button>
        </li>))}
      {/* rechazadas por el servidor — se perdieron y el usuario lo
          ve aquí en vez de jamás enterarse */}
      {(dead || []).map((o) => (
        <li key={o.id} className="row" style={{ opacity: .7 }}>
          <s>{o.payload.operation_type}</s>
          <span className="muted">
            {' '}· {t('sync.rejected')}
            {' '}· {new Date(o.created_at).toLocaleTimeString()}</span>
          <button className="ghost" style={{ minHeight: 24 }}
                  title={t('sync.discard')}
                  aria-label={t('sync.discard')}
                  onClick={async () => {
                    await dropOp(o.id); load(); onChanged?.()
                  }}>✕</button>
        </li>))}
      {/* 409 al reenviar: el servidor ganó — reintentar vuelve a
          'pending' (con versión refrescada) o se descarta */}
      {(confl || []).map((o) => (
        <li key={o.id} className="row" style={{ opacity: .85 }}>
          {o.payload.operation_type}
          <span className="muted">
            {' '}· {t('sync.conflictLocal')}
            {' '}· {new Date(o.created_at).toLocaleTimeString()}</span>
          <button className="ghost" style={{ minHeight: 24 }}
                  title={t('sync.retry')} aria-label={t('sync.retry')}
                  onClick={async () => {
                    await markOp(o.id, 'pending')
                    await flushQueue(); load(); onChanged?.()
                  }}>↻</button>
          <button className="ghost" style={{ minHeight: 24 }}
                  title={t('sync.discard')}
                  aria-label={t('sync.discard')}
                  onClick={async () => {
                    await dropOp(o.id); load(); onChanged?.()
                  }}>✕</button>
        </li>))}
    </ul>
    {ops?.length > 0 && (
      <button className="ghost" onClick={async () => {
        await flushQueue(); load(); onChanged?.()
      }}>{t('sync.flushNow')}</button>)}
  </div>)
}

/** Operaciones rechazadas por optimistic locking — resolución
    asistida: reintentar sobre la versión actual o descartar. */
function SyncConflicts() {
  const { t, tf } = useT()
  const [rows, setRows] = useState(null)
  const [msg, setMsg] = useState(null)
  const load = () => api.opConflicts()
    .then((r) => setRows(r.conflicts || []))
    .catch(() => setRows([]))
  useEffect(() => { load() }, [])
  if (!rows?.length) return null
  const act = async (fn, id, label) => {
    setMsg(null)
    try {
      await fn(id)
      setMsg(`✓ ${label}`)
    } catch (e) { setMsg(`⚠ ${e.message}`) }
    load()
  }
  return (
    <div role="alert">
      <strong>⚠ {tf('set.conflicts', { n: rows.length })}
      </strong>
      <span className="muted">
        {t('set.conflictsHint')}</span>
      <ul style={{ margin: '.3rem 0', paddingLeft: '1rem' }}>
        {rows.map((r) => (
          <li key={r.operation_id} className="row">
            {r.entity_kind === 'character' ? (
              <Link to={`/character/${r.entity_id}/actividad`}>
                {r.operation_type}</Link>
            ) : <span>{r.operation_type}</span>}
            <span className="muted"
                  title={JSON.stringify(r.payload)}>
              {' '}· {r.timestamp?.slice(11, 19)}
              {Object.keys(r.payload || {}).length > 0 &&
                ` · ${Object.entries(r.payload).slice(0, 2)
                    .map(([k, v]) => `${k}=${v}`).join(', ')}`}
            </span>
            <button className="ghost" style={{ minHeight: 24 }}
                    onClick={() =>
                      act(api.retryConflict, r.operation_id,
                          t('set.retryDone'))}>
              {t('set.retry')}</button>
            <button className="ghost" style={{ minHeight: 24 }}
                    onClick={() =>
                      act(api.dismissConflict, r.operation_id,
                          t('set.dismissDone'))}>
              {t('set.dismiss')}</button>
          </li>))}
      </ul>
      {msg && <p className="muted" role="status">{msg}</p>}
    </div>
  )
}
