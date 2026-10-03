/* ErrorBoundary: un fallo de render en una pantalla no debe dejar la
   app en blanco — muestra un estado de error con vía de recuperación
   (recargar) en lugar de un árbol desmontado sin feedback. */
import { Component } from 'react'
import { useT } from '../i18n.jsx'

function Fallback() {
  const { t } = useT()
  return (
    <main>
      <h1>{t('err.title')}</h1>
      <p className="muted">{t('err.hint')}</p>
      <button className="primary"
              onClick={() => location.reload()}>{t('err.reload')}</button>
    </main>)
}

export default class ErrorBoundary extends Component {
  state = { err: null }
  static getDerivedStateFromError(err) { return { err } }
  render() {
    return this.state.err ? <Fallback /> : this.props.children
  }
}
