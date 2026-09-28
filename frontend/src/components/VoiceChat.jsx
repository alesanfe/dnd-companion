import { useEffect, useRef, useState } from 'react'
import { useT } from '../i18n.jsx'

/** Voz de mesa P2P: mesh WebRTC con señalización por la sala WS
    (mensaje 'rtc.signal' dirigido por uid — el servidor solo reenvía).
    Regla de polidez: el uid menor ofrece; evita ofertas cruzadas.
    Requiere cuenta (el uid anónimo no es direccionable). */
export default function VoiceChat({ sock, me, presence, rtcMsg }) {
  const { t } = useT()
  const [joined, setJoined] = useState(false)
  const [muted, setMuted] = useState(false)
  const [err, setErr] = useState(null)
  const peers = useRef({})   // uid → RTCPeerConnection
  const local = useRef(null) // MediaStream del mic
  const audios = useRef({})  // uid → Audio

  const send = (to, data) => {
    const s = sock?.current?.socket
    if (s?.readyState === 1)
      s.send(JSON.stringify({ type: 'rtc.signal', to, data }))
  }

  const pc = (uid) => {
    if (peers.current[uid]) return peers.current[uid]
    const p = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    })
    if (local.current)
      local.current.getTracks().forEach((tr) =>
        p.addTrack(tr, local.current))
    p.onicecandidate = (e) => {
      if (e.candidate) send(uid, { kind: 'ice',
                                 candidate: e.candidate.toJSON() })
    }
    p.ontrack = (e) => {
      if (!audios.current[uid]) {
        const a = new Audio()
        a.autoplay = true
        a.srcObject = e.streams[0]
        audios.current[uid] = a
      }
    }
    peers.current[uid] = p
    return p
  }

  const offer = async (uid) => {
    const p = pc(uid)
    try {
      await p.setLocalDescription(await p.createOffer())
      send(uid, { kind: 'sdp', sdp: p.localDescription })
    } catch { /* par desapareció */ }
  }

  const otherUids = (list) =>
    (list || []).map((m) => m.uid).filter((u) => u && u !== me)

  const join = async () => {
    try {
      local.current =
        await navigator.mediaDevices.getUserMedia({ audio: true })
      setJoined(true); setErr(null)
      // regla: el uid MENOR ofrece — cada lado solo ofrece a los
      // que le superan, evitando ofertas cruzadas
      for (const u of otherUids(presence)) {
        if (me && me < u) await offer(u)
      }
    } catch (e) {
      setErr(t('voice.micError'))
      setJoined(false)
    }
  }

  const leave = () => {
    for (const p of Object.values(peers.current)) p.close()
    peers.current = {}; audios.current = {}
    local.current?.getTracks().forEach((tr) => tr.stop())
    local.current = null
    setJoined(false)
  }

  const toggleMute = () => {
    const on = !muted
    local.current?.getAudioTracks()
      .forEach((tr) => { tr.enabled = !on })
    setMuted(on)
  }

  // señal entrante del par remoto
  useEffect(() => {
    if (!rtcMsg || !joined) return
    const uid = rtcMsg.from
    if (!uid || uid === me) return
    const d = rtcMsg.data || {}
    ;(async () => {
      const p = pc(uid)
      try {
        if (d.kind === 'sdp') {
          await p.setRemoteDescription(d.sdp)
          if (d.sdp.type === 'offer') {
            await p.setLocalDescription(await p.createAnswer())
            send(uid, { kind: 'sdp', sdp: p.localDescription })
          }
        } else if (d.kind === 'ice' && d.candidate) {
          await p.addIceCandidate(d.candidate)
        }
      } catch { /* señal fuera de orden — WebRTC lo tolera */ }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rtcMsg, joined])

  // alguien se unió después → yo ofrezco si mi uid es menor
  useEffect(() => {
    if (!joined || !me) return
    for (const u of otherUids(presence)) {
      if (me < u && !peers.current[u]) offer(u)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presence, joined])

  useEffect(() => () => leave(), [])  // desmontar → colgar

  if (!me) return null   // sin cuenta no hay uid direccionable
  return (
    <span className="row" style={{ gap: 2 }}>
      {!joined ? (
        <button className="ghost" title={t('voice.join')}
                aria-label={t('voice.join')}
                onClick={join}>🎙</button>
      ) : (<>
        <button className="ghost" title={t('voice.leave')}
                aria-label={t('voice.leave')}
                onClick={leave}>📞</button>
        <button className="ghost"
                title={muted ? t('voice.unmute') : t('voice.mute')}
                aria-pressed={muted}
                onClick={toggleMute}>
          {muted ? '🔇' : '🔊'}</button>
      </>)}
      {err && <span className="muted" role="alert">{err}</span>}
    </span>
  )
}
