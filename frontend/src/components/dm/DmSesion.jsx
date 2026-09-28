import { useEffect, useState } from 'react'
import { api } from '../../api.js'

/** Pestaña Sesión: datos de campaña, feed de tiradas en vivo,
    sesiones y preparación, peticiones de tirada a jugadores. */
export default function DmSesion({ c }) {
  const { t, tf, dmTab, campaign, setCampaign, campName, setCampName,
          eventFeed, setEventFeed, rollFeed, feedFilter, setFeedFilter,
          newRolls, setNewRolls, feedRef, playerView,
          sessTitle, setSessTitle, sessions, setSessions,
          timeline, setTimeline, rollReq, setRollReq, refresh,
          chat, chatText, setChatText, sendDmChat,
          typing, onDmTyping, partyChars = [] } = c
  const show = dmTab === 'sesion'
  // peticiones de tirada que los jugadores aún no han respondido —
  // se recalcula al llegar tiradas nuevas (una respuesta la cierra)
  const [pendingReqs, setPendingReqs] = useState([])
  const [loot, setLoot] = useState({ coin: 'gp', amount: '' })
  const [lootMsg, setLootMsg] = useState(null)
  useEffect(() => {
    if (!campaign || partyChars.length === 0) {
      setPendingReqs([])
      return
    }
    api.pendingRolls(campaign.id, partyChars.map((p) => p.id))
      .then((r) => setPendingReqs(r.pending || []))
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaign?.id, rollFeed.length, partyChars.length])
  // campañas existentes — sin esto recargar /dm obligaba a crear una
  // nueva cada visita
  const [camps, setCamps] = useState(null)
  const [pickId, setPickId] = useState('')
  useEffect(() => {
    if (campaign || camps !== null) return
    api.listCampaigns()
      .then((r) => {
        setCamps(r.campaigns)
        setPickId(r.campaigns[0]?.id || '')
      })
      .catch(() => setCamps([]))
  }, [campaign, camps])
  return (<>
    <section className="card" hidden={!show}>
      <h2>{t('dm.campaign')}</h2>
      {!campaign ? (<>
        <form className="row" onSubmit={async (e) => {
          e.preventDefault()
          const r = await api.createCampaign(campName || t('camp.name'))
          // createCampaign devuelve {id, invite_code} — el nombre se
          // conserva del input o el sidebar queda en blanco
          setCampaign({ ...r, name: campName || t('camp.name') })
        }}>
          <input value={campName} onChange={(e) => setCampName(e.target.value)}
                 placeholder={t('ses.campNamePh')} />
          <button type="submit">{t('ses.create')}</button>
        </form>
        {camps?.length > 0 && (
          <form className="row" onSubmit={async (e) => {
            e.preventDefault()
            if (!pickId) return
            setCampaign(await api.getCampaign(pickId))
          }}>
            <label className="muted">{t('ses.openExisting')}
              <select value={pickId} aria-label={t('ses.openExisting')}
                      onChange={(e) => setPickId(e.target.value)}>
                {camps.map((cp) => (
                  <option key={cp.id} value={cp.id}>{cp.name}</option>))}
              </select></label>
            <button type="submit" disabled={!pickId}>
              {t('camp.open')}</button>
          </form>)}
      </>) : (
        <>
          <p>{campaign.name} — {t('ses.invite')}:
            <strong> {campaign.invite_code}</strong>{' '}
            <button className="ghost" onClick={() => setCampaign(null)}>
              {t('ses.switch')}</button></p>
          <div className="row">
            <button className="ghost" onClick={async () => {
              const ex = await api.exportCampaign(campaign.id)
              const blob = new Blob([JSON.stringify(ex, null, 2)],
                                    { type: 'application/json' })
              const a = document.createElement('a')
              a.href = URL.createObjectURL(blob)
              a.download = 'campania.json'
              a.click()
            }}>{t('ses.exportBackup')}</button>
            <button className="ghost" onClick={async () =>
              setEventFeed(eventFeed ? null
                : (await api.campaignEvents(campaign.id)).events)
            }>{t('ses.audit')}</button>
          </div>
          {eventFeed && eventFeed.map((e) => (
            <div key={e.event_id} className="row">
              <span className="muted">{e.occurred_at.slice(11, 19)}</span>
              <span>{e.type}</span>
            </div>
          ))}
        </>
      )}
    </section>

    {campaign && rollFeed.length > 0 && (
      <section className="card" hidden={!show}>
        <h2>{t('dm.feed')}</h2>
        <div className="row" role="group" aria-label={t('ses.filterAria')}>
          {['todas', 'check', 'save', 'attack', 'damage'].map((f) => (
            <button key={f} className="ghost"
                    aria-pressed={feedFilter === f}
                    style={{ borderColor: feedFilter === f
                      ? 'var(--accent)' : undefined }}
                    onClick={() => setFeedFilter(f)}>
              {f === 'todas' ? t('dm.allRolls') : f}</button>))}
        </div>
        {newRolls > 0 && (
          <button className="ghost" role="status"
                  onClick={() => {
                    feedRef.current?.scrollTo({ top: 0 })
                    setNewRolls(0)
                  }}>{tf('ses.newEvents', { n: newRolls })} ↑</button>)}
        <div ref={feedRef}
             style={{ maxHeight: '18rem', overflowY: 'auto' }}
             onScroll={(e) => {
               if (e.target.scrollTop <= 40) setNewRolls(0)
             }}>
        {rollFeed.filter((r) =>
          (!playerView || !r.secret) &&
          (feedFilter === 'todas' ||
           r.roll_type === feedFilter)).map((r, i) => (
          <div key={i} className="row">
            <span>{r.secret ? '🔒 ' : ''}{r.character}</span>
            <span className="muted">
              {r.secret ? `${t('ses.secretTag')} · ` : ''}
              {r.roll_type} · {r.expression}</span>
            <strong>{r.total}</strong>
          </div>
        ))}
        </div>
      </section>
    )}

    {campaign && (
      <section className="card" hidden={!show}>
        <h2>{t('dm.sessions')}</h2>
        <div className="row">
          <input value={sessTitle} placeholder={t('ses.titlePh')}
                 onChange={(e) => setSessTitle(e.target.value)} />
          <button disabled={!sessTitle} onClick={async () => {
            await api.createSession(campaign.id, {
              title: sessTitle, number: sessions.length + 1 })
            setSessTitle('')
            const r = await api.listSessions(campaign.id)
            setSessions(r.sessions)
          }}>{t('ses.create')}</button>
          <button onClick={async () => {
            const r = timeline ? null
                               : await api.timeline(campaign.id)
            setTimeline(r?.timeline || null)
          }}>{t('ses.timeline')}</button>
        </div>
        {sessions.map((s) => (
          <div key={s.id}>
            <div className="row">
              <strong>#{s.number} {s.title}</strong>
              <span className="muted">· {s.status}</span>
              {s.status !== 'done' && (
                <button style={{ minHeight: 32 }} onClick={async () => {
                  await api.patchSession(campaign.id, s.id, {
                    status: s.status === 'prep' ? 'active' : 'done' })
                  api.listSessions(campaign.id)
                    .then((r) => setSessions(r.sessions))
                }}>{s.status === 'prep'
                    ? t('ses.start') : t('common.close')}</button>
              )}
            </div>
            <ul>
              {s.scenes.map((sc) => (
                <li key={sc.id} className="row">
                  {sc.data.order}. {sc.name}
                  {(sc.data.monsters || []).length > 0 && (
                    <button style={{ minHeight: 32 }}
                            onClick={async () => {
                      const r = await api.startScene(campaign.id, sc.id)
                      refresh(r.combat_id)
                    }}>▶ {t('ses.combatBtn')}</button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {timeline && timeline.map((tl) => (
          <div key={tl.id} className="row">
            <span className="muted">{tl.world_date || '—'}</span>
            <span>{tl.name}</span>
          </div>
        ))}
      </section>
    )}

    {/* chat de mesa del DM — el mismo canal efímero que ven los
        jugadores en la pestaña Actividad de su ficha */}
    {campaign && (
      <section className="card" hidden={!show}>
        <h2>{t('act.chat')}</h2>
        <ul style={{ maxHeight: 160, overflowY: 'auto' }}>
          {chat.length === 0 && (
            <li className="muted">{t('act.chatEmpty')}</li>)}
          {chat.map((m, i) => (
            <li key={i}><b>{m.from}:</b> {m.text}</li>))}
        </ul>
        {typing && (
          <p className="muted" role="status" aria-live="polite"
             style={{ margin: '.2rem 0' }}>
            {typing.from} {t('act.typing')}</p>)}
        <form className="row" onSubmit={sendDmChat}>
          <input value={chatText} aria-label={t('act.chatAria')}
                 maxLength={500} placeholder={t('act.chatPh')}
                 onChange={(e) => {
                   setChatText(e.target.value); onDmTyping?.()
                 }} />
          <button type="submit" disabled={!chatText.trim()}>
            {t('act.send')}</button>
        </form>
      </section>)}

    {campaign && (
      <section className="card" hidden={!show}>
        <h2>{t('dm.rollreq')}</h2>
        {pendingReqs.length > 0 && (
          <p className="muted" role="status">
            {t('ses.pendingRolls')}: {pendingReqs.map((p) => {
              const pj = partyChars.find((x) => x.id === p.character_id)
              return `${pj?.name || p.character_id} (${p.expression})`
            }).join(' · ')}
          </p>)}
        <div className="row">
          {/* select por nombre — pedir el uuid de la ficha era inusable */}
          <select value={rollReq.character_id}
                  aria-label={t('ses.pickChar')}
                  onChange={(e) => setRollReq(
                    { ...rollReq, character_id: e.target.value })}>
            <option value="">{t('ses.pickChar')}</option>
            {partyChars.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>))}
          </select>
          <input value={rollReq.expression} style={{ maxWidth: 90 }}
                 onChange={(e) => setRollReq({ ...rollReq, expression: e.target.value })} />
          <input value={rollReq.reason} placeholder={t('ses.reasonPh')}
                 onChange={(e) => setRollReq({ ...rollReq, reason: e.target.value })} />
          <button disabled={!rollReq.character_id}
                  onClick={() => api.requestRoll(campaign.id, rollReq)
                    .then(() => api.pendingRolls(
                      campaign.id, partyChars.map((p) => p.id)))
                    .then((r) => setPendingReqs(r.pending || []))
                    .catch(() => {})}>
            {t('ses.request')}
          </button>
        </div>
        {/* descanso del grupo — una op rest.<kind> por ficha */}
        {partyChars.length > 0 && (
          <div className="row" style={{ marginTop: '.5rem' }}>
            <button className="ghost"
                    onClick={() => api.partyRest(campaign.id, 'short')
                      .then(() => setLootMsg(t('ses.restedShort')))
                      .catch(() => {})}>
              {t('ses.restShort')}</button>
            <button className="ghost"
                    onClick={() => api.partyRest(campaign.id, 'long')
                      .then(() => setLootMsg(t('ses.restedLong')))
                      .catch(() => {})}>
              {t('ses.restLong')}</button>
          </div>)}
        {/* reparto del botín — una op currency.earn por PJ */}
        {partyChars.length > 0 && (
          <div className="row" style={{ marginTop: '.5rem' }}>
            <input type="number" min="1" value={loot.amount}
                   placeholder={t('ses.lootAmt')}
                   aria-label={t('ses.lootAmt')}
                   style={{ maxWidth: 90 }}
                   onChange={(e) => setLoot(
                     { ...loot, amount: e.target.value })} />
            <select value={loot.coin} aria-label={t('ses.lootCoin')}
                    onChange={(e) => setLoot(
                      { ...loot, coin: e.target.value })}>
              {['pp', 'gp', 'ep', 'sp', 'cp'].map((k) => (
                <option key={k} value={k}>{k}</option>))}
            </select>
            <button className="ghost"
                    disabled={!(+loot.amount > 0)}
                    onClick={() => api.splitLoot(campaign.id,
                      { coin: loot.coin, amount: +loot.amount })
                      .then((r) => setLootMsg(tf('ses.lootSplit', {
                        share: r.share, coin: loot.coin,
                        n: r.awarded })))
                      .catch(() => {})}>
              {t('ses.lootSplitBtn')}
            </button>
            {lootMsg && <span className="muted">{lootMsg}</span>}
          </div>)}
      </section>
    )}
  </>)
}
