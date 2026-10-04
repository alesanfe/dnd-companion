import { SpellPicker } from './pickers.jsx'
import { SpellList, Section } from './panels.jsx'
import { useDialogs } from '../ui/Dialogs.jsx'

/** Pestaña Magia: espacios de conjuro y conjuros conocidos. */
export default function TabMagia({ c }) {
  const { id, d, slots, op, t, tf, focus, hud, tab, setCastId,
          derived } = c
  const show = (g) => focus ? hud.has(g) : tab === g
  const dlg = useDialogs()
  const ABILITY_ES = { str: 'FUE', dex: 'DES', con: 'CON',
                       int: 'INT', wis: 'SAB', cha: 'CAR' }
  return (<div className="sheet-cols">
    {/* cabecera de lanzamiento de la hoja oficial (pág. 3):
        característica, CD de salvación y ataque de conjuro */}
    {derived?.spellcasting_ability &&
      (d.spells_known || []).length > 0 && (
      <div className="stats compact" role="group"
           aria-label={t('mag.summaryAria')}>
        <span className="vstat" title={t('mag.abilityTitle')}>
          <i>{t('mag.ability')}</i>
          <b>{ABILITY_ES[derived.spellcasting_ability] ||
              derived.spellcasting_ability.toUpperCase()}</b></span>
        <span className="vstat" title={t('mag.dcTitle')}>
          <i>{t('mag.dc')}</i><b>{derived.spell_save_dc}</b></span>
        <span className="vstat" title={t('mag.atkTitle')}>
          <i>{t('mag.atk')}</i>
          <b>{derived.spell_attack >= 0 ? '+' : ''}
            {derived.spell_attack}</b></span>
      </div>)}
    {(Object.keys(slots).length > 0 ||
      Object.keys(d.pact_slots || {}).length > 0) && (
      <Section title={t('sheet.slots')}  hidden={!show('magia')}>
        {Object.entries(slots).map(([lvl, s]) => (
          <div key={lvl} className="row">
            <span className="muted" style={{ minWidth: '3.2rem' }}>
              {t('mag.lv')}{lvl} {s.total - s.used}/{s.total}</span>
            {/* pips clicables: ● libre → gasta, ○ gastado → recupera */}
            <span className="pips" role="group"
                  aria-label={tf('mag.slotsAria',
                                 { lv: lvl, n: s.total - s.used,
                                   tot: s.total })}>
              {Array.from({ length: s.total }, (_, i) => {
                const free = i < s.total - s.used
                return (
                  <button key={i} className={`pip${free ? '' : ' used'}`}
                          aria-label={free
                            ? tf('mag.spend', { lv: lvl })
                            : tf('mag.recover', { lv: lvl })}
                          onClick={() => op(free
                            ? 'character.spell_slot.use'
                            : 'character.spell_slot.restore',
                            { level: +lvl, pool: 'regular' })} />)
              })}
            </span>
          </div>
        ))}
        {/* magia de pacto (brujo): pool separado, recarga en corto */}
        {Object.entries(d.pact_slots || {}).map(([lvl, s]) => (
          <div key={`p${lvl}`} className="row">
            <span className="muted" style={{ minWidth: '3.2rem' }}
                  title={t('mag.pactTitle')}>
              {t('mag.pact')} {lvl} {s.total - s.used}/{s.total}</span>
            <span className="pips" role="group"
                  aria-label={tf('mag.pactAria',
                                 { lv: lvl, n: s.total - s.used,
                                   tot: s.total })}>
              {Array.from({ length: s.total }, (_, i) => {
                const free = i < s.total - s.used
                return (
                  <button key={i}
                          className={`pip pact${free ? '' : ' used'}`}
                          aria-label={free
                            ? tf('mag.pactSpend', { lv: lvl })
                            : tf('mag.pactRecover', { lv: lvl })}
                          onClick={() => op(free
                            ? 'character.spell_slot.use'
                            : 'character.spell_slot.restore',
                            { level: +lvl, pool: 'pact' })} />)
              })}
            </span>
          </div>
        ))}
      </Section>
    )}

    <Section title={t('sheet.spells')}  hidden={!show('magia')} extraClass="optional">
      <SpellPicker onPick={(sid) =>
        op('character.spell.learn', { spell_id: sid })}
        placeholder={t('mag.learnPh')}
        forClass={d.classes?.[0]?.class_id?.split(/[:|]/).pop()
                  .replace(/-/g, ' ')} />
      {/* guía para no-lanzadores: la pestaña queda casi vacía y el
          picker parece roto sin esta pista (las subclases arcanas
          sí la usan). can_cast viene del derived — el fallback 'int'
          del backend hacía truthy spellcasting_ability para TODAS
          las clases y la nota nunca se veía */}
      {(d.spells_known || []).length === 0 &&
        derived?.can_cast === false && (
        <p className="muted">{t('mag.noCaster')}</p>)}
      {(d.spells_prepared || []).length > 0 && derived && (
        <p className="muted">
          {t('sheet.prepared')}: {(d.spells_prepared || []).length}/
          {derived.prepared_limit ?? '∞'}
          {(d.spells_prepared || []).length >
            (derived.prepared_limit ?? Infinity) &&
            ` ${t('mag.overLimit')}`}
        </p>)}
      {(d.spells_known || []).length > 0 && (
        <SpellList ids={d.spells_known} charId={id}
          preparedIds={d.spells_prepared}
          onToBook={async (sid) => {
            const name = await dlg.prompt(
              t('mag.bookPrompt'), t('mag.bookDefault'))
            if (name?.trim())
              op('character.spellbook.add',
                 { name: name.trim(), spell_id: sid })
          }}
          onTogglePrepare={(sid) => op(
            (d.spells_prepared || []).includes(sid)
              ? 'character.spell.unprepare'
              : 'character.spell.prepare',
            { spell_id: sid })}
          onCast={(sid) => setCastId(sid)}
          onPin={(sid) => op('character.pin', { id: sid })}
          onForget={(sid) =>
            op('character.spell.forget', { spell_id: sid })} />
      )}
      {Object.keys(d.spellbooks || {}).length > 0 &&
        Object.entries(d.spellbooks).map(([name, ids]) => (
          <div key={name}>
            <h3 className="row" style={{ margin: '0.5rem 0 0.2rem' }}>
              <span style={{ flex: 1 }}>📖 {name}</span>
              <button className="ghost" style={{ minHeight: 26 }}
                      aria-label={tf('mag.bookDel', { name })}
                      title={t('mag.bookDelHint')}
                      onClick={() => op('character.spellbook.delete',
                                        { name })}>×</button>
            </h3>
            <SpellList ids={ids} charId={`${id}-${name}`}
              preparedIds={d.spells_prepared}
              onTogglePrepare={(sid) => op(
                (d.spells_prepared || []).includes(sid)
                  ? 'character.spell.unprepare'
                  : 'character.spell.prepare',
                { spell_id: sid })}
              onCast={(sid) => setCastId(sid)}
              onPin={(sid) => op('character.pin', { id: sid })}
              onForget={(sid) => op('character.spellbook.remove',
                                    { name, spell_id: sid })} />
          </div>
        ))}
    </Section>
  </div>)
}
