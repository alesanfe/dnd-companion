import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api.js'

export default function CharacterSheet() {
  const { id } = useParams()
  const [char, setChar] = useState(null)
  const [amount, setAmount] = useState(1)
  const [expr, setExpr] = useState('1d20')
  const [rollType, setRollType] = useState('check')
  const [rollLog, setRollLog] = useState([])
  const [err, setErr] = useState(null)
  const [history, setHistory] = useState(null)
  const [newItem, setNewItem] = useState('')
  const [newCond, setNewCond] = useState('')
  const [coin, setCoin] = useState('gp')
  const [actions, setActions] = useState(null)
  const [focus, setFocus] = useState(false)   // modo concentración
  const [notice, setNotice] = useState(null)  // aviso de concentración
  const [journalEntry, setJournalEntry] = useState('')
  const [derived, setDerived] = useState(null)
  const [shops, setShops] = useState([])
  const [condOptions, setCondOptions] = useState([])

  const loadMeta = () => {
    api.derivedAll(id).then(setDerived).catch(() => {})
    api.contentOptions('condition').then((r) =>
      setCondOptions((r.options || []).map((o) =>
        o.id.split(':').pop()))).catch(() => {})
  }
  useEffect(() => { loadMeta() }, [id])
  useEffect(() => {
    if (!char?.campaign_id) return
    api.listEntities(char.campaign_id, 'shop', 'player')
      .then((r) => setShops(r.entities)).catch(() => {})
  }, [char?.campaign_id])

  const load = () => api.getCharacter(id).then(setChar).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [id])

  const [rollRequest, setRollRequest] = useState(null)
  const [xpAdd, setXpAdd] = useState(0)

  // Sync en vivo: si el personaje está en una campaña, escucha eventos
  // de la sala y recarga cuando algo lo toca. Las peticiones de tirada
  // del DM aparecen como banner accionable.
  useEffect(() => {
    if (!char?.campaign_id) return undefined
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/campaign/${char.campaign_id}`)
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type !== 'event') return
      const ev = msg.event
      if (ev.aggregate_id !== id) return
      if (ev.type === 'dice.roll.requested') setRollRequest(ev.payload)
      else load()
    }
    return () => ws.close()
  }, [char?.campaign_id, id])

  const op = async (type, payload) => {
    try {
      const r = await api.applyOp(char, type, payload)
      // daño manteniendo concentración → avisa de la tirada de CON
      const cc = (r.events || []).find((e) => e.payload?.concentration_check)
      if (cc) {
        setNotice(`Concentración (${cc.payload.spell}): salva CON, CD ${cc.payload.concentration_dc}`)
      }
      load()
    } catch (e) {
      setErr(e.message)
      load() // resync on conflict
    }
  }

  const doRoll = async (e) => {
    e.preventDefault()
    // tirada a través del motor de efectos: aplica ventaja/desventaja y
    // mods declarativos activos sobre el personaje
    const r = await api.characterRoll(id, expr, rollType)
    const fx = (r.effects_applied || []).length
      ? ` [${r.effects_applied.join(', ')}]` : ''
    setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total}${fx}`, ...l].slice(0, 10))
  }

  if (err && !char) return <main><p className="error">{err}</p></main>
  if (!char) return <main><p>Cargando…</p></main>

  const d = char.data
  const hp = d.hp || { current: 0, max: 0, temp: 0 }
  const slots = d.spell_slots || {}

  return (
    <main className={focus ? 'concentration' : ''}>
      <h1>{char.name}
        <span className="muted" style={{ fontSize: '0.9rem' }}>
          {' '}nivel {d.classes?.reduce((s, c) => s + c.level, 0) || 1}
        </span>
      </h1>
      <div className="row">
        <button className={focus ? '' : 'ghost'}
                aria-pressed={focus}
                onClick={() => setFocus(!focus)}>
          {focus ? 'Salir del modo mesa' : 'Modo mesa'}
        </button>
        <button onClick={async () => {
          const ex = await api.exportCharacter(id)
          const blob = new Blob([JSON.stringify(ex, null, 2)],
                                { type: 'application/json' })
          const a = document.createElement('a')
          a.href = URL.createObjectURL(blob)
          a.download = `${char.name}.json`
          a.click()
        }}>Exportar</button>
        {d.classes?.length > 0 && (
          <button onClick={() =>
            op('character.level_up',
               { class_id: d.classes[0].class_id, hp_mode: 'fixed' })}>
            Subir nivel
          </button>
        )}
        <button onClick={async () => {
          const h = await api.opHistory(id)
          setHistory(history ? null : h.operations)
        }}>Historial</button>
      </div>
      {err && <p className="error">{err}</p>}
      {notice && (
        <p className="notice" role="alert">
          {notice} <button onClick={() => setNotice(null)}>OK</button>
        </p>
      )}

      {rollRequest && (
        <section className="card" role="alert">
          <h2>El DM pide una tirada</h2>
          <p><strong>{rollRequest.expression}</strong>
            {rollRequest.reason && ` — ${rollRequest.reason}`}
            {rollRequest.secret && <span className="muted"> (secreta)</span>}
          </p>
          <button onClick={async () => {
            const r = await api.characterRoll(id, rollRequest.expression, 'check')
            setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total}`, ...l].slice(0, 10))
            setRollRequest(null)
          }}>Tirar {rollRequest.expression}</button>
          <button className="ghost" onClick={() => setRollRequest(null)}>Descartar</button>
        </section>
      )}

      <div className="row">
        <span className="muted">PX: {d.xp || 0}</span>
        <input type="number" min="0" style={{ maxWidth: 90 }} value={xpAdd}
               onChange={(e) => setXpAdd(+e.target.value)} />
        <button disabled={!xpAdd} onClick={() => {
          op('character.xp.add', { amount: xpAdd }); setXpAdd(0)
        }}>+XP</button>
        {d.inspiration
          ? <span className="chip">✦ Inspiración
              <button aria-label="Gastar inspiración" onClick={async () => {
                const r = await api.characterRoll(id, expr, rollType, true)
                setRollLog((l) => [`${r.expression} → ${r.kept.join('+')} = ${r.total} [inspiración]`, ...l].slice(0, 10))
                await op('character.inspiration.set', { value: false })
              }}>usar</button>
              <button aria-label="Quitar inspiración" onClick={() =>
                op('character.inspiration.set', { value: false })}>×</button>
            </span>
          : <button className="ghost" onClick={() =>
              op('character.inspiration.set', { value: true })}>
              ✦ Sin inspiración</button>}
        {d.concentrating_on && (
          <span className="chip">
            ⭑ {d.concentrating_on}
            <button aria-label="Romper concentración" onClick={() =>
              op('character.concentration.break', {})}>×</button>
          </span>
        )}
      </div>

      {history && (
        <section className="card optional">
          <h2>Historial <span className="muted">(reversible)</span></h2>
          {history.map((h) => (
            <div key={h.operation_id} className="row">
              <span className="muted">{h.timestamp.slice(11, 19)}</span>
              <span style={{ flex: 1 }}>{h.operation_type}</span>
              {h.reversible ? (
                <button onClick={async () => {
                  await api.undoOp(h.operation_id)
                  setHistory(null)
                  load()
                }}>Deshacer</button>
              ) : <span className="muted">—</span>}
            </div>
          ))}
        </section>
      )}

      {derived && (
        <section className="card">
          <h2>Calculado</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <span className="coin">CA {derived.armor_class.total}</span>
            <span className="coin">Init {derived.initiative >= 0 ? '+' : ''}{derived.initiative}</span>
            <span className="coin">Perc. pasiva {derived.passive_perception}</span>
            {d.spells_known?.length > 0 && <>
              <span className="coin">CD {derived.spell_save_dc}</span>
              <span className="coin">Ataque {derived.spell_attack >= 0 ? '+' : ''}{derived.spell_attack}</span>
            </>}
            <span className="coin">Prof +{derived.proficiency_bonus}</span>
          </div>
          <p className="muted">CA = {derived.armor_class.breakdown
            .map(([n, v]) => `${n} ${v > 0 ? '+' : ''}${v}`).join(' ')}</p>
        </section>
      )}

      <section className="card">
        <h2>Puntos de golpe</h2>
        <div className="hp-big">
          {hp.current} / {hp.max}
          {hp.temp > 0 && <span className="temp"> +{hp.temp} temp</span>}
        </div>
        <div className="row">
          <input type="number" min="1" value={amount}
                 onChange={(e) => setAmount(+e.target.value)} />
          <button className="dmg" onClick={() => op('character.hp.damage', { amount })}>Daño</button>
          <button className="heal" onClick={() => op('character.hp.heal', { amount })}>Curar</button>
        </div>
      </section>

      <section className="card">
        <h2>Descansos</h2>
        <div className="row">
          <button onClick={() => op('character.rest.short', {})}>Descanso corto</button>
          <button onClick={() => op('character.rest.long', {})}>Descanso largo</button>
        </div>
        {(d.hit_dice || []).map((p, i) => (
          <div key={i} className="row">
            <span>Dados de golpe {p.die}: {p.remaining}/{p.total}</span>
            <button disabled={p.remaining <= 0}
                    onClick={() => op('character.hit_die.spend', { pool: i })}>
              Gastar
            </button>
          </div>
        ))}
      </section>

      {Object.keys(slots).length > 0 && (
        <section className="card">
          <h2>Espacios de conjuro</h2>
          {Object.entries(slots).map(([lvl, s]) => (
            <div key={lvl} className="row">
              <span>Nivel {lvl}: {s.total - s.used}/{s.total}</span>
              <button disabled={s.used >= s.total}
                      onClick={() => op('character.spell_slot.use', { level: +lvl })}>
                Usar
              </button>
            </div>
          ))}
        </section>
      )}

      {(d.resources || []).length > 0 && (
        <section className="card">
          <h2>Recursos</h2>
          {d.resources.map((r) => (
            <div key={r.id} className="row">
              <span>{r.name}: {r.current}/{r.max} <em className="muted">({r.reset_on})</em></span>
              <button disabled={r.current <= 0}
                      onClick={() => op('character.resource.consume', { resource_id: r.id })}>
                Usar
              </button>
            </div>
          ))}
        </section>
      )}

      <section className="card optional">
        <h2>Monedas</h2>
        <div className="row purse">
          {['pp', 'gp', 'ep', 'sp', 'cp'].map((c) => (
            <span key={c} className="coin">{c.toUpperCase()}: {(d.purse || {})[c] || 0}</span>
          ))}
        </div>
        <div className="row">
          <input type="number" min="1" value={amount}
                 onChange={(e) => setAmount(+e.target.value)} />
          <select value={coin} onChange={(e) => setCoin(e.target.value)}>
            {['pp', 'gp', 'ep', 'sp', 'cp'].map((c) => <option key={c}>{c}</option>)}
          </select>
          <button className="heal" onClick={() => op('character.currency.earn', { [coin]: amount })}>+</button>
          <button className="dmg" onClick={() => op('character.currency.spend', { [coin]: amount })}>-</button>
        </div>
      </section>

      <section className="card">
        <h2>Acciones</h2>
        <button onClick={async () => {
          if (actions) { setActions(null); return }
          const r = await fetch(`/api/characters/${id}/actions`).then((x) => x.json())
          setActions(r.actions)
        }}>{actions ? 'Ocultar' : 'Ver acciones disponibles'}</button>
        {actions && Object.entries(actions).map(([g, list]) => (
          <div key={g}>
            <h3 className="muted" style={{ textTransform: 'capitalize' }}>{g.replace('_', ' ')}</h3>
            <ul>{list.map((a, i) => (
              <li key={i}>{a.name}
                {a.hit && <span className="muted"> {a.hit} · {a.damage}</span>}
                {a.name.startsWith('Ataque:') && (
                  <button style={{ minHeight: 32, marginLeft: 8 }}
                          onClick={async () => {
                    const w = a.name.replace('Ataque: ', '')
                    const r = await api.characterAttack(id, w)
                    setRollLog((l) => [`${w}: impacto ${r.hit.total} · daño ${r.damage.total}`, ...l].slice(0, 10))
                  }}>⚔</button>
                )}
                {a.name.startsWith('Conjuro:') && (
                  <button style={{ minHeight: 32, marginLeft: 8 }}
                          onClick={async () => {
                    await op('character.spell.cast',
                             { spell_id: a.source, level: 0 })
                  }}>✦</button>
                )}
              </li>))}
            </ul>
          </div>
        ))}
      </section>

      {(d.effects || []).length > 0 && (
        <section className="card optional">
          <h2>Efectos activos</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.effects.map((e) => (
              <span key={e.id} className="chip" title={e.source}>
                {e.name}
                <button aria-label={`Quitar efecto ${e.name}`} onClick={() =>
                  op('character.effect.remove', { effect_id: e.id })}>×</button>
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="card optional">
        <h2>Condiciones</h2>
        <div className="row">
          <input value={newCond} onChange={(e) => setNewCond(e.target.value)}
                 placeholder="poisoned, stunned…" list="cond-list" />
          <datalist id="cond-list">
            {condOptions.map((c) => <option key={c} value={c} />)}
          </datalist>
          <button disabled={!newCond.trim()} onClick={() => {
            op('character.condition.apply', { condition: newCond.trim() })
            setNewCond('')
          }}>Aplicar</button>
        </div>
        {(d.conditions || []).map((c) => (
          <span key={c} className="chip">
            {c}
            <button onClick={() => op('character.condition.remove', { condition: c })}>×</button>
          </span>
        ))}
      </section>

      <section className="card optional">
        <h2>Inventario</h2>
        <ItemPicker onPick={(it) =>
          op('character.inventory.add',
             { name: it.name, source_id: it.id })} />
        <div className="row">
          <input value={newItem} onChange={(e) => setNewItem(e.target.value)}
                 placeholder="Objeto manual" />
          <button disabled={!newItem.trim()} onClick={() => {
            op('character.inventory.add', { name: newItem.trim() })
            setNewItem('')
          }}>Añadir</button>
        </div>
        {(d.inventory || []).map((it) => (
          <div key={it.id} className="row">
            <span style={{ flex: 1 }}>
              {it.name} ×{it.quantity}
              {it.equipped && <span className="muted"> · equipado</span>}
              {it.attuned && <span className="muted"> · sintonizado</span>}
            </span>
            <button onClick={() =>
              op(it.equipped ? 'character.item.unequip'
                             : 'character.item.equip',
                 { item_id: it.id })
            }>{it.equipped ? 'Quitar' : 'Equipar'}</button>
            <button onClick={() => op('character.inventory.remove',
                                      { item_id: it.id, quantity: 1 })}>-</button>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>Dados</h2>
        <form onSubmit={doRoll} className="row">
          <input value={expr} onChange={(e) => setExpr(e.target.value)}
                 placeholder="2d6+3, 1d20adv, 4d6kh3" />
          <select value={rollType} onChange={(e) => setRollType(e.target.value)}>
            <option value="check">check</option>
            <option value="attack">attack</option>
            <option value="damage">damage</option>
            <optgroup label="Salvaciones">
              {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
                <option key={a} value={`save:${a}`}>save:{a}</option>))}
            </optgroup>
            <optgroup label="Habilidades">
              {['skill:perception', 'skill:stealth', 'skill:athletics',
                'skill:insight', 'skill:investigation', 'skill:persuasion']
                .map((s) => <option key={s} value={s}>{s.slice(6)}</option>)}
            </optgroup>
          </select>
          <button type="submit">Tirar</button>
        </form>
        <ul className="log">{rollLog.map((l, i) => <li key={i}>{l}</li>)}</ul>
      </section>

      <section className="card optional">
        <h2>Conjuros</h2>
        <SpellPicker onPick={(sid) =>
          op('character.spell.learn', { spell_id: sid })}
          placeholder="Aprender conjuro — buscar en todas las fuentes" />
        {(d.spells_known || []).length > 0 && (
          <SpellList ids={d.spells_known} onCast={(sid) =>
            op('character.spell.cast', { spell_id: sid, level: 0 })}
            onForget={(sid) =>
              op('character.spell.forget', { spell_id: sid })} />
        )}
      </section>

      {shops.length > 0 && (
        <section className="card optional">
          <h2>Tienda</h2>
          {shops.map((s) => (
            <div key={s.id}>
              <h3 className="muted">{s.name}</h3>
              {(s.data.stock || []).filter((x) => x.quantity > 0).map((it) => (
                <div key={it.name} className="row">
                  <span style={{ flex: 1 }}>{it.name} ×{it.quantity}</span>
                  <span className="muted">{it.price_cp}cp</span>
                  <button onClick={async () => {
                    await op('character.shop.buy',
                             { shop_id: s.id, item: it.name })
                    api.listEntities(char.campaign_id, 'shop', 'player')
                      .then((r) => setShops(r.entities))
                  }}>Comprar</button>
                </div>
              ))}
            </div>
          ))}
        </section>
      )}

      {(d.features || []).length > 0 && (
        <section className="card optional">
          <h2>Rasgos de clase</h2>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.features.map((f) => <span key={f} className="chip">{f}</span>)}
          </div>
        </section>)}

      <section className="card optional">
        <h2>Dotes y dones</h2>
        <SpellPicker entityType="feat" verb="Añadir"
          placeholder="Buscar dote en todas las fuentes"
          onPick={(fid) =>
            op('character.feat.learn', { feat_id: fid })} />
        {(d.feats_known || []).length > 0 && (
          <FeatList ids={d.feats_known} onForget={(fid) =>
            op('character.feat.forget', { feat_id: fid })} />)}
        <SpellPicker entityType="reward" verb="Añadir"
          placeholder="Don sobrenatural / bendición (charm, boon…)"
          onPick={(rid) =>
            op('character.reward.add', { reward_id: rid })} />
        {(d.rewards || []).length > 0 && (
          <FeatList ids={d.rewards} onForget={(rid) =>
            op('character.reward.remove', { reward_id: rid })} />)}
      </section>

      <section className="card optional">
        <h2>Subclase e idiomas</h2>
        <SpellPicker entityType="subclass" verb="Elegir"
          placeholder="Buscar subclase…"
          onPick={(sid) =>
            op('character.subclass.set',
               { class_index: 0, subclass_id: sid })} />
        {(d.classes || []).map((c, i) => (
          <p key={i} className="muted">
            {c.class_id}{c.subclass_id ? ` · ${c.subclass_id}` : ''}
            {' · nv.'}{c.level}</p>))}
        <SpellPicker entityType="language" verb="Añadir"
          placeholder="Idioma (elfo, común, dracónico…)"
          onPick={(lid) =>
            op('character.language.add',
               { name: lid.split(':').pop().split('|')[0] })} />
        {(d.languages || []).length > 0 && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.languages.map((l) => (
              <span key={l} className="chip">{l}
                <button aria-label={`Quitar idioma ${l}`} onClick={() =>
                  op('character.language.remove', { name: l })
                }>×</button></span>))}
          </div>)}
      </section>

      <section className="card optional">
        <h2>Competencias</h2>
        <SpellPicker entityType="skill" verb="Competente"
          placeholder="Habilidad (percepción, sigilo…)"
          onPick={(sid) =>
            op('character.proficiency.add',
               { kind: 'skill',
                 name: sid.split(':').pop().split('|')[0]
                      .replace(/-/g, ' ') })} />
        <div className="row">
          <span className="muted">Salvación:</span>
          {['str', 'dex', 'con', 'int', 'wis', 'cha'].map((a) => (
            <button key={a} className="ghost" onClick={() =>
              op('character.proficiency.add',
                 { kind: 'save', name: a })}>{a.toUpperCase()}</button>))}
        </div>
        {(d.skill_proficiencies?.length > 0 || d.save_proficiencies?.length > 0) && (
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {d.save_proficiencies?.map((s) => (
              <span key={s} className="chip">save:{s}
                <button aria-label={`Quitar competencia ${s}`} onClick={() =>
                  op('character.proficiency.remove',
                     { kind: 'save', name: s })}>×</button>
              </span>))}
            {d.skill_proficiencies?.map((s) => (
              <span key={s} className="chip">{s}
                <button aria-label={`Quitar competencia ${s}`} onClick={() =>
                  op('character.proficiency.remove',
                     { kind: 'skill', name: s })}>×</button>
              </span>))}
          </div>
        )}
      </section>

      <section className="card optional">
        <h2>Diario</h2>
        <div className="row">
          <input value={journalEntry} placeholder="Anotación de la sesión…"
                 onChange={(e) => setJournalEntry(e.target.value)} />
          <button disabled={!journalEntry.trim()} onClick={() => {
            op('character.journal.add', { entry: journalEntry.trim() })
            setJournalEntry('')
          }}>Anotar</button>
        </div>
        <ul>{(d.narrative?.journal || []).map((j, i) => <li key={i}>{j}</li>)}</ul>
      </section>
    </main>
  )
}


function ItemPicker({ onPick }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const go = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    const r = await api.search(q.trim())
    setHits(r.results
      .filter((h) => ['item', 'magic-item', 'equipment']
        .includes(h.entity_type))
      .slice(0, 12))
  }
  return (
    <div>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Buscar objeto en el corpus (daga, potion…)" />
        <button type="submit">Buscar</button>
      </form>
      {hits.length > 0 && (
        <ul>
          {hits.map((h) => (
            <li key={h.id} className="row">
              <span style={{ flex: 1 }}>{h.name}
                <span className="muted"> · {h.source_id}</span></span>
              <button onClick={() => { onPick(h); setHits([]) }}>
                Añadir</button>
            </li>))}
        </ul>)}
    </div>
  )
}


function SpellPicker({ onPick, entityType = 'spell',
                      verb = 'Aprender',
                      placeholder = 'Buscar en todas las fuentes' }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const go = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    const r = await api.search(q.trim(), entityType)
    setHits(r.results.slice(0, 12))
  }
  return (
    <div>
      <form onSubmit={go} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={placeholder} />
        <button type="submit">Buscar</button>
      </form>
      {hits.length > 0 && (
        <ul>
          {hits.map((h) => (
            <li key={h.id} className="row">
              <span style={{ flex: 1 }}>{h.name}
                <span className="muted"> · {h.source_id}</span></span>
              <button onClick={() => { onPick(h.id); setHits([]) }}>
                {verb}</button>
            </li>))}
        </ul>)}
    </div>
  )
}


function SpellList({ ids, onCast, onForget }) {
  const [names, setNames] = useState({})
  useEffect(() => {
    for (const sid of ids) {
      if (names[sid]) continue
      api.getEntity(sid)
        .then((e) => setNames((n) => ({ ...n, [sid]: e.name || sid })))
        .catch(() => setNames((n) => ({ ...n, [sid]: sid })))
    }
  }, [ids])
  return (
    <ul>
      {ids.map((sid) => (
        <li key={sid} className="row">
          <span style={{ flex: 1 }}>{names[sid] || sid}</span>
          <button onClick={() => onCast(sid)}>Lanzar</button>
          <button className="ghost" onClick={() => onForget(sid)}>×</button>
        </li>
      ))}
    </ul>
  )
}


function FeatList({ ids, onForget }) {
  const [names, setNames] = useState({})
  useEffect(() => {
    for (const fid of ids) {
      if (names[fid]) continue
      api.getEntity(fid)
        .then((e) => setNames((n) => ({ ...n, [fid]: e.name || fid })))
        .catch(() => setNames((n) => ({ ...n, [fid]: fid })))
    }
  }, [ids])
  return (
    <ul>
      {ids.map((fid) => (
        <li key={fid} className="row">
          <span style={{ flex: 1 }}>{names[fid] || fid}</span>
          <button className="ghost" onClick={() => onForget(fid)}>×</button>
        </li>))}
    </ul>
  )
}
