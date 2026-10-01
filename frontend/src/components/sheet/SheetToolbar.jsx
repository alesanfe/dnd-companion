import { api } from '../../api.js'

// barra de acciones de la ficha — extraída de pages/CharacterSheet.jsx
// (AU-22); los handlers vienen del padre por props
export default function SheetToolbar({
  char, focus, hudSize, setHud, setFocus, lvlPanel, setLvlPanel,
  history, setHistory, notify, toggleNotify, setErr, load, t,
}) {
  return (
    <div className="toolbar">
      <button className={focus ? 'ghost' : 'primary'}
              aria-pressed={focus}
              onClick={() => {
                if (!focus && hudSize <= 1)
                  // modo partida entra con el preset de combate —
                  // HUD personalizable si el usuario lo cambió antes
                  setHud(new Set(['resumen', 'acciones', 'magia']))
                setFocus(!focus)
              }}>
        {focus ? `⏻ ${t('sheet.focusOff')}` : `⚔ ${t('sheet.focus')}`}
      </button>
      {char.data.classes?.length > 0 && (
        <button aria-expanded={lvlPanel}
                onClick={() => setLvlPanel(!lvlPanel)}>
          {t('sheet.levelup')} ▾
        </button>
      )}
      <span className="tsep" />
      <button className="ghost" onClick={async () => {
        try {
          const h = await api.opHistory(char.id)
          const last = (h.operations || []).find((o) => o.reversible)
          if (last) { await api.undoOp(last.operation_id); load() }
        } catch (e) { setErr(e.message) }
      }}>{t('sheet.undo')}</button>
      <button className="ghost" onClick={async () => {
        try {
          const h = await api.opHistory(char.id)
          setHistory(history ? null : h.operations)
        } catch (e) { setErr(e.message) }
      }}>{t('sheet.history.btn')}</button>
      <button className="ghost" onClick={async () => {
        try {
          const ex = await api.exportCharacter(char.id)
          const blob = new Blob([JSON.stringify(ex, null, 2)],
                                { type: 'application/json' })
          const a = document.createElement('a')
          a.href = URL.createObjectURL(blob)
          a.download = `${char.name}.json`
          a.click()
        } catch (e) { setErr(e.message) }
      }}>{t('sheet.export')}</button>
      {/* el navegador nombra el PDF con document.title — fijarlo
          al nombre del PJ durante la impresión */}
      <button className="ghost" onClick={() => {
        const prev = document.title
        document.title = char.name || prev
        window.print()
        document.title = prev
      }}>
        🖨 {t('sheet.print')}</button>
      {char.campaign_id && (
        <button className="ghost" aria-pressed={notify}
                title={t('sheet.notifyHint')}
                onClick={toggleNotify}>
          {notify ? '🔔' : '🔕'}</button>)}
    </div>
  )
}
