/* i18n ligero: diccionario ES/EN + contexto. Idioma persistido en
   localStorage ('dnd-lang'); por defecto el del navegador.
   Uso:  const { t, lang, setLang } = useT()   →  t('nav.sheets') */
import { createContext, useContext, useEffect, useState } from 'react'

const KEY = 'dnd-lang'
const detect = () =>
  (localStorage.getItem(KEY) ||
   (navigator.language || 'es').split('-')[0]) === 'en' ? 'en' : 'es'

const LangCtx = createContext({ lang: 'es', setLang: () => {},
                                t: (k) => k })

export function LangProvider({ children }) {
  const [lang, setLang] = useState(detect)
  useEffect(() => {
    localStorage.setItem(KEY, lang)
    document.documentElement.lang = lang
  }, [lang])
  const t = (key) => STRINGS[lang]?.[key] ?? STRINGS.es[key] ?? key
  return (
    <LangCtx.Provider value={{ lang, setLang, t }}>
      {children}
    </LangCtx.Provider>)
}
export const useT = () => useContext(LangCtx)

/* ---- diccionario ---- */
const STRINGS = {
es: {
  'nav.sheets': 'Fichas', 'nav.campaigns': 'Campañas',
  'nav.compendium': 'Compendio', 'nav.dm': 'Mesa DM',
  'nav.create': 'Crear',
  'create.character': 'Personaje',
  'create.import': 'Importar personaje',
  'create.campaign': 'Campaña / mesa',
  'create.content': 'Contenido (compendio)',

  'sync.online': 'en línea', 'sync.offline': 'sin conexión',
  'sync.pending': 'pendientes de sincronizar',
  'sync.conflicts': 'conflictos', 'sync.conflict.hint': 'rechazado por conflicto de versión — tu dato local queda en el dispositivo',
  'account.login': 'Entrar', 'account.logout': 'Salir',
  'account.user': 'usuario', 'account.pass': 'contraseña',

  'charlist.title': 'Personajes',
  'charlist.new': '＋ Nuevo',
  'charlist.search': 'buscar…',
  'charlist.import': 'Importar JSON',
  'charlist.empty': 'Sin personajes aún — crea o importa uno.',
  'charlist.sort.name': 'Nombre', 'charlist.sort.recent': 'Recientes',
  'charlist.sort.level': 'Nivel',
  'charlist.synced': 'sincronizado', 'charlist.offline': 'local',

  'tab.resumen': 'Resumen', 'tab.acciones': 'Acciones',
  'tab.stats': 'Características', 'tab.magia': 'Magia',
  'tab.inventario': 'Inventario', 'tab.rasgos': 'Rasgos',
  'tab.historia': 'Historia', 'tab.actividad': 'Actividad',

  'sheet.hp': 'Puntos de golpe', 'sheet.xp': 'Experiencia',
  'sheet.levelup': 'Subir de nivel', 'sheet.rests': 'Descansos',
  'sheet.short': 'Descanso corto', 'sheet.long': 'Descanso largo',
  'sheet.conditions': 'Condiciones', 'sheet.limited': 'Usos limitados',
  'sheet.slots': 'Espacios de conjuro', 'sheet.spells': 'Conjuros',
  'sheet.known': 'Conocidos', 'sheet.prepared': 'Preparados',
  'sheet.inventory': 'Inventario', 'sheet.equipped': 'Equipado',
  'sheet.backpack': 'Mochila', 'sheet.consumables': 'Consumibles',
  'sheet.currency': 'Monedas', 'sheet.features': 'Rasgos',
  'sheet.feats': 'Dotes', 'sheet.languages': 'Idiomas',
  'sheet.effects': 'Efectos activos', 'sheet.journal': 'Diario',
  'sheet.history': 'Historial de operaciones',
  'sheet.favorites': 'Favoritos', 'sheet.actions': 'Acciones',
  'sheet.note': 'Nota rápida', 'sheet.deathsaves': 'salvaciones de muerte',
  'sheet.damage': 'Daño', 'sheet.heal': 'Curar',
  'sheet.attack': 'Atacar', 'sheet.cast': 'Lanzar',
  'sheet.undo': '↩ Deshacer', 'sheet.export': 'Exportar',
  'sheet.print': 'Imprimir', 'sheet.history.btn': 'Historial',
  'sheet.focus': 'Modo partida', 'sheet.advanced': 'Edición avanzada (puntuaciones y nombre)',
  'sheet.rounds': 'rondas', 'sheet.apply': 'Aplicar',
  'sheet.tick': '⏱ +1 ronda', 'sheet.write': 'Anotar',
  'sheet.rollreq': 'El DM pide una tirada',
  'sheet.derived': 'Calculado', 'sheet.dice': 'Dados',

  'dm.session': 'Sesión', 'dm.combat': 'Combate', 'dm.campaign': 'Campaña',
  'dm.newcombat': 'Nuevo combate', 'dm.next': 'Siguiente turno',
  'dm.end': 'Terminar', 'dm.init': 'Tirar inits',
  'dm.difficulty': 'Dificultad de encuentro',
  'dm.entities': 'Entidades de campaña',
  'dm.feed': 'Tiradas de la mesa', 'dm.playerView': '👁 Vista jugador',
  'dm.playerViewOn': '🙈 Vista jugador: ON',
  'dm.exportvtt': 'Exportar VTT', 'dm.reveal': 'Revelar',
  'dm.condition': 'Condición',
  'dm.allRolls': 'todas', 'dm.newEvents': 'evento',
  'dm.sessions': 'Sesiones y preparación',
  'dm.rollreq': 'Pedir tirada a un jugador',
  'dm.addcombatant': 'Añadir combatiente',
  'dm.initiative': 'Iniciativa',

  'search.title': 'Buscador de reglas',
  'search.placeholder': 'fireball — o /monster cr:1..5 type:undead',
  'search.type': 'Tipo de entidad', 'search.edition': 'Edición',
  'search.source': 'Fuente de contenido',
  'search.allSources': 'todas las fuentes',
  'search.button': 'Buscar', 'search.ask': 'Preguntar a las reglas',
  'search.favorites': '★ Favoritos', 'search.recent': 'Recientes',
  'search.recentQueries': 'Búsquedas recientes',
  'search.collections': 'Colecciones',
  'search.empty': 'Sin resultados — prueba otro término, quita filtros o busca en otra fuente.',
  'search.homebrew': '+ Contenido homebrew',
  'search.assistant': 'Asistente de reglas',
  'search.compare': 'Comparar',

  'camp.title': 'Campañas', 'camp.new': '＋ Nueva campaña',
  'camp.name': 'Nombre', 'camp.invite': 'Código de invitación',
  'camp.join': 'Unirse', 'camp.open': 'Abrir',
  'camp.yours': 'Tus campañas', 'camp.empty': 'Sin campañas.',
  'camp.characters': 'Personajes de la campaña',
  'camp.rolls': 'Tiradas recientes',
  'camp.nothingRevealed': 'El DM aún no ha revelado nada.',

  'wiz.title': 'Nuevo personaje', 'wiz.next': 'Siguiente',
  'wiz.back': 'Atrás', 'wiz.finish': 'Crear personaje',
  'wiz.name': 'Nombre', 'wiz.class': 'Clase', 'wiz.species': 'Especie',
  'wiz.background': 'Trasfondo', 'wiz.abilities': 'Puntuaciones',
  'wiz.summary': 'Resumen',

  'entity.copy': 'Copiar', 'entity.fav': 'Favorito',
  'entity.collection': 'Colección', 'entity.addChar': '＋ PJ',
  'entity.editions': 'Otras ediciones:', 'entity.diff': 'difieren:',
  'entity.back': '← Volver al buscador',

  'palette.placeholder': 'Buscar acciones…',
  'common.cancel': 'Cancelar', 'common.close': 'Cerrar',
  'common.save': 'Guardar', 'common.delete': 'Borrar',
  'common.loading': 'Cargando…', 'common.use': 'Usar',
  'common.add': 'Añadir', 'common.details': 'Detalles',
  'common.forget': 'Olvidar', 'common.pin': 'Fijar',
},

en: {
  'nav.sheets': 'Sheets', 'nav.campaigns': 'Campaigns',
  'nav.compendium': 'Compendium', 'nav.dm': 'DM Table',
  'nav.create': 'Create',
  'create.character': 'Character',
  'create.import': 'Import character',
  'create.campaign': 'Campaign / table',
  'create.content': 'Content (compendium)',

  'sync.online': 'online', 'sync.offline': 'offline',
  'sync.pending': 'pending sync',
  'sync.conflicts': 'conflicts', 'sync.conflict.hint': 'rejected due to version conflict — local data kept on this device',
  'account.login': 'Sign in', 'account.logout': 'Sign out',
  'account.user': 'username', 'account.pass': 'password',

  'charlist.title': 'Characters',
  'charlist.new': '＋ New',
  'charlist.search': 'search…',
  'charlist.import': 'Import JSON',
  'charlist.empty': 'No characters yet — create or import one.',
  'charlist.sort.name': 'Name', 'charlist.sort.recent': 'Recent',
  'charlist.sort.level': 'Level',
  'charlist.synced': 'synced', 'charlist.offline': 'local',

  'tab.resumen': 'Summary', 'tab.acciones': 'Actions',
  'tab.stats': 'Ability Scores', 'tab.magia': 'Magic',
  'tab.inventario': 'Inventory', 'tab.rasgos': 'Traits',
  'tab.historia': 'Story', 'tab.actividad': 'Activity',

  'sheet.hp': 'Hit Points', 'sheet.xp': 'Experience',
  'sheet.levelup': 'Level Up', 'sheet.rests': 'Rests',
  'sheet.short': 'Short Rest', 'sheet.long': 'Long Rest',
  'sheet.conditions': 'Conditions', 'sheet.limited': 'Limited Uses',
  'sheet.slots': 'Spell Slots', 'sheet.spells': 'Spells',
  'sheet.known': 'Known', 'sheet.prepared': 'Prepared',
  'sheet.inventory': 'Inventory', 'sheet.equipped': 'Equipped',
  'sheet.backpack': 'Backpack', 'sheet.consumables': 'Consumables',
  'sheet.currency': 'Currency', 'sheet.features': 'Features',
  'sheet.feats': 'Feats', 'sheet.languages': 'Languages',
  'sheet.effects': 'Active Effects', 'sheet.journal': 'Journal',
  'sheet.history': 'Operation History',
  'sheet.favorites': 'Favorites', 'sheet.actions': 'Actions',
  'sheet.note': 'Quick Note', 'sheet.deathsaves': 'death saves',
  'sheet.damage': 'Damage', 'sheet.heal': 'Heal',
  'sheet.attack': 'Attack', 'sheet.cast': 'Cast',
  'sheet.undo': '↩ Undo', 'sheet.export': 'Export',
  'sheet.print': 'Print', 'sheet.history.btn': 'History',
  'sheet.focus': 'Play Mode', 'sheet.advanced': 'Advanced editing (scores & name)',
  'sheet.rounds': 'rounds', 'sheet.apply': 'Apply',
  'sheet.tick': '⏱ +1 round', 'sheet.write': 'Add note',
  'sheet.rollreq': 'The DM requests a roll',
  'sheet.derived': 'Computed', 'sheet.dice': 'Dice',

  'dm.session': 'Session', 'dm.combat': 'Combat', 'dm.campaign': 'Campaign',
  'dm.newcombat': 'New combat', 'dm.next': 'Next turn',
  'dm.end': 'End', 'dm.init': 'Roll inits',
  'dm.difficulty': 'Encounter difficulty',
  'dm.entities': 'Campaign entities',
  'dm.feed': 'Table rolls', 'dm.playerView': '👁 Player view',
  'dm.playerViewOn': '🙈 Player view: ON',
  'dm.exportvtt': 'Export VTT', 'dm.reveal': 'Reveal',
  'dm.condition': 'Condition',
  'dm.allRolls': 'all', 'dm.newEvents': 'event',
  'dm.sessions': 'Sessions & prep',
  'dm.rollreq': 'Request a roll from a player',
  'dm.addcombatant': 'Add combatant',
  'dm.initiative': 'Initiative',

  'search.title': 'Rules search',
  'search.placeholder': 'fireball — or /monster cr:1..5 type:undead',
  'search.type': 'Entity type', 'search.edition': 'Edition',
  'search.source': 'Content source',
  'search.allSources': 'all sources',
  'search.button': 'Search', 'search.ask': 'Ask the rules',
  'search.favorites': '★ Favorites', 'search.recent': 'Recent',
  'search.recentQueries': 'Recent searches',
  'search.collections': 'Collections',
  'search.empty': 'No results — try another term, remove filters or search another source.',
  'search.homebrew': '+ Homebrew content',
  'search.assistant': 'Rules assistant',
  'search.compare': 'Compare',

  'camp.title': 'Campaigns', 'camp.new': '＋ New campaign',
  'camp.name': 'Name', 'camp.invite': 'Invite code',
  'camp.join': 'Join', 'camp.open': 'Open',
  'camp.yours': 'Your campaigns', 'camp.empty': 'No campaigns.',
  'camp.characters': 'Campaign characters',
  'camp.rolls': 'Recent rolls',
  'camp.nothingRevealed': 'The DM has revealed nothing yet.',

  'wiz.title': 'New character', 'wiz.next': 'Next',
  'wiz.back': 'Back', 'wiz.finish': 'Create character',
  'wiz.name': 'Name', 'wiz.class': 'Class', 'wiz.species': 'Species',
  'wiz.background': 'Background', 'wiz.abilities': 'Ability scores',
  'wiz.summary': 'Summary',

  'entity.copy': 'Copy', 'entity.fav': 'Favorite',
  'entity.collection': 'Collection', 'entity.addChar': '＋ PC',
  'entity.editions': 'Other editions:', 'entity.diff': 'differ:',
  'entity.back': '← Back to search',

  'palette.placeholder': 'Search actions…',
  'common.cancel': 'Cancel', 'common.close': 'Close',
  'common.save': 'Save', 'common.delete': 'Delete',
  'common.loading': 'Loading…', 'common.use': 'Use',
  'common.add': 'Add', 'common.details': 'Details',
  'common.forget': 'Forget', 'common.pin': 'Pin',
},
}
