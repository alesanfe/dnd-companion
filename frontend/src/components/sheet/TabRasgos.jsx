import { useState } from 'react'
import { Link } from 'react-router-dom'
import { SpellPicker, useEntityNames } from './pickers.jsx'
import { FeatList, Section } from './panels.jsx'

/** Pestaña Rasgos: rasgos opcionales, dotes/dones, subclase por clase,
    idiomas y otras competencias (armadura/arma/herramienta). */
export default function TabRasgos({ c }) {
  const { d, op, t, tf, focus, hud, tab } = c
  const show = (g) => focus ? hud.has(g) : tab === g
  const [otherProf, setOtherProf] = useState('')
  const names = useEntityNames(
    (d.classes || []).flatMap((cl) => [cl.class_id, cl.subclass_id])
      .filter(Boolean))
  const entName = (eid) => eid
    ? (names[eid] || eid.split(':').pop().replaceAll('-', ' ')) : null
  return (<div className="sheet-cols">
    <Section title={t('ras.features')}  hidden={!show('rasgos')} extraClass="optional">
      <SpellPicker entityType="feature" verb={t('common.add')}
        placeholder={t('ras.featurePh')}
        onPick={(fid) =>
          op('character.feature.add', { entity_id: fid })} />
      {(d.features || []).length > 0 && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {d.features.map((f) => (
            <span key={f} className="chip">{f}
              <button aria-label={tf('ras.featureRemove', { name: f })}
                      onClick={() =>
                op('character.feature.remove', { name: f })
              }>×</button></span>))}
        </div>)}
    </Section>

    <Section title={t('ras.feats')}  hidden={!show('rasgos')} extraClass="optional">
      <SpellPicker entityType="feat" verb={t('common.add')}
        placeholder={t('ras.featPh')}
        onPick={(fid) =>
          op('character.feat.learn', { feat_id: fid })} />
      {(d.feats_known || []).length > 0 && (
        <FeatList ids={d.feats_known} onForget={(fid) =>
          op('character.feat.forget', { feat_id: fid })} />)}
      <SpellPicker entityType="reward" verb={t('common.add')}
        placeholder={t('ras.rewardPh')}
        onPick={(rid) =>
          op('character.reward.add', { reward_id: rid })} />
      {(d.rewards || []).length > 0 && (
        <FeatList ids={d.rewards} onForget={(rid) =>
          op('character.reward.remove', { reward_id: rid })} />)}
    </Section>

    <Section title={t('ras.subclassLangs')}  hidden={!show('rasgos')} extraClass="optional">
      {(d.classes || []).map((cl, i) => (
        <div key={i} style={{ marginBottom: '.5rem' }}>
          <p className="muted" style={{ margin: '0 0 .2rem' }}>
            {/* clase/subclase enlazan al compendio */}
            <Link to={`/content/${encodeURIComponent(cl.class_id)}`}
                  style={{ color: 'inherit', textDecoration: 'none' }}>
              <strong>{entName(cl.class_id)}</strong></Link>
            {' '}— {t('sheet.lvlShort')}{cl.level}
            {cl.subclass_id
              ? <> · {t('ras.subclass')}: <b>
                  <Link to={`/content/${encodeURIComponent(
                                cl.subclass_id)}`}
                        style={{ color: 'inherit',
                                 textDecoration: 'none' }}>
                    {entName(cl.subclass_id)}</Link></b></>
              : ` · ${t('ras.noSubclass')}`}</p>
          <SpellPicker entityType="subclass" verb={t('ras.choose')}
            placeholder={tf('ras.subclassPh',
                            { name: entName(cl.class_id) })}
            onPick={(sid) =>
              op('character.subclass.set',
                 { class_index: i, subclass_id: sid })} />
        </div>))}
      <SpellPicker entityType="language" verb={t('common.add')}
        placeholder={t('ras.langPh')}
        onPick={(lid) =>
          op('character.language.add',
             { name: lid.split(':').pop().split('|')[0] })} />
      {(d.languages || []).length > 0 && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {d.languages.map((l) => (
            <span key={l} className="chip">{l}
              <button aria-label={tf('ras.langRemove', { name: l })}
                      onClick={() =>
                op('character.language.remove', { name: l })
              }>×</button></span>))}
        </div>)}
    </Section>

    <Section title={t('ras.otherProfs')}  hidden={!show('rasgos')} extraClass="optional">
      <p className="muted" style={{ marginTop: 0 }}>
        {t('ras.otherProfsHint')}</p>
      <div className="row">
        <input value={otherProf}
               placeholder={t('ras.otherProfPh')}
               aria-label={t('ras.otherProfAria')}
               onChange={(e) => setOtherProf(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' &&
                 otherProf.trim() &&
                 op('character.proficiency.add',
                    { kind: 'other', name: otherProf.trim() })
                   .then(() => setOtherProf(''))} />
        <button disabled={!otherProf.trim()} onClick={() => {
          op('character.proficiency.add',
             { kind: 'other', name: otherProf.trim() })
          setOtherProf('')
        }}>{t('common.add')}</button>
      </div>
      {(d.other_proficiencies || []).length > 0 && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {d.other_proficiencies.map((p) => (
            <span key={p} className="chip">{p}
              <button aria-label={tf('ras.profRemove', { name: p })}
                      onClick={() =>
                op('character.proficiency.remove',
                   { kind: 'other', name: p })
              }>×</button></span>))}
        </div>)}
    </Section>
  </div>)
}
