import { Section } from './panels.jsx'
import { api } from '../../api.js'

/** Pestaña Actividad: historial de operaciones reversible +
    chat efímero de mesa (WS de la campaña). */
export default function TabActividad({ c }) {
  const { t, tf, focus, hud, tab, history, setHistory, load, char,
          chat = [], chatText = '', setChatText, sendChat } = c
  const show = (g) => focus ? hud.has(g) : tab === g
  if (!history && !char?.campaign_id) return null
  return (<>
    {char?.campaign_id && (
      <Section title={t('act.chat')}  hidden={!show('actividad')}
               extraClass="optional">
        <ul className="log" role="log" aria-live="polite">
          {chat.length === 0 &&
            <li className="muted">{t('act.chatEmpty')}</li>}
          {chat.map((m, i) => (
            <li key={i}><b>{m.from}</b>: {m.text}</li>))}
        </ul>
        <form onSubmit={sendChat} className="row">
          <input value={chatText} aria-label={t('act.chatAria')}
                 maxLength={500} placeholder={t('act.chatPh')}
                 onChange={(e) => setChatText(e.target.value)} />
          <button type="submit" disabled={!chatText.trim()}>
            {t('act.send')}</button>
        </form>
      </Section>)}
    {history && (
    <Section title={<>{t('sheet.history')} <span className="muted">{t('act.reversible')}</span></>}  hidden={!show('actividad')} extraClass="optional">
      {/* ops ya revertidas (alguien aplicó su inversa) quedan
          tachadas; las reversiones llevan ↺ y marcan a su objetivo */}
      {(() => {
        const undone = new Set(history.map((h) =>
          h.payload?._undoes).filter(Boolean))
        return history.map((h) => (
        <div key={h.operation_id} className="row">
          <span className="muted">{h.timestamp.slice(11, 19)}</span>
          <span style={{ flex: 1,
                         textDecoration: undone.has(h.operation_id)
                           ? 'line-through' : undefined }}
                className={undone.has(h.operation_id) ? 'muted' : ''}>
            {h.payload?._undoes ? `↺ ${h.operation_type}`
                                : h.operation_type}
            {undone.has(h.operation_id) && ` · ${t('act.undone')}`}
          </span>
          {h.reversible && !undone.has(h.operation_id) ? (
            <>
            <button onClick={async () => {
              try { await api.undoOp(h.operation_id) }
              catch { /* ya revertida o no reversible */ }
              setHistory(null)
              load()
            }}>{t('sheet.undoBtn')}</button>
            <button className="ghost"
                    title={t('act.undoToHere')}
                    onClick={async () => {
              const idx = history.indexOf(h)
              for (const x of history.slice(0, idx + 1)) {
                if (x.reversible)
                  try { await api.undoOp(x.operation_id) }
                  catch { /* ya revertida — seguir con la anterior */ }
              }
              setHistory(null)
              load()
            }}>{t('act.undoTo')}</button>
            </>
          ) : <span className="muted">—</span>}
        </div>))
      })()}
    </Section>)}
  </>)
}
