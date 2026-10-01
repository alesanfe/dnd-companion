import MapBoard from '../MapBoard.jsx'

/** Pestaña Mapa: el tablero táctico pasa a ser un módulo propio
    en vez de ocupar siempre la pantalla de la mesa. */
export default function DmMapa({ c }) {
  const { dmTab, campaign, entities, partyChars, ping,
          ordered, activeIdx, combat, playerView } = c
  if (!campaign || dmTab !== 'mapa') return null
  // entities = todas las entidades de campaña → pins enlazables;
  // partyChars → tokens vinculados a ficha (PG en vivo + nombre)
  // iniciativa indexada por ref_id Y nombre — los monstruos no
  // tienen ficha y antes no llevaban badge ni anillo de turno
  const turnOrder = {}
  ;(ordered || []).forEach((cb, i) => {
    turnOrder[cb.ref_id || cb.name] = i + 1
    if (cb.name) turnOrder[cb.name] = i + 1
  })
  const active = ordered?.[activeIdx]
  return <MapBoard campaign={campaign} worldEntities={entities || []}
                   chars={partyChars || []} ping={ping}
                   readOnly={playerView}
                   activeRef={active?.ref_id} activeName={active?.name}
                   turnOrder={turnOrder}
                   combatants={combat?.combat?.combatants || []}
                   combat={combat} />
}
