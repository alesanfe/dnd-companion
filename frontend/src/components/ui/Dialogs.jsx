import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { useT } from '../../i18n.jsx'

/* Diálogos modales para sustituir window.confirm/prompt:
   - focus trap básico + Esc + click-outside (prompt no cierra fuera
     porque perder texto es destructivo — sí lo hace confirm)
   - aria-modal + labelledby + el foco cae al primer control
   - uso: const { confirm, prompt } = useDialogs()
     if (await confirm(msg)) … / const v = await prompt(msg, def)   */

const Ctx = createContext(null)
export const useDialogs = () => useContext(Ctx)

function Dialog({ title, onClose, alert, children }) {
  const ref = useRef(null)
  useEffect(() => {
    // foco al primer control interactivo del diálogo
    ref.current?.querySelector('input, button.primary, button')
      ?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key !== 'Tab' || !ref.current) return
      // focus trap: cicla dentro de los controles del diálogo
      const els = ref.current.querySelectorAll(
        'input, select, textarea, button, [href]')
      if (!els.length) return
      const first = els[0], last = els[els.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="dlg-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose()
    }}>
      <div ref={ref} className="dlg"
           role={alert ? 'alertdialog' : 'dialog'}
           aria-modal="true" aria-labelledby="dlg-t">
        <h3 id="dlg-t">{title}</h3>
        {children}
      </div>
    </div>
  )
}

export function DialogProvider({ children }) {
  const { t } = useT()
  // {kind: 'confirm'|'prompt', title, def, resolve}
  const [req, setReq] = useState(null)
  const [value, setValue] = useState('')

  const confirm = (title) =>
    new Promise((res) => setReq({ kind: 'confirm', title, resolve: res }))
  const prompt = (title, def = '') =>
    new Promise((res) => {
      setValue(def ?? '')
      setReq({ kind: 'prompt', title, resolve: res })
    })

  const close = (result) => {
    req?.resolve(result)
    setReq(null)
  }

  return (
    <Ctx.Provider value={{ confirm, prompt }}>
      {children}
      {req?.kind === 'confirm' && (
        <Dialog alert title={req.title} onClose={() => close(false)}>
          <div className="dlg-actions">
            <button className="ghost" onClick={() => close(false)}>
              {t('common.cancel')}</button>
            <button className="dmg" onClick={() => close(true)}>
              {t('common.confirm')}</button>
          </div>
        </Dialog>)}
      {req?.kind === 'prompt' && (
        <Dialog title={req.title} onClose={() => close(null)}>
          <form onSubmit={(e) => { e.preventDefault(); close(value) }}>
            <input value={value} autoFocus
                   aria-label={req.title}
                   onChange={(e) => setValue(e.target.value)} />
            <div className="dlg-actions">
              <button type="button" className="ghost"
                      onClick={() => close(null)}>
                {t('common.cancel')}</button>
              <button type="submit" className="primary">
                {t('common.ok')}</button>
            </div>
          </form>
        </Dialog>)}
    </Ctx.Provider>
  )
}
