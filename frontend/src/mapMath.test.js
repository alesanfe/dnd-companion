import { describe, expect, it } from 'vitest'
import { blockedByWall, inCone, segsCross } from './mapMath.js'

describe('segsCross', () => {
  it('cruce clásico en X', () => {
    expect(segsCross([0, 0], [2, 2], [0, 2], [2, 0])).toBe(true)
  })
  it('paralelos no cruzan', () => {
    expect(segsCross([0, 0], [2, 0], [0, 1], [2, 1])).toBe(false)
  })
  it('toque en punta no cuenta como cruce estricto', () => {
    // comparten extremo pero no se atraviesan
    expect(segsCross([0, 0], [1, 0], [1, 0], [1, 1])).toBe(false)
  })
})

describe('blockedByWall', () => {
  const walls = ['2,2,E']   // borde derecho de (2,2) = x=3, y∈[2,3]

  it('recta horizontal cruza el muro E', () => {
    expect(blockedByWall(walls, 2, 2, 4, 2)).toBe(true)
  })
  it('la vertical paralela no lo toca', () => {
    expect(blockedByWall(walls, 3, 0, 3, 5)).toBe(false)
  })
  it('quedarse a un lado no cruza', () => {
    expect(blockedByWall(walls, 1, 2, 2, 2)).toBe(false)
  })
  it('la diagonal que pasa por el borde también se ve', () => {
    // centro (2.5,2.5) → (4.5,1.5): cruza x=3 en y=2.25, dentro
    // del rango [2,3] del muro vertical
    expect(blockedByWall(walls, 2, 2, 4, 1)).toBe(true)
    // en cambio (2,1)→(4,2) pasa por encima (cruza x=3 en y=1.75)
    expect(blockedByWall(walls, 2, 1, 4, 2)).toBe(false)
  })
  it('la esquina exacta no cuenta (caso ambiguo)', () => {
    // de (2,1) a (4,3) roza solo la punta del muro en (3,2)
    expect(blockedByWall(walls, 2, 1, 4, 3)).toBe(false)
  })
  it('muro S: borde inferior de (0,0)', () => {
    expect(blockedByWall(['0,0,S'], 0, 0, 0, 2)).toBe(true)
  })
})

describe('inCone (53.13°)', () => {
  // cono hacia +x desde (0,0), largo 4 casillas
  it('eje recto dentro del alcance', () => {
    expect(inCone(0, 0, 4, 0, 4, 0)).toBe(true)
    expect(inCone(0, 0, 4, 0, 2, 0)).toBe(true)
  })
  it('fuera de alcance no cuenta', () => {
    expect(inCone(0, 0, 4, 0, 5, 0)).toBe(false)
  })
  it('el ancho crece con la distancia (ancho=largo)', () => {
    // a 4 de distancia el medio-cono abarca 2 de perpendicular
    expect(inCone(0, 0, 4, 0, 4, 2)).toBe(true)   // tan θ=.5 → en el límite
    expect(inCone(0, 0, 4, 0, 4, 3)).toBe(false)  // ya fuera del abanico
  })
  it('el ápice siempre dentro', () => {
    expect(inCone(0, 0, 4, 0, 0, 0)).toBe(true)
  })
  it('dirección cualquiera: cono hacia el sur', () => {
    expect(inCone(5, 5, 5, 9, 5, 8)).toBe(true)   // misma columna
    expect(inCone(5, 5, 5, 9, 9, 5)).toBe(false)  // perpendicular lejos
  })
})
