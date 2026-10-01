/* Geometría pura del mapa — extraída para tests unitarios. */

// distancia en pies entre el centro de dos celdas
export const cellDist = (x1, y1, x2, y2, ft) =>
  Math.hypot(x2 - x1, y2 - y1) * ft

// constantes del grid compartidas por MapBoard y sus subpiezas
export const CELL = 44
export const MARK_COLORS = ['#27ae60', '#2980b9', '#c0392b', '#f39c12',
                            '#8e44ad', '#7f8c8d']
export const MAP_DEFAULTS = { cols: 16, rows: 10, cell_ft: 5,
                              tokens: [], fog: [], marks: {},
                              pins: [], walls: [] }

// segmento (p→q) cruza segmento (a→b)? test de orientación estándar
const _cross = (o, a, b) =>
  (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
export const segsCross = (p, q, a, b) => {
  const d1 = _cross(a, b, p), d2 = _cross(a, b, q)
  const d3 = _cross(p, q, a), d4 = _cross(p, q, b)
  return (d1 > 0 && d2 < 0 || d1 < 0 && d2 > 0) &&
         (d3 > 0 && d4 < 0 || d3 < 0 && d4 > 0)
}

// el segmento token→celda (centros) cruza algún muro? coordenadas
// de celda; 'x,y,E' borde derecho, 'x,y,S' borde inferior
export const blockedByWall = (walls, x1, y1, x2, y2) =>
  walls.some((w) => {
    const [wx, wy, ws] = w.split(',')
    const X = +wx, Y = +wy
    const [a, b] = ws === 'E'
      ? [[X + 1, Y], [X + 1, Y + 1]]
      : [[X, Y + 1], [X + 1, Y + 1]]
    return segsCross([x1 + .5, y1 + .5], [x2 + .5, y2 + .5], a, b)
  })

// cono 5e: ¿la celda (x,y) está en el cono desde el ápice con el
// ancho = largo? apertura 53.13° (D&D: ancho = largo en cada punto)
export const inCone = (x1, y1, x2, y2, x, y) => {
  const len = Math.hypot(x2 - x1, y2 - y1) + .5
  const dd = Math.hypot(x - x1, y - y1)
  if (dd > len) return false
  if (dd < 0.01) return true                       // el ápice
  const ang = Math.atan2(y2 - y1, x2 - x1)
  let da = Math.atan2(y - y1, x - x1) - ang
  while (da > Math.PI) da -= 2 * Math.PI
  while (da < -Math.PI) da += 2 * Math.PI
  return Math.abs(da) <= Math.atan(.5) + .02       // 53.13°/2
}
