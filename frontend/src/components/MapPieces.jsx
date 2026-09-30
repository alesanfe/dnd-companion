/** Capas SVG del mapa extraídas de MapBoard: token, pin y la cinta de
 *  iniciativa. Son componentes de presentación — la lógica de negocio
 *  (arrastre, ataques, alcance) sigue en MapBoard. */

/** Token del grid: círculo/imagen + anillos (selección, turno activo,
 *  zona pintada), badge de iniciativa, badge de condiciones, barra PG. */
export function MapToken({ tk, size, lx, ly, selected, active, zoneColor,
                          order, conds, hp, hpMax, movable, dragging,
                          onDown, onClick }) {
  // casillas que ocupa (grande 2×2, enorme 3×3…) — anchor = sup-izq
  const tsize = Math.max(1, +(tk.size || 1))
  const tr = tsize * size * .5 - 2
  const cx = (lx + tsize * .5) * size
  const cy = (ly + tsize * .5) * size
  return (
    <g onMouseDown={onDown} onClick={onClick}
       opacity={dragging ? .55 : 1}
       style={{ cursor: movable ? 'grab' : 'default' }}>
      {tk.image_url
        ? (<>
            <clipPath id={`clip-${tk.id}`}>
              <circle cx={cx} cy={cy} r={tr} />
            </clipPath>
            <image href={tk.image_url}
                   x={cx - tr} y={cy - tr}
                   width={tr * 2} height={tr * 2}
                   preserveAspectRatio="xMidYMid slice"
                   clipPath={`url(#clip-${tk.id})`} />
            <circle cx={cx} cy={cy} r={tr} fill="none"
                    stroke={selected ? '#fff' : active ? '#ffd700' : '#111'}
                    strokeWidth={selected || active ? 3 : 1} /> </>)
        : <circle cx={cx} cy={cy} r={tr} fill={tk.color}
                  stroke={selected ? '#fff' : active ? '#ffd700' : '#111'}
                  strokeWidth={selected || active ? 3 : 1} />}
      {/* halo de luz: el token que emite ilumina su radio (los muros
          recortan la luz en el render de niebla) */}
      {tk.light_ft > 0 && (
        <circle cx={cx} cy={cy}
                r={(tk.light_ft / (tk._cellFt || 5)) * size}
                fill="#f5c542" opacity=".10" pointerEvents="none" />)}
      {/* posición en la iniciativa del tracker */}
      {order && (
        <text x={cx - tsize * .45 * size}
              y={cy - tsize * .4 * size + size * .18}
              fill="#9cf" fontSize={size * .26}
              fontWeight="bold" pointerEvents="none">
          {order}</text>)}
      {/* sobre casilla pintada → anillo del color de la zona */}
      {zoneColor && (
        <circle cx={cx} cy={cy} r={tr + 4} fill="none"
                stroke={zoneColor} strokeWidth={2}
                strokeDasharray="4 3" opacity=".9" pointerEvents="none" />)}
      {/* turno activo en el tracker → anillo dorado pulsante */}
      {active && (
        <circle cx={cx} cy={cy} r={tr + 3} fill="none" stroke="#ffd700"
                strokeWidth={1.5}>
          <animate attributeName="opacity" values="1;.3;1"
                   dur="1.2s" repeatCount="indefinite" />
        </circle>)}
      {!tk.image_url && (
        <text x={cx} y={cy + tr * .5}
              textAnchor="middle" fill="#fff"
              fontSize={tr * .72} pointerEvents="none">
          {tk.name.slice(0, 2).toUpperCase()}</text>)}
      {/* insignia de condiciones (ficha vinculada o tracker) */}
      {conds?.length > 0 && (
        <circle cx={cx + tsize * .42 * size}
                cy={cy - tsize * .42 * size}
                r={size * .13} fill="#e67e22"
                stroke="#111" strokeWidth={1}>
          <title>{conds.join(', ')}</title>
        </circle>)}
      {hp != null && hpMax != null && (
        <g>
          <rect x={lx * size + 2} y={ly * size + 2}
                width={tsize * size - 4} height={4} rx={2}
                fill="#000" opacity=".6" />
          <rect x={lx * size + 2} y={ly * size + 2}
                width={(tsize * size - 4) * Math.max(0, hp / hpMax)}
                height={4} rx={2}
                fill={hp / hpMax > .5 ? '#27ae60'
                      : hp > 0 ? '#e67e22' : '#c0392b'} />
        </g>)}
    </g>)
}

/** Pin ligado a una entidad del mundo (📍 + nombre). */
export function MapPin({ p, ent, size, selected, onClick }) {
  return (
    <g onClick={onClick} style={{ cursor: 'pointer' }}
       opacity={selected ? 1 : .85}>
      <text x={(p.x + .5) * size} y={(p.y + .58) * size}
            textAnchor="middle" fontSize={size * .55}>
        📍</text>
      {ent && (
        <text x={(p.x + .5) * size} y={(p.y + .98) * size}
              textAnchor="middle" fill="#fff"
              stroke="#000" strokeWidth={size * .012}
              fontSize={size * .26} pointerEvents="none">
          {ent.name.slice(0, 16)}</text>)}
    </g>)
}

/** Cinta de iniciativa sobre el tablero: orden del tracker, turno
 *  activo dorado; clic → selecciona su token en el grid. */
export function InitiativeRibbon({ combatants, turnOrder, activeRef,
                                  activeName, tokens, selectable,
                                  onSelect, t, tf }) {
  const chips = [...combatants]
    .map((cb) => ({ cb, pos: turnOrder[cb.ref_id || cb.name] ??
                            turnOrder[cb.name] }))
    .filter((x) => x.pos != null)
    .sort((a, b) => a.pos - b.pos)
  if (!chips.length) return null
  return (
    <div className="row" style={{ gap: 4, flexWrap: 'wrap',
                                  margin: '2px 0' }}
         role="list" aria-label={t('map.initRibbonAria')}>
      {chips.map(({ cb, pos }) => {
        const isActive = (activeRef && cb.ref_id === activeRef) ||
                         (activeName && cb.name === activeName)
        const tk = tokens.find((t2) =>
          t2.combatant_id === cb.id ||
          (cb.ref_id && t2.ref_id === cb.ref_id) ||
          t2.name === cb.name)
        return (
          <button key={cb.id} role="listitem" className="ghost"
                  title={tk ? tf('map.initChipTitle', { name: cb.name })
                            : t('map.initChipNoTok')}
                  style={{ padding: '1px 6px', fontSize: '.8rem',
                           border: isActive
                             ? '1px solid #ffd700' : undefined,
                           color: isActive ? '#ffd700' : undefined,
                           opacity: tk ? 1 : .55 }}
                  onClick={() => tk && selectable(tk) && onSelect(tk)}>
            {pos}·{cb.name}
          </button>)
      })}
    </div>)
}
