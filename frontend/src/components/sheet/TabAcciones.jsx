import { useEffect } from 'react'
import { Section } from './panels.jsx'
import { api } from '../../api.js'

/** Pestaña Acciones: acciones agrupadas, efectos activos y dados. */
export default function TabAcciones({ c }) {
  const { id, char, d, op, t, tf, focus, hud, tab,
          actions, setActions, expr, setExpr, rollType, setRollType,
          doRoll, rollLog, setRollLog, setNotice } = c
  const show = (g) => focus ? hud.has(g) : tab === g

  /* las acciones se cargan solas al abrir la pestaña la primera
     vez — patrón Fight Club: todo lo tirable a la vista */
  const loadActions = async () => {
    const r = await api.characterActions(id)
    setActions(r.actions)
  }
  useEffect(() => {
    if (actions !== null || !show('acciones')) return
    let alive = true
    api.characterActions(id)
      .then((r) => { if (alive) setActions(r.actions) })
      .catch(() => {})
    return () => { alive = false }
    // hud en deps: en modo focus, marcar 'acciones' en el HUD debe
    // disparar la carga — show() depende de hud, no de tab
  }, [tab, focus, hud, id, actions])

  return (<div className="sheet-cols">
    <Section title={t('sheet.actions')}  hidden={!show('acciones')}>
      {actions && (
        <button className="ghost" onClick={() => setActions(null)}>
          {t('acc.hide')}</button>)}
      {actions === null && (
        <button onClick={loadActions}>{t('acc.show')}</button>)}
      {actions && Object.entries(actions).map(([g, list]) => (
        <div key={g}>
          <h3 className="muted" style={{ textTransform: 'capitalize' }}>{g.replace('_', ' ')}</h3>
          <ul>{list.map((a, i) => {
            const isAtk = a.name.startsWith('Ataque:')
            const isSpell = a.name.startsWith('Conjuro:')
            const label = a.name.replace(/^Ataque: |^Conjuro: /, '')
            return (
            <li key={i} className="action-row">
              {isAtk && (
                <button className="primary act-btn"
                        aria-label={tf('acc.attackWith', { name: label })}
                        onClick={async () => {
                  try {
                    // maestría 2024: el arma la declara, el motor la
                    // aplica (flex/graze) o la anota (cleave/nick)
                    const heroic = char.ruleset === 'dnd5e-2024' ||
                                   d.ruleset === 'dnd5e-2024'
                    const r = await api.characterAttack(
                      id, label, 'normal', null,
                      heroic && !!a.mastery)
                    setRollLog((l) => [
                      `${label}: ${t('acc.hit')} ${r.hit.total}` +
                      (r.damage ? ` · ${t('acc.dmg')} ${
                        r.damage.total}` : '') +
                      (r.mastery ? ` ⚒${r.mastery}` : ''),
                      ...l].slice(0, 10))
                  } catch (e) { setNotice(e.message) }
                }}>⚔</button>)}
              {isSpell && (
                <button className="act-btn"
                        aria-label={tf('acc.cast', { name: label })}
                        onClick={async () => {
                  await op('character.spell.cast',
                           { spell_id: a.source, level: 0 })
                }}>✦</button>)}
              <span className="action-name">{label}</span>
              {a.hit && <span className="muted"> {a.hit} · {a.damage}</span>}
              {a.mastery && (
                <span className="chip" title={t('acc.mastery')}>
                  ⚒{a.mastery}</span>)}
              <button className="ghost" style={{ minHeight: 28 }}
                      title={t('acc.pinTitle')}
                      aria-label={tf('acc.pinAria', { name: a.name })}
                      onClick={() => op('character.pin',
                        { id: a.source || a.name })}>
                📌</button>
            </li>)})}
          </ul>
        </div>
      ))}
    </Section>

    {(d.effects || []).length > 0 && (
      <Section title={t('sheet.effects')}  hidden={!show('acciones')} extraClass="optional">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {d.effects.map((e) => (
            <span key={e.id} className="chip" title={e.source}>
              {e.name}
              <button aria-label={tf('acc.effectRemove', { name: e.name })}
                      onClick={() =>
                op('character.effect.remove', { effect_id: e.id })}>×</button>
            </span>
          ))}
        </div>
      </Section>
    )}

    <Section title={t('sheet.dice')}  hidden={!show('acciones')}>
      <form onSubmit={doRoll} className="row">
        <input value={expr} onChange={(e) => setExpr(e.target.value)}
               aria-label={t('acc.expression')}
               placeholder="2d6+3, 1d20adv, 4d6kh3" />
        <select value={rollType} onChange={(e) => setRollType(e.target.value)}>
          <option value="check">{t('acc.check')}</option>
          <option value="attack">{t('acc.attack')}</option>
          <option value="damage">{t('acc.damage')}</option>
          <optgroup label={t('acc.saves')}>
            {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
              <option key={a} value={`save:${a}`}>
                {t('acc.save')} {t(`stat.${a}`)}</option>))}
          </optgroup>
          <optgroup label={t('acc.skills')}>
            {['perception', 'stealth', 'athletics',
              'insight', 'investigation', 'persuasion']
              .map((s) => <option key={s} value={`skill:${s}`}>
                {t(`skill.${s}`)}</option>)}
          </optgroup>
        </select>
        <button type="submit">{t('sheet.roll')}</button>
      </form>
      {/* bandeja de dados — un toque = una tirada (Fight Club/Owlbear);
          d20 también con ventaja/desventaja */}
      <div className="row" style={{ flexWrap: 'wrap', marginTop: '.3rem' }}
           role="group" aria-label={t('dice.trayAria')}>
        {['d4', 'd6', 'd8', 'd10', 'd12', 'd20', 'd100'].map((die) => (
          <button key={die} className="ghost" style={{ minWidth: 48 }}
                  aria-label={tf('dice.rollAria', { die })}
                  onClick={async () => {
            const ex = `1${die}`
            try {
              const r = await api.characterRoll(id, ex, rollType)
              setRollLog((l) => [
                `${r.expression} → ${r.kept.join('+')} = ${r.total}${
                  (r.effects_applied || []).length
                    ? ` [${r.effects_applied.join(', ')}]` : ''}`,
                ...l].slice(0, 10))
            } catch (e) { setNotice(e.message) }
          }}>{die}</button>))}
        {[['adv', `+ ${t('stats.adv')}`],
          ['dis', `− ${t('stats.dis')}`]].map(([m, lbl]) => (
          <button key={m} className="ghost" style={{ minWidth: 56 }}
                  aria-label={tf('dice.rollModeAria', { mode: lbl })}
                  onClick={async () => {
            try {
              const r = await api.characterRoll(id, `1d20${m}`, rollType)
              setRollLog((l) => [
                `${r.expression} → ${r.kept.join('+')} = ${r.total}${
                  (r.effects_applied || []).length
                    ? ` [${r.effects_applied.join(', ')}]` : ''}`,
                ...l].slice(0, 10))
            } catch (e) { setNotice(e.message) }
          }}>d20{lbl}</button>))}
      </div>
      <ul className="log" role="status" aria-live="polite">
        {rollLog.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </Section>
  </div>)
}
