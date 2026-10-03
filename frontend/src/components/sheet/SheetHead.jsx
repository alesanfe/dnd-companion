import { SHEET_TABS } from './data.js'
import { onTabsKeyDown } from '../../a11y.js'

// cabecera pegajosa: vitales a mano + config del HUD + nav de pestañas
// — extraída de pages/CharacterSheet.jsx (AU-22)
export default function SheetHead({
  hp, derived, d, rollInit, op, focus, hud, setHud, tab, setTab,
  t, tf, tr,
}) {
  return (
    <div className="sticky-head">
      <div className="vital">
        <span className={`vstat hp${hp.max && hp.current / hp.max <= 0.5
              ? ' low' : ''}`}
              role="img"
              aria-label={tf('sheet.hpAria',
                             { cur: hp.current, max: hp.max })}>
          <i>PG</i>
          <b>{hp.current}/{hp.max}{hp.temp > 0 && `+${hp.temp}`}</b>
        </span>
        {derived && <>
          <span className="vstat"
                title={`CA = ${derived.armor_class.breakdown
                  .map(([n, v]) => `${n} ${v > 0 ? '+' : ''}${v}`)
                  .join(' ')}`}>
            <i>CA</i><b>{derived.armor_class.total}</b></span>
          <button className="vstat act"
                  title={tf('sheet.initTitle', {
                    mod: `${derived.initiative >= 0 ? '+' : ''}${
                      derived.initiative}`})}
                  aria-label={tf('sheet.initAria', {
                    mod: `${derived.initiative >= 0 ? '+' : ''}${
                      derived.initiative}`})}
                  onClick={() => rollInit('')}
                  onContextMenu={(e) => {
            e.preventDefault()
            rollInit(e.shiftKey ? 'dis' : 'adv')
          }}><i>Init</i><b>{derived.initiative >= 0 ? '+' : ''}
            {derived.initiative}</b></button>
          <span className="vstat"
                title={t('sheet.percTitle')}>
            <i>Perc</i><b>{derived.passive_perception}</b></span>
          <span className="vstat" title={t('sheet.profTitle')}>
            <i>Prof</i><b>+{derived.proficiency_bonus}</b></span>
          <span className="vstat"
                title={tf('sheet.speedTitle', { spd: d.speed ?? 30 }) +
                  Object.entries(d.speeds || {})
                    .map(([k, v]) => ` · ${
                      t('sheet.speedName.' + k) !==
                        'sheet.speedName.' + k
                        ? t('sheet.speedName.' + k) : k} ${v}`)
                    .join('') + t('sheet.speedTitleEnd')}>
            <i>Vel</i><b>{d.speed ?? 30}<small> ft</small>
              {(d.speeds?.fly || d.speeds?.swim) && (
                <small style={{ fontWeight: 'normal' }}>
                  {d.speeds.fly ? ' ✈' : ''}
                  {d.speeds.swim ? ' ≈' : ''}</small>)}</b></span>
        </>}
        <button className={`vstat act${d.inspiration ? ' on' : ''}`}
                aria-pressed={!!d.inspiration}
                title={d.inspiration ? t('sheet.inspSpend')
                                     : t('sheet.inspGain')}
                onClick={() => op('character.inspiration.set',
                                  { value: !d.inspiration })}>
          <i>Insp</i><b>✦</b></button>
        {d.concentrating_on &&
          <span className="chip">⭑ {d.concentrating_on}</span>}
        {(d.conditions || []).map((cname) =>
          <span key={cname} className="chip">{cname}
            {d.condition_stacks?.[cname] > 0 &&
              ` ×${d.condition_stacks[cname]}`}</span>)}
      </div>
      {focus && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {[['combat', ['resumen', 'acciones', 'magia']],
            ['explore', ['resumen', 'stats', 'inventario']],
            ['social', ['resumen', 'rasgos', 'historia']],
            ['all', SHEET_TABS.map(([k]) => k)]]
            .map(([p, groups]) => (
            <button key={p} className="ghost" style={{ fontSize: '.85em' }}
                    onClick={() => setHud(new Set(groups))}>
              {t('hud.' + p)}</button>))}
          <span className="muted">·</span>
          {SHEET_TABS.map(([k, label]) => (
              <label key={k} className="muted"
                     style={{ fontSize: '.85em' }}>
                <input type="checkbox" checked={hud.has(k)}
                  onChange={(e) => setHud((prev) => {
                    const nx = new Set(prev)
                    e.target.checked ? nx.add(k) : nx.delete(k)
                    return nx
                  })} />
                {tr('tab.' + k, label)}</label>))}
        </div>)}
      {!focus && (
        <nav className="tabs" role="tablist" aria-label={t('sheet.tabsAria')}
             onKeyDown={onTabsKeyDown}>
          {SHEET_TABS.map(([k, label, icon]) => (
              <button key={k} role="tab" aria-selected={tab === k}
                      onClick={() => setTab(k)}>
                <span className="ti" aria-hidden="true">{icon}</span>
                {tr('tab.' + k, label)}</button>))}
        </nav>)}
    </div>
  )
}
