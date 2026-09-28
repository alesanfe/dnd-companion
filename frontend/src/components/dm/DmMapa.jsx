import MapBoard from '../MapBoard.jsx'

/** Pestaña Mapa: el tablero táctico pasa a ser un módulo propio
    en vez de ocupar siempre la pantalla de la mesa. */
export default function DmMapa({ c }) {
  const { dmTab, campaign, entities, partyChars, ping,
          ordered, activeIdx } = c
  if (!campaign || dmTab !== 'mapa') return null
  // entities = todas las entidades de campaña → pins enlazables;
  // partyChars → tokens vinculados a ficha (PG en vivo + nombre)
  // ref_id → posición en la iniciativa (badge sobre el token)
  const turnOrder = {}
  ;(ordered || []).forEach((cb, i) => {
    if (cb.ref_id) turnOrder[cb.ref_id] = i + 1 })
  return <MapBoard campaign={campaign} worldEntities={entities || []}
                   chars={partyChars || []} ping={ping}
                   activeRef={ordered?.[activeIdx]?.ref_id}
                   turnOrder={turnOrder} />
}
