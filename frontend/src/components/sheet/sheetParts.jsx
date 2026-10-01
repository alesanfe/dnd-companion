/* Bloques autocontenidos de CharacterSheet: recorrido de primera
   visita, editor de identidad, socket de campaña y preview de
   rasgos del siguiente nivel. Extraídos para mantener la página
   como coordinador. */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api.js'
import { campaignSocket } from '../../ws.js'
import { useT } from '../../i18n.jsx'

const TOUR_KEYS = ['tour.identity', 'tour.focus', 'tour.vitalbar',
                   'tour.collapse', 'tour.firstroll']

/** Sync en vivo: escucha la sala de la campaña y reparte eventos —
    chat efímero, tiradas del grupo (con notificación opcional),
    peticiones del DM y resync cuando un evento toca esta ficha. */
export function useCampaignSocket(char, id, notify, load, sinks) {
  const { setChat, setRollLog, setRollRequest, setTyping } = sinks
  const { tf } = useT()
  const wsRef = useRef(null)
  useEffect(() => {
    if (!char?.campaign_id) return undefined
    const sock = campaignSocket(char.campaign_id, {
      onOpen: load,                 // resync tras cada reconexión
      onMessage: (msg) => {
      const ev = msg.event || msg      // eventos van sin envolver
      if (!ev?.type || typeof ev.type !== 'string') return
      /* chat efímero — el tipo no lleva '.' y llega suelto */
      if (ev.type === 'chat') {
        setChat((l) => [
          { from: ev.from, text: ev.text }, ...l].slice(0, 30))
        return
      }
      /* "está escribiendo" — efímero como el chat, caduca solo */
      if (ev.type === 'typing') {
        setTyping?.({ from: ev.from, at: Date.now() })
        return
      }
      if (!ev.type.includes('.')) return
      /* tiradas de otros PJs de la campaña → log compartido
         (las secretas del DM no llegan a este socket) */
      if (ev.type === 'dice.roll.created') {
        if (ev.aggregate_id !== id && !ev.payload?.secret) {
          const p = ev.payload
          setRollLog((l) => [
            `🎲 ${p.character}: ${p.expression} = ${p.total}`,
            ...l].slice(0, 10))
          if (notify && document.hidden &&
              'Notification' in window)
            new Notification(`${p.character} tira`, {
              body: `${p.expression} = ${p.total}`,
              icon: '/icon-192.png' })
        }
        return
      }
      // eventos de la ficha — o eventos de combate que la referencian
      // (el DM daña/cura al PJ desde el tablero: payload.character_id)
      if (ev.aggregate_id !== id && ev.payload?.character_id !== id)
        return
      /* concentración: el daño vino por el tracker (combatant.damage)
         — el evento lleva la CD; sin este aviso el jugador no
         sabía que debía tirar CON */
      if (ev.payload?.concentration_check) {
        sinks.setNotice?.(tf('sheet.concCheck', {
          spell: ev.payload.spell,
          dc: ev.payload.concentration_dc }))
      }
      if (ev.type === 'dice.roll.requested') {
        setRollRequest(ev.payload)
        if (notify && 'Notification' in window)
          new Notification('El DM pide una tirada', {
            body: ev.payload?.label || '', icon: '/icon-192.png' })
      } else load()
      },
    })
    wsRef.current = sock
    return () => { wsRef.current = null; sock.close() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [char?.campaign_id, id, notify])
  return wsRef
}


/** Recorrido de primera visita — una vez, salta con Saltar. */
export function SheetTour({ step, onStep }) {
  const { t } = useT()
  if (step === null) return null
  const last = step === TOUR_KEYS.length - 1
  const done = () => {
    localStorage.setItem('dnd-tour-done', '1')
    onStep(null)
  }
  return (
    <div className="tour" role="dialog" aria-label={t('tour.aria')}>
      <h3>{t(`${TOUR_KEYS[step]}.title`)}</h3>
      <p>{t(`${TOUR_KEYS[step]}.desc`)}</p>
      <div className="tour-dots" aria-hidden="true">
        {TOUR_KEYS.map((_, i) => (
          <i key={i} className={i <= step ? 'on' : ''} />))}
      </div>
      <div className="tour-nav">
        <span className="muted step">{step + 1}/{TOUR_KEYS.length}</span>
        <span className="row" style={{ margin: 0 }}>
          <button className="ghost" onClick={done}>
            {t('tour.skip')}</button>
          <button className="primary"
                  onClick={() => last ? done() : onStep(step + 1)}>
            {last ? t('tour.play') : t('wiz.next')}</button>
        </span>
      </div>
    </div>
  )
}


/** Editor de identidad — campos de cabecera de la hoja
    (alineación, jugador, velocidades, sentidos, nombre). */
export function IdentityEditor({ d, name, op }) {
  const { t, tf } = useT()
  const set = (field, value) =>
    op('character.identity.set', { field, value })
  return (
    <details className="identity-edit">
      <summary>{t('sheet.editIdentity')}</summary>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select value={d.alignment || ''} aria-label={t('sheet.alignment')}
                onChange={(e) => set('alignment', e.target.value)}>
          <option value="">— {t('sheet.alignment').toLowerCase()}</option>
          {['LB','NB','CB','LN','N','CN','LM','NM','CM'].map((a) =>
            <option key={a} value={a}>{a}</option>)}
        </select>
        <input placeholder={t('sheet.playerName')} defaultValue={d.player_name}
               aria-label={t('sheet.playerName')} style={{ maxWidth: 160 }}
               onBlur={(e) => e.target.value !== (d.player_name || '') &&
                 set('player_name', e.target.value)} />
        <label className="muted">{t('sheet.speed')}
          <input type="number" min="0" step="5" style={{ maxWidth: 70 }}
                 defaultValue={d.speed ?? 30}
                 aria-label={t('sheet.speedAria')}
                 onBlur={(e) => +e.target.value !== d.speed &&
                   set('speed', +e.target.value)} />
          ft</label>
        {/* velocidades extra: vuelo, nado, trepa, excavar */}
        {[['fly', t('sheet.speedFly')], ['swim', t('sheet.speedSwim')],
          ['climb', t('sheet.speedClimb')],
          ['burrow', t('sheet.speedBurrow')]].map(([k, lbl]) => (
          <label key={k} className="muted">{lbl}
            <input type="number" min="0" step="5"
                   style={{ maxWidth: 62 }}
                   defaultValue={d.speeds?.[k] || ''}
                   placeholder="0"
                   aria-label={tf('sheet.speedOfAria', { name: lbl })}
                   onBlur={(e) => +e.target.value !==
                     (d.speeds?.[k] || 0) &&
                     set('speeds', { [k]: +e.target.value })} />
          </label>))}
        <label className="muted">{t('sheet.senses')}
          <input defaultValue={d.senses || ''}
                 placeholder={t('sheet.sensesPh')}
                 style={{ maxWidth: 180 }}
                 aria-label={t('sheet.senses')}
                 onBlur={(e) => e.target.value !== (d.senses || '') &&
                   set('senses', e.target.value)} />
        </label>
        <label className="muted">{t('sheet.rename')}
          <input defaultValue={name} style={{ maxWidth: 140 }}
                 aria-label={t('sheet.renameAria')}
                 onBlur={(e) => e.target.value &&
                   e.target.value !== name &&
                   set('name', e.target.value)} />
        </label>
      </div>
    </details>
  )
}


/** Rasgos ganados al subir de nivel — preview estilo D&D Beyond
    builder. La entidad 'level' del corpus es <class_id>-<n> en
    5e-bits; si no existe, busca por slug de clase + nivel. */
export function NextLevelFeatures({ classId, level }) {
  const { t } = useT()
  const [feats, setFeats] = useState(null)
  useEffect(() => {
    let alive = true
    setFeats(null)
    ;(async () => {
      let data = null
      try {
        const e = await api.getEntity(`${classId}-${level}`)
        if (e?.entity_type === 'level') data = e.data
      } catch { /* id no 5e-bits → búsqueda */ }
      if (!data) {
        try {
          const slug = classId.split(':').pop().split('|')[0]
          const want = slug.replaceAll('-', ' ').toLowerCase()
          const r = await api.search(`${slug} ${level}`, 'level')
          for (const cand of (r.results || []).slice(0, 4)) {
            const e2 = await api.getEntity(cand.id).catch(() => null)
            if (e2?.data?.level === level &&
                (e2.data?.class?.name || '').toLowerCase() === want) {
              data = e2.data
              break
            }
          }
        } catch { /* sin preview para esta fuente */ }
      }
      if (alive) setFeats(data ? (data.features || []) : [])
    })()
    return () => { alive = false }
  }, [classId, level])
  if (!feats?.length) return null
  return (
    <span className="muted" style={{ flexBasis: '100%', fontSize: '.8rem' }}>
      ▸ {t('lvlup.gains')}: {feats.map((f) => f.name || f).join(' · ')}
    </span>
  )
}
