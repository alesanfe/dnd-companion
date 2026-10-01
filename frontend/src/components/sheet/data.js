/* Constantes compartidas por las pestañas de la ficha de personaje. */

/** abreviatura → nombre largo (la ficha serializa 'strength', no 'str') */
export const AB_LONG = {
  str: 'strength', dex: 'dexterity', con: 'constitution',
  int: 'intelligence', wis: 'wisdom', cha: 'charisma',
}

/** Lee la puntuación con cualquiera de los dos formatos de clave. */
export const abilityScore = (abilities, ab) =>
  abilities?.[AB_LONG[ab]] ?? abilities?.[ab] ?? 10

/** [id, etiqueta, habilidades] — agrupación de la hoja oficial 2024. */
export const STATS = [
  ['str', 'Fuerza', [['athletics', 'Atletismo']]],
  ['dex', 'Destreza', [['acrobatics', 'Acrobacias'],
                      ['sleight-of-hand', 'Juego de manos'],
                      ['stealth', 'Sigilo']]],
  ['con', 'Constitución', []],
  ['int', 'Inteligencia', [['arcana', 'Arcana'], ['history', 'Historia'],
                          ['investigation', 'Investigación'],
                          ['nature', 'Naturaleza'],
                          ['religion', 'Religión']]],
  ['wis', 'Sabiduría', [['animal-handling', 'Trato animal'],
                       ['insight', 'Perspicacia'],
                       ['medicine', 'Medicina'],
                       ['perception', 'Percepción'],
                       ['survival', 'Supervivencia']]],
  ['cha', 'Carisma', [['deception', 'Engaño'],
                      ['intimidation', 'Intimidación'],
                      ['performance', 'Interpretación'],
                      ['persuasion', 'Persuasión']]],
]

/** ids de habilidad → etiqueta ES (los ids son canónicos SRD). */
export const SKILL_ES = {
  'athletics': 'Atletismo', 'acrobatics': 'Acrobacias',
  'sleight-of-hand': 'Juego de manos', 'stealth': 'Sigilo',
  'arcana': 'Arcana', 'history': 'Historia',
  'investigation': 'Investigación', 'nature': 'Naturaleza',
  'religion': 'Religión', 'animal-handling': 'Trato animal',
  'insight': 'Perspicacia', 'medicine': 'Medicina',
  'perception': 'Percepción', 'survival': 'Supervivencia',
  'deception': 'Engaño', 'intimidation': 'Intimidación',
  'performance': 'Interpretación', 'persuasion': 'Persuasión',
}

export const RESET_ORDER = ['short', 'dawn', 'long', 'none']
export const RESET_LABELS = { short: 'Descanso corto', dawn: 'Al amanecer',
                       long: 'Descanso largo', none: 'Sin recuperación' }

/** Presets de trackers de clase (PHB 2014) — estilo Fight Club:
    [nombre, usos máximos en función del nivel total, reset_on]. */
export const TRACKER_PRESETS = [
  ['Rage', (lv) => lv >= 17 ? 6 : lv >= 12 ? 5 : lv >= 6 ? 4
                 : lv >= 3 ? 3 : 2, 'long'],
  ['Second Wind', () => 1, 'short'],
  ['Action Surge', (lv) => lv >= 17 ? 2 : 1, 'short'],
  ['Superiority Dice', (lv) => lv >= 15 ? 6 : lv >= 7 ? 5 : 4, 'short'],
  ['Ki', (lv) => lv, 'short'],
  ['Lay on Hands', (lv) => lv * 5, 'long'],
  ['Channel Divinity', () => 1, 'short'],
  ['Sorcery Points', (lv) => lv, 'long'],
  ['Wild Shape', () => 2, 'short'],
  ['Lucky', () => 3, 'long'],
]

/** Efecto mecánico SRD de la condición — espejo de
    domain/conditions.py (los nombres en ES se muestran tal cual). */
export const COND_RULES = {
  blinded: 'Desventaja en ataques', cegado: 'Desventaja en ataques',
  cegada: 'Desventaja en ataques',
  invisible: 'Ventaja en ataques',
  poisoned: 'Desventaja en ataques y pruebas',
  envenenado: 'Desventaja en ataques y pruebas',
  envenenada: 'Desventaja en ataques y pruebas',
  prone: 'Desventaja en ataques', tumbado: 'Desventaja en ataques',
  derribado: 'Desventaja en ataques', postrado: 'Desventaja en ataques',
  restrained: 'Desventaja en ataques y salvaciones de DES',
  apresado: 'Desventaja en ataques y salvaciones de DES',
  apresada: 'Desventaja en ataques y salvaciones de DES',
  frightened: 'Desventaja en ataques y pruebas',
  asustado: 'Desventaja en ataques y pruebas',
  atemorizado: 'Desventaja en ataques y pruebas',
  stunned: 'Incapacitado · autofallo STR/DES', aturdido: 'Incapacitado · autofallo STR/DES',
  aturdida: 'Incapacitado · autofallo STR/DES',
  paralyzed: 'Incapacitado · autofallo STR/DES',
  paralizado: 'Incapacitado · autofallo STR/DES',
  paralizada: 'Incapacitado · autofallo STR/DES',
  petrified: 'Incapacitado · autofallo STR/DES',
  petrificado: 'Incapacitado · autofallo STR/DES',
  unconscious: 'Incapacitado · autofallo STR/DES',
  inconsciente: 'Incapacitado · autofallo STR/DES',
  incapacitated: 'Sin acciones ni reacciones',
  incapacitado: 'Sin acciones ni reacciones',
  incapacitada: 'Sin acciones ni reacciones',
  exhaustion: 'Desventaja en pruebas (3+: también ataques y saves)',
  exhausto: 'Desventaja en pruebas (3+: también ataques y saves)',
  agotado: 'Desventaja en pruebas (3+: también ataques y saves)',
  grappled: 'Velocidad 0', agarrado: 'Velocidad 0',
  agarrada: 'Velocidad 0',
  dead: 'Muerto', muerto: 'Muerto', muerta: 'Muerto',
}

// orden y etiquetas de las pestañas de la ficha — compartido por la
// página (ruta /character/:id/:tab) y la cabecera (nav + HUD)
export const SHEET_TABS = [
  ['resumen', 'Resumen', '✦'], ['acciones', 'Acciones', '⚔'],
  ['stats', 'Características', '🛡'], ['magia', 'Magia', '✨'],
  ['inventario', 'Inventario', '🎒'], ['rasgos', 'Rasgos', '📜'],
  ['historia', 'Historia', '✎'], ['actividad', 'Actividad', '🕓'],
]
