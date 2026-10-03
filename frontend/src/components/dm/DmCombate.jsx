import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api.js'
import { AB_LONG, SKILL_ES } from '../sheet/data.js'

/** Pestaña Combate: calculadora de dificultad, nuevo encuentro,
    tracker de iniciativa, daño de área y panel del combatiente. */
export default function DmCombate({ c }) {
  const { t, tf, dmTab, campaign, playerView, combat, combatName,
          setCombatName, refresh, cop, setCombat, ordered, activeIdx, sel,
          setSelId, difficulty, setDifficulty, partyLevels,
          setPartyLevels, crs, setCrs, query, setQuery, monsters,
          manual, setManual, searchMonsters, dmg, setDmg, dmgType,
          setDmgType, newCond, setNewCond, condRounds, setCondRounds,
          areaDmg, setAreaDmg, areaAmt, setAreaAmt, areaType,
          setAreaType, areaResults, setAreaResults,
          setRollReq, setDmTab, entities } = c
  const [xpMsg, setXpMsg] = useState(null)
  const [creating, setCreating] = useState(false)
  const [suggestDiff, setSuggestDiff] = useState('medium')
  const [suggested, setSuggested] = useState(null)
  const [delegMembers, setDelegMembers] = useState(null)
  if (!campaign) return null

  /* Primera casilla libre para un token, calculada sobre el data
     FRESCO del mapa (puede ser la copia ganadora tras un 409). */
  const placeToken = (data, partial) => {
    const toks = data.tokens || []
    const used = new Set(toks.map((t2) => `${t2.x},${t2.y}`))
    let x = 0, y = 0
    while (used.has(`${x},${y}`)) { x++; if (x >= (data.cols || 16)) {
      x = 0; y++ } }
    return { ...partial, id: `t${crypto.randomUUID()}`, x, y }
  }

  /* Añade un token al primer mapa público con optimistic lock —
     si un jugador movió su token entre la carga y el drop, el
     append se rehace sobre la copia fresca (nunca lo pisa). */
  const addToken = async (partial) => {
    const map = (entities || []).find(
      (e) => e.kind === 'map' && e.visibility !== 'dm')
    if (!map) { setDmTab('mapa'); return }   // sin mapa → pestaña Mapa
    await api.patchEntityRebase(campaign.id, map, (d) => ({
      ...d, tokens: [...(d.tokens || []), placeToken(d, partial)],
    })).catch(() => {})   // mapa borrado o dos carreras perdidas
  }

  /* 📍 combatiente → token en el primer mapa público. El token queda
     vinculado a la ficha (ref_id) — PG en vivo y el jugador puede
     moverlo. */
  const toMap = async (cb) => {
    // tamaño del stat block → casillas del token (large 2×2, huge 3×3)
    const sz = String(cb.stat_block?.size || '').toLowerCase()
    const sq = sz.includes('gargan') ? 4
      : (sz.includes('huge') || sz.includes('enorme')) ? 3
      : (sz.includes('large') || sz.includes('grande')) ? 2 : 1
    await addToken({
      name: cb.name, size: sq,
      color: cb.kind === 'character'
        ? 'hsl(210 70% 45%)' : 'hsl(0 70% 45%)',
      ref_id: cb.ref_id || null,
      hp: cb.hp_current ?? null, max_hp: cb.hp_max ?? null,
    })
  }

  /* 📍 directo al mapa desde el buscador de monstruos — preparación
     de encuentros sin pasar por el tracker de combate */
  const dropMonster = async (m) => {
    let hp = null, sq = 1
    try {
      const dat = typeof m.data === 'string'
        ? JSON.parse(m.data) : (m.data || {})
      hp = dat.hp ?? dat.hit_points ?? dat.hp_max ?? null
      const sz = String(dat.size || '').toLowerCase()
      sq = sz.includes('gargan') ? 4
        : (sz.includes('huge') || sz.includes('enorme')) ? 3
        : (sz.includes('large') || sz.includes('grande')) ? 2 : 1
    } catch { /* resultado sin data — nombre suelto */ }
    await addToken({
      name: m.name, size: sq,
      color: 'hsl(0 70% 45%)',
      // ref al contenido: si ese monstruo entra en combate, el
      // combatiente lleva el mismo ref_id → el anillo de turno le
      // cae encima en el mapa
      ref_id: m.id || null,
      ...(hp ? { hp, max_hp: hp } : {}),
    })
  }
  const show = dmTab === 'combate'
  return (<>
    <section className="card" hidden={!show}>
      <h2>{t('dm.difficulty')}</h2>
      <div className="row">
        <input value={partyLevels} placeholder={t('com.levelsPh')}
               aria-label={t('com.levelsPh')}
               onChange={(e) => setPartyLevels(e.target.value)} />
        <input value={crs} placeholder={t('com.crsPh')}
               aria-label={t('com.crsPh')}
               onChange={(e) => setCrs(e.target.value)} />
        <button onClick={async () => {
          const lv = partyLevels.split(',').map((x) => +x.trim()).filter(Boolean)
          const cr = crs.split(',').map((x) => x.trim()).filter(Boolean)
          setDifficulty(await api.encounterDifficulty(lv, cr))
        }}>{t('com.calc')}</button>
      </div>
      {difficulty && (
        <p>
          <strong>{difficulty.rating.toUpperCase()}</strong>
          {' '}· {tf('com.adjXp', { n: difficulty.adjusted_xp,
                                  base: difficulty.raw_xp })}
          {difficulty.warnings.map((w) => <em key={w} className="error" role="alert"><br />{w}</em>)}
        </p>
      )}
      {/* constructor: presupuesto → composición de la content DB */}
      <div className="row">
        <select value={suggestDiff}
                aria-label={t('com.suggest')}
                onChange={(e) => setSuggestDiff(e.target.value)}>
          <option value="easy">easy</option>
          <option value="medium">medium</option>
          <option value="hard">hard</option>
          <option value="deadly">deadly</option>
        </select>
        <button className="ghost" onClick={async () => {
          const lv = partyLevels.split(',')
            .map((x) => +x.trim()).filter(Boolean)
          try {
            const r = await api.encounterSuggest({
              party_levels: lv, difficulty: suggestDiff })
            setSuggested(r)
            setCrs(r.monsters.map((m) => m.cr).join(','))
          } catch (e) { setSuggested({ error: e.message }) }
        }}>{t('com.suggest')}</button>
      </div>
      {suggested?.error && (
        <p className="error" role="alert">{suggested.error}</p>)}
      {suggested?.monsters && (
        <div>
          <p className="muted">
            {tf('com.suggestBudget', {
              difficulty: suggested.difficulty,
              n: suggested.budget })}
            {' '}· {tf('com.adjXp', {
              n: suggested.adjusted_xp, base: suggested.raw_xp })}
          </p>
          {/* crear el combate y meter la composición de un tirón —
              cada op devuelve la versión nueva para encadenar */}
          <button className="ghost" onClick={async () => {
            const r = await api.createCombat(
              combatName || t('com.defaultName'), campaign.id)
            let v = r.version ?? 1
            for (const m of suggested.monsters) {
              const op = await api.applyOp({ id: r.id, version: v },
                'combatant.add', { content_entity_id: m.id }, 'combat')
              if (op.queued) break   // offline — el resto luego
              v = op.version ?? v + 1
            }
            refresh(r.id)
          }}>▶ {t('com.start')}</button>
          <ul style={{ margin: 0 }}>
            {suggested.monsters.map((m) => (
              <li key={m.id}>
                {m.name} <em className="muted">CR {m.cr}</em>
                {' '}<button className="ghost"
                  title={t('com.toMap')}
                  onClick={() => dropMonster(
                    { id: m.id, name: m.name })}>📍</button>
              </li>))}
          </ul>
        </div>)}
    </section>

    {!combat && (
      <section className="card" hidden={!show}>
        <h2>{t('dm.newcombat')}</h2>
        <form className="row" onSubmit={async (e) => {
          e.preventDefault()
          if (creating) return              // doble submit = 2 combates
          setCreating(true)
          try {
            const r = await api.createCombat(
              combatName || t('com.defaultName'), campaign.id)
            refresh(r.id)
          } finally { setCreating(false) }
        }}>
          <input value={combatName} onChange={(e) => setCombatName(e.target.value)}
                 aria-label={t('com.namePh')}
                 placeholder={t('com.namePh')} />
          <button type="submit" disabled={creating}>{t('com.start')}</button>
        </form>
      </section>
    )}

    {combat && (
      <div className="dm-combat-grid">
        <section className="card" hidden={!show}>
          <h2>{combat.combat.name} — {t('com.round')} {combat.combat.round}</h2>
          <div className="row">
            <button onClick={() => cop('combat.next_turn', {})}>{t('dm.next')}</button>
            <button onClick={() => cop('combat.prev_turn', {})}>
              {t('com.prev')}</button>
            <button onClick={async () => {
              await api.addParty(combat.id)
              refresh(combat.id)
            }}>{t('com.addParty')}</button>
            <button onClick={async () => {
              let ver = combat.version
              for (const cb of combat.combat.combatants) {
                const r = await api.applyOp(
                  { id: combat.id, version: ver },
                  'combatant.initiative.roll',
                  { combatant_id: cb.id }, 'combat')
                ver = r.version ?? ver + 1   // la versión avanza por op
              }
              refresh(combat.id)
            }}>{t('dm.init')}</button>
            <button className="ghost" onClick={async () =>
              setDifficulty(await api.combatDifficulty(combat.id))
            }>{t('com.difficultyBtn')}</button>
            <button className="ghost" aria-expanded={!!areaDmg}
                    onClick={() => setAreaDmg(areaDmg ? null : {})}>
              {t('com.areaDmg')}</button>
            {/* reparto de XP del encuentro — op xp.add por PJ,
                auditable y deshacible */}
            <button className="ghost" title={t('com.xpTitle')}
                    onClick={async () => {
                      const r = await api.awardXp(combat.id).catch(() => null)
                      setXpMsg(r === null ? null
                        : r.total_xp
                          ? tf('com.xpAwarded', {
                              total: r.total_xp, share: r.per_player })
                          : t('com.xpNone'))
                    }}>{t('com.xpAward')}</button>
            <button className="dmg" onClick={() => cop('combat.end', {})}>{t('dm.end')}</button>
            <button className="ghost" title={t('com.delTitle')}
                    aria-label={t('com.delTitle')}
                    onClick={async () => {
              if (!confirm(t('com.delConfirm'))) return
              await api.deleteCombat(combat.id)
              setCombat(null)
            }}>🗑</button>
          </div>
          {xpMsg && (
            <p className="notice" role="status">
              {xpMsg}
              <button className="ghost"
                      onClick={() => setXpMsg(null)}>✕</button>
            </p>)}
          {areaDmg && (
            <div className="card" role="dialog"
                 aria-label={t('com.areaAria')}
                 style={{ background: 'var(--card-raised)' }}>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                {ordered.map((cb) => (
                  <label key={cb.id} className="chip"
                         style={{ cursor: 'pointer' }}>
                    <input type="checkbox"
                           checked={!!areaDmg[cb.id]}
                           onChange={(e) => setAreaDmg({
                             ...areaDmg, [cb.id]: e.target.checked })} />
                    {' '}{cb.name}</label>))}
              </div>
              <div className="row">
                <input type="number" min="1" value={areaAmt}
                       aria-label={t('com.amount')}
                       onChange={(e) => setAreaAmt(+e.target.value)} />
                <select value={areaType}
                        onChange={(e) => setAreaType(e.target.value)}
                        aria-label={t('sheet.dmgType')}>
                  <option value="">{t('sheet.noType')}</option>
                  {['fire', 'cold', 'lightning', 'poison', 'acid',
                    'necrotic', 'radiant', 'psychic', 'thunder',
                    'force', 'bludgeoning', 'piercing',
                    'slashing'].map((t2) =>
                    <option key={t2} value={t2}>{t2}</option>)}
                </select>
                <button className="dmg" onClick={async () => {
                  const targets = ordered.filter((cb) => areaDmg[cb.id])
                  let ver = combat.version
                  const res = []
                  for (const cb of targets) {
                    const r = await api.applyOp(
                      { id: combat.id, version: ver },
                      'combatant.damage',
                      { combatant_id: cb.id, amount: areaAmt,
                        damage_type: areaType }, 'combat')
                    ver = r.version ?? ver + 1
                    const ev = (r.events || []).find(
                      (e) => e.type === 'character.hp.changed')
                    res.push(`${cb.name}: ${areaAmt} → ${
                      ev?.payload?.amount ?? areaAmt}${
                      ev?.payload?.note ? ` (${ev.payload.note})` : ''}`)
                  }
                  setAreaResults(res)
                  refresh(combat.id)
                }}>{t('sheet.apply')}</button>
              </div>
              {(areaResults || []).length > 0 && (
                <ul style={{ margin: '.4rem 0 0' }}>
                  {areaResults.map((r, i) => <li key={i}>{r}</li>)}
                </ul>)}
            </div>)}
          {difficulty && (
            <p>
              <span className="chip">{difficulty.rating}</span>{' '}
              <span className="muted">
                {tf('com.xpDetail', { raw: difficulty.raw_xp,
                                      adj: difficulty.adjusted_xp })}
                {difficulty.warnings.map((w) => ` · ${w}`)}
              </span>
            </p>)}
        </section>

        {/* plegable: el panel fijo de la derecha empujaba el tracker
            en pantallas medias; details abierto mantiene descubrible */}
        <section className="card" hidden={!show}>
          <details open>
            <summary style={{ cursor: 'pointer' }}>
              <h2 style={{ display: 'inline' }}>{t('dm.addcombatant')}</h2>
            </summary>
          <form onSubmit={searchMonsters} className="row">
            <input value={query} onChange={(e) => setQuery(e.target.value)}
                   aria-label={t('com.monsterPh')}
                   placeholder={t('com.monsterPh')} />
            <button type="submit">{t('search.button')}</button>
          </form>
          {monsters.map((m) => (
            <div key={m.id} className="row">
              <span>{m.name}</span>
              <button onClick={() =>
                cop('combatant.add', { content_entity_id: m.id })}>+</button>
              <button className="ghost" title={t('com.toMap')}
                      onClick={() => dropMonster(m)}>📍</button>
            </div>
          ))}
          <div className="row">
            <input value={manual.name} placeholder={t('com.npcPh')}
                   aria-label={t('com.npcPh')}
                   onChange={(e) => setManual({ ...manual, name: e.target.value })} />
            <input type="number" style={{ maxWidth: 70 }} value={manual.hp_max}
                   aria-label={t('map.hpMaxAria') || 'HP max'}
                   onChange={(e) => setManual({ ...manual, hp_max: +e.target.value })} />
            <input type="number" style={{ maxWidth: 70 }} value={manual.initiative}
                   aria-label={t('dm.initiative')}
                   onChange={(e) => setManual({ ...manual, initiative: +e.target.value })} />
            <button disabled={!manual.name}
                    onClick={() => cop('combatant.add', {
                      name: manual.name, hp_max: manual.hp_max,
                      initiative: manual.initiative, kind: 'npc',
                    })}>{t('common.add')}</button>
          </div>
          </details>
        </section>

        <section className="card" hidden={!show}>
          <h2>{t('dm.initiative')}</h2>
          <div className="row">
            <select value={dmgType}
                    onChange={(e) => setDmgType(e.target.value)}
                    style={{ maxWidth: 160 }}
                    aria-label={t('sheet.dmgType')}>
              <option value="">{t('com.dmgUntyped')}</option>
              {['fire', 'cold', 'lightning', 'poison', 'acid',
                'necrotic', 'radiant', 'psychic', 'thunder',
                'force', 'bludgeoning', 'piercing', 'slashing']
                .map((t2) => <option key={t2} value={t2}>{t2}</option>)}
            </select>
            <span className="muted">
              {t('com.resistNote')}
            </span>
          </div>
          {ordered.map((cb, i) => {
            const isTurn = i === activeIdx &&
              combat.combat.status === 'active'
            return (
            <div key={cb.id}
                 className={`row combatant${isTurn ? ' turn' : ''}`}
                 aria-current={isTurn ? 'true' : undefined}>
              <span className="init">{cb.initiative}</span>
              <span className="cname"
                    role="button" tabIndex={0}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSelId(cb.id)}
                    onKeyDown={(e) => e.key === 'Enter' &&
                      setSelId(cb.id)}>
                {isTurn &&
                  <span className="turn-tag">{t('com.turn')} </span>}
                {cb.name}
                {cb.conditions.map((x) => (
                  <em key={x} className="chip"
                      title={(cb.condition_durations?.[x]
                        ? `${cb.condition_durations[x]} ${t('sheet.rounds')} — ` : '') +
                        t('com.condClick')}
                      onClick={() => cop('combatant.condition.remove',
                        { combatant_id: cb.id, condition: x })}
                      style={{ cursor: 'pointer' }}>
                    {x}{cb.condition_durations?.[x]
                      ? ` ⏳${cb.condition_durations[x]}` : ''}</em>))}
              </span>
              <span className="hp">{cb.hp_current}/{cb.hp_max}</span>
              <input type="number" style={{ maxWidth: 70 }}
                     aria-label={tf('com.dmgAmtAria', { name: cb.name })}
                     value={dmg[cb.id] || ''}
                     onChange={(e) => setDmg({ ...dmg, [cb.id]: +e.target.value })} />
              <button className="dmg" disabled={!dmg[cb.id]}
                      onClick={() => cop('combatant.damage', {
                        combatant_id: cb.id, amount: dmg[cb.id],
                        damage_type: dmgType || undefined })}>-</button>
              <button className="heal" disabled={!dmg[cb.id]}
                      onClick={() => cop('combatant.heal', { combatant_id: cb.id, amount: dmg[cb.id] })}>+</button>
              <button className="ghost" title={t('com.toMap')}
                      aria-label={tf('com.toMapAria', { name: cb.name })}
                      onClick={() => toMap(cb)}>📍</button>
              <button className="ghost" title={t('dm.remove')}
                      aria-label={tf('com.removeAria', { name: cb.name })}
                      onClick={() => cop('combatant.remove', {
                        combatant_id: cb.id })}>×</button>
            </div>
          )})}
        </section>

        {/* Panel contextual: click en un combatiente → condiciones
           con duración, acciones y stat block */}
        {sel && !playerView && (
          <section className="card" hidden={!show}
                   aria-label={tf('com.condAria', { name: sel.name })}>
            <h2>{t('dm.condition')} — {sel.name}</h2>
            <div className="row">
              <input list="dm-conds" value={newCond}
                     placeholder={t('sheet.condPh')}
                     aria-label={t('com.condAria2')}
                     onChange={(e) => setNewCond(e.target.value)} />
              <input type="number" min="1" placeholder={t('sheet.rounds')}
                     title={t('sheet.condDurTitle')}
                     aria-label={t('sheet.condDurAria')}
                     style={{ maxWidth: 80 }}
                     value={condRounds}
                     onChange={(e) => setCondRounds(e.target.value)} />
              <button disabled={!newCond.trim()} onClick={() => {
                cop('combatant.condition.apply', {
                  combatant_id: sel.id,
                  condition: newCond.trim(),
                  ...(condRounds ? { rounds: +condRounds } : {}) })
                setNewCond('')
              }}>{t('sheet.apply')}</button>
            </div>
            {/* salvación de muerte: solo con el combatiente a 0 PG */}
            {sel.hp_current === 0 && (
              <div className="row" style={{ marginTop: '.35rem' }}>
                <button className="dmg" onClick={() =>
                  cop('combatant.death_save_roll',
                      { combatant_id: sel.id })}>
                  ☠ {t('com.deathRoll')}</button>
                {(sel.death_saves?.success > 0 ||
                  sel.death_saves?.fail > 0) && (
                  <span className="muted">
                    ✓{sel.death_saves.success}{' '}
                    ✗{sel.death_saves.fail}</span>)}
              </div>)}
            {/* tiradas del stat block: salvaciones y pruebas de
                habilidad — las condiciones aplican (des)ventaja */}
            <div className="row" style={{ flexWrap: 'wrap',
                                          marginTop: '.35rem' }}>
              <span className="muted">{t('com.saveRoll')}:</span>
              {Object.keys(AB_LONG).map((ab) => (
                <button key={ab} className="ghost"
                        style={{ minHeight: 30 }}
                        onClick={() => cop('combatant.save',
                          { combatant_id: sel.id, ability: ab })}>
                  {ab.toUpperCase()}</button>))}
            </div>
            <form className="row" onSubmit={(e) => {
              e.preventDefault()
              cop('combatant.check',
                  { combatant_id: sel.id, skill: e.target.skill.value })
            }}>
              <span className="muted">{t('com.checkRoll')}:</span>
              <select name="skill" aria-label={t('com.checkAria')}>
                {Object.entries(SKILL_ES).map(([sk, es]) => (
                  <option key={sk}
                          value={sk.replace(/-/g, ' ')}>
                    {es}</option>))}
              </select>
              <button type="submit" className="ghost">
                {t('com.checkGo')}</button>
            </form>
            {/* delegar un NPC/monstruo a un jugador: mueve su token
                y tira sus acciones — el guard vive en el servidor
                (op DM-only); un PJ ya tiene dueño, no se delega */}
            {sel.kind !== 'character' && (
              <div className="row" style={{ marginTop: '.35rem' }}>
                <select value={sel.delegated_to || ''}
                        aria-label={t('com.delegateAria')}
                        onFocus={() => {
                          if (delegMembers === null)
                            api.listMembers(campaign.id)
                              .then((r) => setDelegMembers(r.members))
                              .catch(() => {})
                        }}
                        onChange={(e) => cop('combatant.delegate', {
                          combatant_id: sel.id,
                          player_uid: e.target.value || null })}>
                  <option value="">{t('com.delegateNone')}</option>
                  {(delegMembers || [])
                    .filter((m) => m.role === 'player'
                                   || m.role === 'guest')
                    .map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.user_id.slice(0, 8)} ({m.role})</option>))}
                </select>
              </div>)}
          </section>)}
        {/* stat block completo estilo Kobold Plus: características,
            defensas y sentidos junto al tracker, sin abrir el
            compendio aparte */}
        {sel?.stat_block && !playerView && (() => {
          const sb = sel.stat_block
          const fmtMod = (v) => `${v >= 0 ? '+' : ''}${
            Math.floor((v - 10) / 2)}`
          const row = (label, val) => val && (
            <p key={label} className="muted"
               style={{ margin: '.15rem 0', fontSize: '.85rem' }}>
              <b>{label}:</b> {val}</p>)
          return (
            <section className="card" hidden={!show}
                     aria-label={tf('com.statblockAria',
                                    { name: sel.name })}>
              <p className="muted" style={{ margin: 0 }}>
                {[sb.size, sb.type, sb.alignment]
                  .filter(Boolean).join(' · ')}</p>
              <p style={{ margin: '.15rem 0' }}>
                CA <b>{sb.ac}</b> · {t('com.speed')}{' '}
                <b>{sb.speed || '—'}</b>
                {sel.ref_id && (
                  <Link style={{ marginLeft: '.6rem' }}
                        to={`/content/${encodeURIComponent(sel.ref_id)}`}>
                    {t('com.sheetLink')}</Link>)}
              </p>
              {sb.abilities && (
                <div className="row" style={{ flexWrap: 'wrap',
                                             gap: '.3rem' }}>
                  {Object.entries(sb.abilities).map(([ab, v]) => (
                    <span key={ab} className="chip"
                          style={{ fontSize: '.8rem' }}>
                      {ab.toUpperCase()} {v} ({fmtMod(v)})</span>))}
                </div>)}
              {row(t('com.saves'),
                   Object.entries(sb.saves || {})
                     .map(([k, v]) => `${k.toUpperCase()} +${v}`)
                     .join(', '))}
              {row(t('com.skills'),
                   Object.entries(sb.skills || {})
                     .map(([k, v]) => `${k} +${v}`).join(', '))}
              {row(t('com.resist'),
                   [].concat(sb.resistances || []).join(', '))}
              {row(t('com.immune'),
                   [].concat(sb.immunities || []).join(', '))}
              {row(t('com.vuln'),
                   [].concat(sb.vulnerabilities || []).join(', '))}
              {row(t('com.senses'), sb.senses)}
              {row(t('com.languages'), sb.languages)}
            </section>)
        })()}
        {sel && !playerView && (sel.stat_block?.actions?.length > 0) && (
          <section className="card" hidden={!show}
                   aria-label={tf('com.actionsAria', { name: sel.name })}>
            <h2>{sel.name}
              <span className="muted" style={{ fontSize: '.8em' }}>
                {' '}CA {sel.stat_block.ac} · CR {sel.stat_block.cr}
                {sel.stat_block.spellcasting?.spells?.length > 0 &&
                  ` · ${sel.stat_block.spellcasting.spells.length} ${t('com.spellsCount')}`}
              </span>
              <button className="ghost" style={{ float: 'right' }}
                      onClick={() => setSelId(null)}>×</button>
            </h2>
            {sel.stat_block.actions.map((a, ai) => (
              <div key={ai} className="row">
                <button onClick={() =>
                  cop('combatant.action.roll',
                      { combatant_id: sel.id, action_index: ai })
                }>{a.name}</button>
                <span className="muted" style={{ fontSize: '0.8em' }}>
                  {a.category !== 'action' && `[${a.category}] `}
                  {a.text?.slice(0, 110)}{a.text?.length > 110 && '…'}
                </span>
              </div>))}
          </section>)}

        {/* Vista DM del personaje: CA/PG/condiciones + acciones de
            mesa sin abrir la ficha completa */}
        {sel && !playerView && sel.kind === 'character' && (
          <section className="card" hidden={!show}
                   aria-label={tf('com.dmSumAria', { name: sel.name })}>
            <h2>{sel.name}
              <span className="muted" style={{ fontSize: '.8em' }}>
                {' '}{t('com.playerTag')} · CA {sel.ac}</span>
              <button className="ghost" style={{ float: 'right' }}
                      onClick={() => setSelId(null)}>×</button>
            </h2>
            <p>
              PG {sel.hp_current}/{sel.hp_max}
              {sel.hp_temp > 0 && ` (+${sel.hp_temp} temp)`}
            </p>
            {sel.conditions.length > 0 && (
              <p className="muted">
                {t('com.conditions')}: {sel.conditions.join(' · ')}</p>)}
            {(sel.death_saves?.success > 0 ||
              sel.death_saves?.fail > 0) && (
              <p className="muted">
                {t('com.death')}: ✓{sel.death_saves.success}{' '}
                ✗{sel.death_saves.fail}</p>)}
            <div className="row">
              {sel.ref_id && (
                <Link to={`/character/${sel.ref_id}`}>
                  <button className="ghost">{t('com.sheetFull')}</button></Link>)}
              {sel.ref_id && (
                <button className="ghost" onClick={() => {
                  setRollReq({ character_id: sel.ref_id,
                               expression: '1d20', reason: '' })
                  setDmTab('sesion')
                }}>{t('com.reqRoll')}</button>)}
            </div>
          </section>)}
      </div>
    )}
  </>)
}
