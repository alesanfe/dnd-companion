import MapBoard from '../MapBoard.jsx'

/** Pestaña Mapa: el tablero táctico pasa a ser un módulo propio
    en vez de ocupar siempre la pantalla de la mesa. */
export default function DmMapa({ c }) {
  const { dmTab, campaign, entities } = c
  if (!campaign || dmTab !== 'mapa') return null
  // entities = todas las entidades de campaña → pins enlazables
  return <MapBoard campaign={campaign} worldEntities={entities || []} />
}
