import { NextLevelFeatures } from './sheetParts.jsx'
import { SpellPicker } from './pickers.jsx'

// panel de subida de nivel: clase existente o multiclase nueva —
// extraído de pages/CharacterSheet.jsx (AU-22)
export default function SheetLevelUp({
  classes, entName, op, setLvlPanel, t, tf,
}) {
  return (
    <section className="card" role="dialog"
             aria-label={t('sheet.levelup')}>
      <h2>{t('sheet.levelup')}</h2>
      {(classes || []).map((cl) => (
        <div key={cl.class_id} className="row">
          <span style={{ flex: 1 }}>
            {entName(cl.class_id)}
            {cl.subclass_id && ` (${entName(cl.subclass_id)})`}
            {' — '}{t('sheet.lvlShort')}{cl.level}</span>
          <button className="primary" onClick={() => {
            setLvlPanel(false)
            op('character.level_up',
               { class_id: cl.class_id, hp_mode: 'fixed' })
          }}>{tf('sheet.levelTo', { n: cl.level + 1 })}</button>
          <NextLevelFeatures classId={cl.class_id}
                             level={cl.level + 1} />
        </div>))}
      <p className="muted" style={{ marginBottom: 0 }}>
        {t('sheet.multiclassHint')}</p>
      <SpellPicker entityType="class" verb={t('sheet.addLv1')}
        placeholder={t('sheet.searchClass')}
        onPick={(cid) => {
          setLvlPanel(false)
          op('character.level_up',
             { class_id: cid, hp_mode: 'fixed' })
        }} />
    </section>
  )
}
