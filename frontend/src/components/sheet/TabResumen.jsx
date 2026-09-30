import { useState } from 'react'
import { api } from '../../api.js'
import { CondChip, Section } from './panels.jsx'
import { RESET_ORDER, TRACKER_PRESETS } from './data.js'

const DMG_TYPES = ['acid', 'bludgeoning', 'cold', 'fire', 'force',
                   'lightning', 'necrotic', 'piercing', 'poison',
                   'psychic', 'radiant', 'slashing', 'thunder']

/** Pestaña Resumen: XP/inspiración, PG, descansos, recursos,
    fijados, nota rápida y condiciones. Recibe el contexto de la
    ficha (`c`) construido por CharacterSheet. */
export default function TabResumen({ c }) {
  const { id, char, d, hp, derived, op, t, tf, focus, hud, tab,
          amount, setAmount, xpAdd, setXpAdd,
          charDmgType, setCharDmgType, pinnedNames,
          journalEntry, setJournalEntry,
          newCond, setNewCond, condRounds, setCondRounds,
          condOptions, condRules, setAtkItem, setCastId,
          expr, rollType, setRollLog, setNotice } = c
  const show = (g) => focus ? hud.has(g) : tab === g
  return (<div className="sheet-cols">
    <div className="row" hidden={!show('resumen')}>
      <span className="muted">XP: {d.xp || 0}</span>
      <input type="number" min="0" style={{ maxWidth: 90 }} value={xpAdd}
             onChange={(e) => setXpAdd(+e.target.value)} />
      <button disabled={!xpAdd} onClick={() => {
        op('character.xp.add', { amount: xpAdd }); setXpAdd(0)
      }}>+XP</button>
      {d.inspiration
        ? <span className="chip">✦ {t('sheet.inspiration')}
            <button aria-label={t('sheet.inspSpendAria')} onClick={async () => {
              try {
                const r = await api.characterRoll(id, expr, rollType, true)
                setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total} [${t('sheet.inspiration')}]`, ...l].slice(0, 10))
                await op('character.inspiration.set', { value: false })
              } catch (e) { setNotice(e.message) }
            }}>{t('common.use').toLowerCase()}</button>
            <button aria-label={t('sheet.inspRemoveAria')} onClick={() =>
              op('character.inspiration.set', { value: false })}>×</button>
          </span>
        : <button className="ghost" onClick={() =>
            op('character.inspiration.set', { value: true })}>
            ✦ {t('sheet.noInspiration')}</button>}
      {d.concentrating_on && (
        <span className="chip">
          ⭑ {d.concentrating_on}
          <button aria-label={t('sheet.breakConc')} onClick={() =>
            op('character.concentration.break', {})}>×</button>
        </span>
      )}
    </div>

    <Section title={t('sheet.xp')}  hidden={!show('resumen')}>
      {derived?.next_level_xp > 0 && (
        <div className="hp-bar xp" role="img"
             aria-label={tf('sheet.xpAria',
                            { xp: d.xp || 0, nx: derived.next_level_xp })}>
          <div style={{ width: `${Math.min(100, Math.round(
            (d.xp || 0) / derived.next_level_xp * 100))}%` }} />
        </div>)}
      <div className="row">
        <span>XP {d.xp || 0}
          {derived?.next_level_xp &&
            <span className="muted"> / {derived.next_level_xp}
              {' '}{tf('sheet.forLevel', { n: (d.classes || [])
                .reduce((a, c2) => a + c2.level, 0) + 1 })}
              {derived.xp_to_next > 0 &&
                ` · ${tf('sheet.xpToGo', { n: derived.xp_to_next })}`}</span>}
        </span>
        <input type="number" min="1" value={amount}
               onChange={(e) => setAmount(+e.target.value)}
               aria-label={t('sheet.xpAmount')} />
        <button onClick={() =>
          op('character.xp.add', { amount })}>+XP</button>
        {derived?.next_level_xp != null &&
          (d.xp || 0) >= derived.next_level_xp && (
          <button className="primary" onClick={() =>
            op('character.level_up', { hp_mode: 'fixed' })}>
            {t('sheet.levelupLong')}</button>)}
      </div>
    </Section>

    <Section title={t('sheet.hp')}  hidden={!show('resumen')}>
      <div className="hp-big">
        {hp.current} / {hp.max}
        {hp.temp > 0 && <span className="temp"> +{hp.temp} temp</span>}
      </div>
      {hp.current === 0 && (
        <div className="notice" role="alert">
          <strong>{t('sheet.zeroHp')}</strong>
          <div className="row" style={{ alignItems: 'center' }}>
            <span className="dsaves" role="img"
                  aria-label={tf('sheet.dsSuccess',
                                 { n: d.death_saves?.success || 0 })}>
              {[0, 1, 2].map((i) => (
                <i key={i} className={`ds ok${
                  i < (d.death_saves?.success || 0) ? ' on' : ''}`} />))}
            </span>
            <span className="dsaves" role="img"
                  aria-label={tf('sheet.dsFail',
                                 { n: d.death_saves?.fail || 0 })}>
              {[0, 1, 2].map((i) => (
                <i key={i} className={`ds ko${
                  i < (d.death_saves?.fail || 0) ? ' on' : ''}`} />))}
            </span>
            <button className="primary" onClick={async () => {
              try {
                const r = await api.roll('1d20')
                await op('character.death_save', { roll: r.total })
              } catch (e) { setNotice(e.message) }
            }}>{t('sheet.rollSave')}</button>
          </div>
        </div>)}
      <div className="hp-bar" role="img"
           aria-label={tf('sheet.hpAria2',
                          { cur: hp.current, max: hp.max })}>
        <div style={{
          width: `${hp.max ? Math.round(100 * hp.current / hp.max) : 0}%`,
          background: !hp.max ? 'var(--success)'
            : hp.current / hp.max <= 0.25 ? 'var(--danger)'
            : hp.current / hp.max <= 0.5 ? 'var(--accent)'   /* malherido */
            : 'var(--success)' }} />
      </div>
      <div className="row">
        <input type="number" min="1" value={amount}
               onChange={(e) => setAmount(+e.target.value)} />
        <select value={charDmgType}
                onChange={(e) => setCharDmgType(e.target.value)}
                aria-label={t('sheet.dmgType')} style={{ maxWidth: 130 }}>
          <option value="">{t('sheet.noType')}</option>
          {['fire', 'cold', 'lightning', 'poison', 'acid', 'necrotic',
            'radiant', 'psychic', 'thunder', 'force', 'bludgeoning',
            'piercing', 'slashing']
            .map((t2) => <option key={t2} value={t2}>{t2}</option>)}
        </select>
        <button className="dmg" onClick={async () => {
          const r = await op('character.hp.damage',
             { amount, type: charDmgType || undefined })
          const ev = (r?.events || []).find(
            (e) => e.type === 'character.hp.changed')
          const p = ev?.payload
          if (p) {
            setNotice(
              `${t('sheet.damage')}${p.damage_type
                ? ` ${t('sheet.ofType')} ${p.damage_type}` : ''}: ` +
              `${amount} → ${p.amount} ${t('sheet.applied')}` +
              (p.temp_absorbed
                ? ` (${tf('sheet.tempAbsorbed', { n: p.temp_absorbed })})`
                : '') +
              (p.damage_effects?.length
                ? `. ${p.damage_effects.join('; ')}` : '') +
              (p.concentration_check
                ? `. ${tf('sheet.conSaveNote',
                         { dc: p.concentration_dc, spell: p.spell })}`
                : ''))
          }
        }}>{t('sheet.damage')}</button>
        <button className="heal" onClick={() =>
          op('character.hp.heal', { amount })}>{t('sheet.heal')}</button>
      </div>
    </Section>

    <Section title={t('sheet.rests')}  hidden={!show('resumen')}>
      {/* qué se recuperará — estilo D&D Beyond rest dialog */}
      {(() => {
        const totalLv = (d.classes || [])
          .reduce((a2, c2) => a2 + c2.level, 0)
        const pactUsed = Object.values(d.pact_slots || {})
          .reduce((a2, s) => a2 + (s.used || 0), 0)
        const slotUsed = Object.values(d.spell_slots || {})
          .reduce((a2, s) => a2 + (s.used || 0), 0)
        const resBy = (rs) => (d.resources || [])
          .filter((r) => r.reset_on === rs && r.current < r.max)
          .map((r) => `${r.name} ${r.current}/${r.max}`)
        const hdMissing = (d.hit_dice || [])
          .reduce((a2, p) => a2 + (p.total - p.remaining), 0)
        const hdRegain = Math.min(Math.max(1, Math.floor(totalLv / 2)),
                                  hdMissing)
        const shortList = [
          pactUsed > 0 && tf('rest.pact', { n: pactUsed }),
          ...resBy('short'),
        ].filter(Boolean)
        const longList = [
          slotUsed > 0 && tf('rest.slots', { n: slotUsed }),
          pactUsed > 0 && tf('rest.pact', { n: pactUsed }),
          hp.max - hp.current > 0 &&
            tf('rest.hp', { n: hp.max - hp.current }),
          hp.temp > 0 && tf('rest.temp', { n: hp.temp }),
          hdRegain > 0 && tf('rest.hd', { n: hdRegain }),
          ...['short', 'long', 'dawn'].flatMap(resBy),
          (d.condition_stacks || {}).exhaustion > 0 && t('rest.exh'),
        ].filter(Boolean)
        return (
          <details style={{ marginBottom: '.3rem' }}>
            <summary className="muted" style={{ cursor: 'pointer' }}>
              {t('rest.preview')}</summary>
            <ul className="muted" style={{ margin: '.2rem 0',
                paddingLeft: '1.2rem', fontSize: '.85rem' }}>
              <li><strong>{t('sheet.short')}:</strong>{' '}
                {shortList.length ? shortList.join(' · ')
                                  : t('rest.none')}</li>
              <li><strong>{t('sheet.long')}:</strong>{' '}
                {longList.length ? longList.join(' · ')
                                 : t('rest.none')}</li>
            </ul>
          </details>)
      })()}
      <div className="row">
        <button onClick={() => op('character.rest.short', {})}>{t('sheet.short')}</button>
        <button onClick={() => op('character.rest.long', {})}>{t('sheet.long')}</button>
      </div>
      {(d.hit_dice || []).map((p, i) => (
        <div key={i} className="row">
          <span className="muted" style={{ minWidth: '5.8rem' }}>
            {p.die} {p.remaining}/{p.total}</span>
          <span className="pips" role="group"
                aria-label={tf('sheet.hitdiceAria',
                               { die: p.die, rem: p.remaining,
                                 tot: p.total })}>
            {Array.from({ length: p.total }, (_, j) => {
              const free = j < p.remaining
              return (
                <button key={j}
                        className={`pip die${free ? '' : ' used'}`}
                        aria-label={free
                          ? tf('sheet.spendDie', { die: p.die })
                          : tf('sheet.recoverDie', { die: p.die })}
                        onClick={() => op(free
                          ? 'character.hit_die.spend'
                          : 'character.hit_die.unspend',
                          { pool: i })} />)
            })}
          </span>
        </div>
      ))}
    </Section>

    <Section title={t('sheet.limited')}  hidden={!show('resumen')}
             extraClass="optional">
        {Object.entries((d.resources || []).reduce((g, r) => {
          (g[r.reset_on || 'long'] ??= []).push(r)
          return g
        }, {})).sort(([a], [b]) =>
          RESET_ORDER.indexOf(a) - RESET_ORDER.indexOf(b))
          .map(([reset, list]) => (
            <div key={reset}>
              <h3 className="muted" style={{ fontSize: '.85rem' }}>
                {t('reset.' + reset) !== 'reset.' + reset
                  ? t('reset.' + reset) : reset}</h3>
              {list.map((r) => (
          <div key={r.id} className="row">
            <span style={{ flex: 1 }}>{r.name}: {r.current}/{r.max}</span>
            {r.current > 0
              ? <button onClick={() => op('character.resource.consume',
                                         { resource_id: r.id })}>
                  {t('common.use')}</button>
              : <span className="muted">{t('sheet.depleted')}</span>}
            {r.current < r.max && (
              <button className="ghost" aria-label={tf('sheet.restoreUse',
                                        { name: r.name })}
                      onClick={() => op('character.resource.restore',
                                        { resource_id: r.id, amount: 1 })}>
                +</button>)}
            <button className="ghost" aria-label={tf('sheet.removeResource',
                                        { name: r.name })}
                    onClick={() => op('character.resource.remove',
                                      { resource_id: r.id })}>×</button>
          </div>
        ))}
            </div>))}
        {(d.resources || []).length === 0 && (
          <p className="muted">{t('sheet.noResources')}</p>)}
        <details>
          <summary className="muted" style={{ cursor: 'pointer' }}>
            {t('sheet.addTracker')}</summary>
          <form className="row" onSubmit={(e) => {
            e.preventDefault()
            const f = e.target
            const name = f.rname.value.trim()
            const max = +f.rmax.value
            if (!name || max < 1) return
            op('character.resource.add',
               { name, max, reset_on: f.rreset.value })
            f.reset()
          }}>
            {/* preset de clase → rellena nombre/usos/reset
                (los selectores son solo atajos, todo editable) */}
            <select defaultValue="" aria-label={t('sheet.preset')}
                    style={{ maxWidth: 150 }} onChange={(e) => {
              const p = TRACKER_PRESETS[+e.target.value]
              if (!p) return
              const f = e.target.form
              const lv = (d.classes || [])
                .reduce((a2, c2) => a2 + c2.level, 0) || 1
              f.rname.value = p[0]
              f.rmax.value = Math.max(1, p[1](lv))
              f.rreset.value = p[2]
            }}>
              <option value="">{t('sheet.preset')}</option>
              {TRACKER_PRESETS.map((p, i) => (
                <option key={p[0]} value={i}>{p[0]}</option>))}
            </select>
            <input name="rname" required maxLength={40}
                   placeholder={t('sheet.trackerPh')} />
            <input name="rmax" type="number" min="1" max="99"
                   required placeholder={t('sheet.uses')}
                   style={{ maxWidth: 70 }} aria-label={t('sheet.maxUses')} />
            <select name="rreset" aria-label={t('sheet.resetsOn')}
                    defaultValue="long">
              <option value="short">{t('sheet.short')}</option>
              <option value="long">{t('sheet.long')}</option>
              <option value="dawn">{t('sheet.dawn')}</option>
              <option value="none">{t('sheet.never')}</option>
            </select>
            <button type="submit">{t('common.add')}</button>
          </form>
        </details>
      </Section>

    {(d.pinned || []).length > 0 && (
      <Section title={t('sheet.favorites')}  hidden={!show('resumen')}>
        {d.pinned.map((pid) => {
          const it = (d.inventory || []).find((x) => x.id === pid)
          const spell = (d.spells_known || []).includes(pid) ? pid : null
          return (
            <div key={pid} className="row">
              <span style={{ flex: 1 }}>
                {it?.name || pinnedNames[pid] ||
                  pid.split(':').pop().replace(/-/g, ' ')}</span>
              {it && (
                <button onClick={() => setAtkItem(it)}>
                  {t('sheet.attack')}</button>)}
              {spell && (
                <button onClick={() => setCastId(spell)}>
                  {t('sheet.cast')}</button>)}
              <button className="ghost"
                      aria-label={t('sheet.unpinAria')}
                      onClick={() =>
                        op('character.unpin', { id: pid })}>×</button>
            </div>)})}
      </Section>)}

    <Section title={t('sheet.note')}  hidden={!show('resumen')}>
      <div className="row">
        <input value={journalEntry}
               placeholder={t('sheet.notePh')}
               aria-label={t('sheet.note')}
               onChange={(e) => setJournalEntry(e.target.value)}
               onKeyDown={(e) => {
                 if (e.key === 'Enter' && journalEntry.trim()) {
                   op('character.journal.add',
                      { entry: journalEntry.trim() })
                   setJournalEntry('')
                 }
               }} />
        <button disabled={!journalEntry.trim()} onClick={() => {
          op('character.journal.add', { entry: journalEntry.trim() })
          setJournalEntry('')
        }}>{t('sheet.write')}</button>
      </div>
    </Section>

    <Section title={t('sheet.conditions')}  hidden={!show('resumen')} extraClass="optional">
      <div className="row">
        <input value={newCond} onChange={(e) => setNewCond(e.target.value)}
               placeholder={t('sheet.condPh')} list="cond-list" />
        <datalist id="cond-list">
          {condOptions.map((co) => <option key={co} value={co} />)}
        </datalist>
        <input type="number" min="1" placeholder={t('sheet.rounds')}
               title={t('sheet.condDurTitle')}
               aria-label={t('sheet.condDurAria')}
               style={{ maxWidth: 76 }}
               value={condRounds}
               onChange={(e) => setCondRounds(e.target.value)} />
        <button disabled={!newCond.trim()} onClick={() => {
          op('character.condition.apply', {
            condition: newCond.trim(),
            ...(condRounds ? { rounds: +condRounds } : {}) })
          setNewCond('')
        }}>{t('sheet.apply')}</button>
        {Object.keys(d.condition_durations || {}).length > 0 && (
          <button className="ghost"
                  title={t('sheet.tickTitle')}
                  onClick={() =>
                    op('character.tick', { rounds: 1 })}>
            {t('sheet.tick')}</button>)}
      </div>
      {(d.conditions || []).map((co) => (
        <span key={co} className="row" style={{ alignItems: 'center' }}>
          <CondChip name={(d.condition_stacks?.[co] > 0)
                          ? `${co} ×${d.condition_stacks[co]}` : co}
            rules={condRules}
            onRemove={() => op('character.condition.remove',
                               { condition: co })} />
          {(d.condition_stacks?.[co] ?? 0) > 0 ? (
            <>
              <button className="ghost" style={{ minHeight: 28 }}
                      aria-label={tf('sheet.stackDown', { name: co })}
                      onClick={() => op('character.condition.apply',
                                        { condition: co, stacks: -1 })}>
                −</button>
              <button className="ghost" style={{ minHeight: 28 }}
                      aria-label={tf('sheet.stackUp', { name: co })}
                      onClick={() => op('character.condition.apply',
                                        { condition: co, stacks: 1 })}>
                +</button>
            </>) : (
            <button className="ghost" style={{ minHeight: 28 }}
                    title={t('sheet.stackTitle')}
                    aria-label={tf('sheet.stackAria', { name: co })}
                    onClick={() => op('character.condition.apply',
                                      { condition: co, stacks: 1 })}>
              ×n</button>)}
          {d.condition_durations?.[co] != null && (
            <span className="muted" style={{ fontSize: '.8rem' }}>
              ⏳ {d.condition_durations[co]} {t('sheet.rounds')}</span>)}
        </span>
      ))}
      {/* regla de agotamiento: penalizadores activos por nivel,
          acumulativos (desventaja en pruebas → velocidad /2 → …) */}
      {(derived?.exhaustion || []).length > 0 && (
        <div className="notice" role="alert"
             style={{ marginTop: '.4rem' }}>
          <strong>☠ {t('sheet.exhaustion')}</strong>
          <ul style={{ margin: '.2rem 0 0', paddingLeft: '1.2rem' }}>
            {derived.exhaustion.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>)}
    </Section>

    {/* efectos declarativos: resistencias, bendiciones, auras —
        el motor los aplica a tiradas/daño y salen en Defensas */}
    <Section title={t('fx.title')} hidden={!show('resumen')}
             extraClass="optional">
      <EffectsEditor d={d} op={op} t={t} tf={tf} />
    </Section>
  </div>)
}

/** Mini-editor de Effect: cubre el 90% de usos (resistencia,
    vulnerabilidad, inmunidad a daño o condición, ventaja/
    desventaja, modificador +N). */
function EffectsEditor({ d, op, t, tf }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState('grant_resistance')
  const [target, setTarget] = useState('')
  const [value, setValue] = useState(1)
  const KINDS = [
    ['grant_resistance', t('fx.op.res')],
    ['grant_vulnerability', t('fx.op.vuln')],
    ['grant_immunity', t('fx.op.imm')],
    ['immcond', t('fx.op.immCond')],
    ['grant_advantage', t('fx.op.adv')],
    ['grant_disadvantage', t('fx.op.dis')],
    ['add_modifier', t('fx.op.mod')],
  ]
  const isDmg = ['grant_resistance', 'grant_vulnerability',
                 'grant_immunity'].includes(kind)
  const submit = (e) => {
    e.preventDefault()
    if (!name.trim() || (kind !== 'add_modifier' && !target.trim()))
      return
    const effOp = kind === 'immcond'
      ? { op: 'grant_immunity', target: `condition:${target.trim()}` }
      : kind === 'add_modifier'
        ? { op: 'add_modifier', target: target.trim(), value: +value }
        : { op: kind, target: target.trim() }
    op('character.effect.add',
       { effect: { name: name.trim(), trigger: null,
                   operations: [effOp] } })
    setName(''); setTarget('')
  }
  return (<>
    {(d.effects || []).length > 0 && (
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {d.effects.map((e) => (
          <span key={e.id} className="chip"
                title={(e.operations || [])
                  .map((o) => `${o.op}:${o.target}`).join(' · ')}>
            {e.name}
            <button aria-label={tf('fx.removeAria', { name: e.name })}
                    onClick={() =>
                      op('character.effect.remove', { effect_id: e.id })}>
              ×</button>
          </span>))}
      </div>)}
    <form className="row" style={{ flexWrap: 'wrap' }}
          onSubmit={submit}>
      <input value={name} required maxLength={40}
             placeholder={t('fx.namePh')} aria-label={t('fx.namePh')}
             onChange={(e) => setName(e.target.value)} />
      <select value={kind} aria-label={t('fx.kindAria')}
              onChange={(e) => setKind(e.target.value)}>
        {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <input value={target} required={kind !== 'add_modifier'}
             list={isDmg ? 'dmg-types' : undefined}
             placeholder={kind === 'immcond' ? t('fx.condPh')
                          : t('fx.targetPh')}
             aria-label={t('fx.targetAria')}
             onChange={(e) => setTarget(e.target.value)} />
      {kind === 'add_modifier' && (
        <input type="number" value={value} style={{ maxWidth: 64 }}
               aria-label={t('fx.valueAria')}
               onChange={(e) => setValue(e.target.value)} />)}
      <button type="submit" disabled={!name.trim()}>
        {t('common.add')}</button>
    </form>
    <datalist id="dmg-types">
      {DMG_TYPES.map((x) => <option key={x} value={x} />)}
    </datalist>
  </>)
}
