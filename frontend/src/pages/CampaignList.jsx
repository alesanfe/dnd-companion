import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errText } from '../api.js'
import { useT } from '../i18n.jsx'

/** Lista de campañas del usuario — hub entre fichas y mesa. */
export default function CampaignList() {
  const { t } = useT()
  const [camps, setCamps] = useState(null)
  const [err, setErr] = useState(null)
  const fileRef = useRef(null)

  const load = () => api.listCampaigns()
      .then((r) => setCamps(r.campaigns))
      .catch((e) => setErr(errText(e, t)))

  // restaura un backup exportado (misma forma que /export)
  const onImport = async (e) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    try {
      await api.importCampaign(JSON.parse(await f.text()))
      load()
    } catch (ex) { setErr(errText(ex, t)) }
  }

  useEffect(() => { load() }, [])

  const ROLE = { owner: 'DM', dm: 'DM', co_dm: t('camps.coDm'),
                 player: t('camps.player'), guest: t('camps.guest'),
                 spectator: t('camps.spectator') }
  return (
    <main>
      <h1>{t('camp.title')}
        <button className="ghost" style={{ float: 'right' }}
                title={t('camps.importTitle')}
                onClick={() => fileRef.current?.click()}>
          {t('camps.import')}</button>
        <input ref={fileRef} type="file" accept=".json" hidden
               onChange={onImport} />
      </h1>
      {err && <p className="error" role="alert">{err}</p>}
      {camps === null &&
        <p className="muted" role="status">{t('common.loading')}</p>}
      {camps && camps.length === 0 && (
        <div className="card empty">
          <p><strong>{t('camp.empty')}</strong></p>
          <Link to="/dm"><button className="primary">{t('nav.dm')}</button></Link>
        </div>)}
      <div className="char-grid">
      {(camps || []).map((c) => (
        <Link key={c.id} to={`/campaign/${c.id}`}
              className="card dash-card">
          <div className="row" style={{ marginTop: 0 }}>
            <strong style={{ flex: 1, fontSize: '1.1rem' }}>
              {c.name}</strong>
            <span className="chip">{ROLE[c.role] || c.role}</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            🗺 {t(`ruleset.${c.ruleset}`)}</p>
        </Link>))}
      </div>
    </main>
  )
}
