import { getToken, currentUser } from './session.js'

/** WebSocket de sala de campaña con reconexión exponencial
    (1s→2s→…→15s). onOpen se llama en cada (re)conexión — usarlo
    para resync. onMessage recibe el JSON tal cual llega. El
    handle expone `.socket` (el WS vivo actual) y `.close()`. */
export function campaignSocket(campaignId, { onMessage, onOpen } = {}) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const uid = currentUser()?.user_id
  const tok = getToken()
  const url = `${proto}://${location.host}/ws/campaign/${campaignId}` +
    (tok ? `?token=${encodeURIComponent(tok)}`
         : uid ? `?user_id=${uid}` : '')
  const handle = { socket: null, closed: false }
  let delay = 1000, timer
  const connect = () => {
    if (handle.closed) return
    const ws = new WebSocket(url)
    handle.socket = ws
    ws.onopen = () => { delay = 1000; onOpen?.() }
    ws.onmessage = (m) => {
      // guard contra sockets obsoletos: tras reconectar, el viejo
      // no debe alimentar el feed
      if (handle.socket !== ws) return
      try { onMessage?.(JSON.parse(m.data)) } catch { /* suelto */ }
    }
    ws.onclose = () => {
      if (handle.closed || handle.socket !== ws) return
      timer = setTimeout(connect, delay)
      delay = Math.min(15000, delay * 2)
    }
  }
  handle.close = () => {
    handle.closed = true
    clearTimeout(timer)
    handle.socket?.close()
  }
  connect()
  return handle
}
