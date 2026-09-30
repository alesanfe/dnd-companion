import { useState } from 'react'
import { Section } from './panels.jsx'
import { api } from '../../api.js'
import { SpellPicker } from './pickers.jsx'
import { abilityScore } from './data.js'

/** Pestaña Características: stats derivadas, habilidades por
    característica y competencias. */
export default function TabStats({ c }) {
  const { id, char, d, derived, stats, op, t, tf, focus, hud, tab,
          load, setRollLog, setNotice } = c
  const [asiAb, setAsiAb] = useState('str')
  const show = (g) => focus ? hud.has(g) : tab === g
  return (<div className="sheet-cols">
    {derived && (
      <Section title={t('sheet.derived')}  hidden={!show('stats')}>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <span className="vstat"><i>CA</i><b>{derived.armor_class.total}</b></span>
          <span className="vstat"><i>Init</i><b>{derived.initiative >= 0 ? '+' : ''}{derived.initiative}</b></span>
          <span className="vstat"><i>Perc.</i><b>{derived.passive_perception}</b></span>
          {d.spells_known?.length > 0 && <>
            <span className="vstat"><i>CD</i><b>{derived.spell_save_dc}</b></span>
            <span className="vstat"><i>{t('stats.spellAtk')}</i><b>{derived.spell_attack >= 0 ? '+' : ''}{derived.spell_attack}</b></span>
          </>}
          <span className="vstat"><i>Prof</i><b>+{derived.proficiency_bonus}</b></span>
        </div>
        <p className="muted">CA = {derived.armor_class.breakdown
          .map(([n, v]) => `${n} ${v > 0 ? '+' : ''}${v}`).join(' ')}</p>
        {/* traza del motor de efectos por stat — "mi iniciativa es
            +2 porque <rasgo> da ventaja / +3 por <efecto>" */}
        <StatTrace id={id} derived={derived} d={d} t={t} />
        {/* defensas por efectos activos + sentidos (cajas
            Defenses/Senses de la hoja oficial) */}
        {(derived.defenses?.resistances?.length > 0 ||
          derived.defenses?.vulnerabilities?.length > 0 ||
          derived.defenses?.immunities?.length > 0 ||
          derived.defenses?.condition_immunities?.length > 0 ||
          d.senses) && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {derived.defenses.resistances.map((x) => (
              <span key={x} className="chip def-res"
                    title={t('def.resTitle')}>½ {x}</span>))}
            {derived.defenses.vulnerabilities.map((x) => (
              <span key={x} className="chip def-vuln"
                    title={t('def.vulnTitle')}>×2 {x}</span>))}
            {derived.defenses.immunities.map((x) => (
              <span key={x} className="chip def-imm"
                    title={t('def.immTitle')}>⊘ {x}</span>))}
            {(derived.defenses.condition_immunities || []).map((x) => (
              <span key={x} className="chip def-imm"
                    title={t('def.condImmTitle')}>🛡 {x}</span>))}
            {d.senses && (
              <span className="chip" title={t('def.sensesTitle')}>
                👁 {d.senses}</span>)}
          </div>)}
      </Section>
    )}

    {/* hoja 2024: habilidades agrupadas por característica, cada
        valor pulsable para tirar */}
    <Section title={t('tab.stats')}  hidden={!show('stats')}>
      <div className="ability-grid">
        {stats.map(([ab, label, skills]) => {
          const score = abilityScore(d.abilities, ab)
          const mod = Math.floor((score - 10) / 2)
          const prof = derived?.proficiency_bonus ?? 2
          const saveProf = d.save_proficiencies?.includes(ab)
          /* tirada tipada: el backend suma mod + competencia y aplica
             condiciones (agotamiento, parálisis → autofallo en FUE/DES) */
          const rollIt = async (rollType, name, mode = '') => {
            try {
              const r = await api.characterRoll(id, `1d20${mode}`, rollType)
              setRollLog((l) => [
                `${name}${mode === 'adv' ? ` [${t('stats.adv')}]`
                             : mode === 'dis' ? ` [${t('stats.dis')}]` : ''}${
                  r.auto_fail ? ` — ${t('stats.autofail')}` : ''}: ${
                  (r.kept || []).join('+')} = ${r.total}${
                  (r.effects_applied || []).length
                    ? ` [${r.effects_applied.join(', ')}]` : ''}`, ...l]
                .slice(0, 10))
            } catch (e) { setNotice(e.message) }
          }
          const rollCtx = (rollType, name) => (e) => {
            e.preventDefault()
            rollIt(rollType, name, e.shiftKey ? 'dis' : 'adv')
          }
          return (
            <div key={ab} className="ability-cell">
              <span className="muted ab-label">{label}</span>
              {/* el modificador es el héroe — la puntuación va pequeña
                  debajo, como en la hoja oficial */}
              <button className="ab-mod"
                      aria-label={tf('stats.checkOf', { name: label })}
                      title={t('stats.rollTitle')}
                      onClick={() =>
                        rollIt(`check:${ab}`, label)}
                      onContextMenu={rollCtx(`check:${ab}`, label)}>
                {mod >= 0 ? '+' : ''}{mod}</button>
              <span className="ab-score muted">{score}</span>
              <button className="ab-save"
                      aria-label={`${tf('stats.saveOf', { name: label })}${
                        saveProf ? ` ${t('stats.profTag')}` : ''}`}
                      title={t('stats.rollTitle')}
                      onContextMenu={rollCtx(
                        `save:${ab}`, `${t('stats.save')} ${label}`)}
                      onClick={() => rollIt(
                        `save:${ab}`, `${t('stats.save')} ${label}`)}>
                {t('stats.save')} {saveProf ? '●' : '○'}{' '}
                {mod + (saveProf ? prof : 0) >= 0 ? '+' : ''}
                {mod + (saveProf ? prof : 0)}</button>
              <ul className="skill-list">
                {skills.map(([sid, sname]) => {
                  const profs = d.skill_proficiencies || []
                  const p = profs.includes(sid) ||
                            profs.includes(sid.replace(/-/g, ' '))
                  const bonus = mod + (p ? prof : 0)
                  return (
                    <li key={sid}>
                      <button className="ghost"
                              style={{ fontSize: '.8em',
                                       textAlign: 'left' }}
                              aria-label={`${tf('stats.skillOf',
                                        { name: sname })}${
                                p ? ` ${t('stats.profTag')}` : ''}`}
                              title={t('stats.rollTitle')}
                              onContextMenu={rollCtx(
                                `skill:${sid}`, sname)}
                              onClick={() =>
                                rollIt(`skill:${sid}`, sname)}>
                        {p ? '●' : '○'} {sname}{' '}
                        {bonus >= 0 ? '+' : ''}{bonus}</button>
                    </li>)})}
              </ul>
            </div>)
        })}
      </div>
      <p className="muted" style={{ fontSize: '.8rem' }}>
        {t('stats.legend')}</p>
      <details>
        <summary className="muted" style={{ cursor: 'pointer' }}>
          {t('sheet.advanced')}</summary>
        <div className="row">
          <input defaultValue={char.name} aria-label={t('wiz.name')}
                 onBlur={async (e) => {
                   if (e.target.value.trim() &&
                       e.target.value !== char.name) {
                     try {
                       await api.patchCharacter(
                         id, { name: e.target.value.trim() })
                       load()
                     } catch (ex) { setNotice(ex.message) }
                   }
                 }} />
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {stats.map(([ab, label]) => (
            <label key={ab} className="muted"
                   style={{ fontSize: '.8rem' }}>
              {label.slice(0, 3).toUpperCase()}
              <input type="number" min="1" max="30"
                     defaultValue={abilityScore(d.abilities, ab)}
                     style={{ maxWidth: 64, display: 'block' }}
                     aria-label={tf('stats.scoreOf', { name: label })}
                     onBlur={(e) =>
                      op('character.ability.set',
                         { ability: ab,
                           value: +e.target.value })} />
            </label>))}
        </div>
      </details>
      {/* mejora de característica por nivel (ASI): +2 a una o +1/+1;
          una dote la sustituye — el conteo vive en la ficha */}
      {(derived?.asi_available ?? 0) > 0 && (
        <div className="notice" role="status">
          <div className="row" style={{ alignItems: 'center' }}>
            <strong>✨ {tf('stats.asiAvailable',
              { n: Math.floor(derived.asi_available / 2) })}</strong>
          </div>
          <div className="row">
            <select value={asiAb} aria-label={t('stats.asiAria')}
                    onChange={(e) => setAsiAb(e.target.value)}>
              {stats.map(([ab, label]) => (
                <option key={ab} value={ab}>{label}</option>))}
            </select>
            <button onClick={() =>
              op('character.asi.apply',
                 { ability: asiAb, amount: 2 })}>+2</button>
            <button onClick={() =>
              op('character.asi.apply',
                 { ability: asiAb, amount: 1 })}>+1</button>
            <button className="ghost"
                    title={t('stats.featInstead')}
                    onClick={() => op('character.asi.spent', {})}>
              {t('stats.pickFeat')}</button>
          </div>
        </div>)}
      {derived && (() => {
        const prof = derived.proficiency_bonus
        const profs = d.skill_proficiencies || []
        const has = (s) => profs.includes(s) ||
                           profs.includes(s.replace(/ /g, '-'))
        const mod = (a) => Math.floor((abilityScore(d.abilities, a) - 10) / 2)
        const pas = (skill, ab) =>
          10 + mod(ab) + (has(skill) ? prof : 0)
        return (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <span className="coin">
              {t('stats.passPerception')} {pas('perception', 'wis')}</span>
            <span className="coin">
              {t('stats.passInvestigation')} {pas('investigation', 'int')}</span>
            <span className="coin">
              {t('stats.passInsight')} {pas('insight', 'wis')}</span>
          </div>)
      })()}
    </Section>

    <Section title={t('stats.profs')}  hidden={!show('stats')} extraClass="optional">
      <SpellPicker entityType="skill" verb={t('stats.profVerb')}
        placeholder={t('stats.skillPh')}
        onPick={(sid) =>
          op('character.proficiency.add',
             { kind: 'skill',
               name: sid.split(':').pop().split('|')[0]
                    .replace(/-/g, ' ') })} />
      <div className="row">
        <span className="muted">{t('stats.saveLabel')}</span>
        {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
          <button key={a} className="ghost" onClick={() =>
            op('character.proficiency.add',
               { kind: 'save', name: a })}>{a.toUpperCase()}</button>))}
      </div>
      {(d.skill_proficiencies?.length > 0 || d.save_proficiencies?.length > 0) && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {d.save_proficiencies?.map((s) => (
            <span key={s} className="chip">save:{s}
              <button aria-label={tf('stats.profRemove', { name: s })}
                      onClick={() =>
                op('character.proficiency.remove',
                   { kind: 'save', name: s })}>×</button>
            </span>))}
          {d.skill_proficiencies?.map((s) => (
            <span key={s} className="chip">{s}
              <button aria-label={tf('stats.profRemove', { name: s })}
                      onClick={() =>
                op('character.proficiency.remove',
                   { kind: 'skill', name: s })}>×</button>
            </span>))}
        </div>
      )}
    </Section>
  </div>)
}

/** Traza de /derived/{stat}: resuelve un stat contra los efectos
    activos y muestra de dónde sale cada modificador (fuente →
    valor → razón). La base se pasa desde la ficha (CA ya tiene su
    desglose propio; aquí se trazan init/percepción/velocidad). */
function StatTrace({ id, derived, d, t }) {
  const [trace, setTrace] = useState(null)   // {stat, r}
  const BASES = {
    initiative: derived.initiative,
    passive_perception: derived.passive_perception,
    speed: parseInt(d.speed) || 30,
  }
  const ask = async (stat) => {
    try {
      const r = await api.derivedStat(id, stat, BASES[stat])
      setTrace({ stat, r })
    } catch { setTrace({ stat, r: null }) }
  }
  if (!derived) return null
  return (
    <details onToggle={(e) => { if (!e.target.open) setTrace(null) }}>
      <summary className="muted" style={{ cursor: 'pointer' }}>
        {t('stats.traceTitle')}</summary>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {Object.keys(BASES).map((stat) => (
          <button key={stat} className="ghost" style={{ minHeight: 30 }}
                  onClick={() => ask(stat)}>
            {t(`stats.trace.${stat}`)}</button>))}
      </div>
      {trace && (
        <p className="muted" role="status">
          {t(`stats.trace.${trace.stat}`)}:{' '}
          {trace.r ? (<>
            {trace.r.base}
            {trace.r.entries.map((en, i) => (
              <span key={i}> {en.value > 0 ? '+' : ''}{en.value}
                {' '}({en.source}{en.reason ? `, ${en.reason}` : ''})
              </span>))}
            {' = '}<strong>{trace.r.total}</strong>
            {trace.r.advantage && ` · ${t('stats.traceAdv')}`}
            {trace.r.disadvantage && ` · ${t('stats.traceDis')}`}
          </>) : t('stats.traceErr')}
        </p>)}
    </details>
  )
}
