import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { ItemPicker } from './pickers.jsx'
import { AttackPanel, Section } from './panels.jsx'
import { abilityScore } from './data.js'

/** Pestaña Inventario: monedas, objetos (equipado/mochila/
    consumibles), fabricación, entrega a compañeros y tiendas de
    la campaña. */
export default function TabInventario({ c }) {
  const { id, char, d, op, t, tf, focus, hud, tab,
          amount, setAmount, coin, setCoin,
          invTab, setInvTab, newItem, setNewItem,
          atkItem, setAtkItem, shops, setShops, setRollLog, load } = c
  const show = (g) => focus ? hud.has(g) : tab === g
  // compañeros de grupo para pasar objetos (transferencia atómica)
  const [party, setParty] = useState(null)
  useEffect(() => {
    if (!char.campaign_id) { setParty(null); return }
    api.listCharacters(char.campaign_id)
      .then((r) => setParty((r.characters || [])
        .filter((x) => x.id !== id)))
      .catch(() => setParty(null))
  }, [char.campaign_id])
  return (<div className="sheet-cols">
    <Section title={t('sheet.currency')}  hidden={!show('inventario')} extraClass="optional">
      <div className="row purse">
        {['pp', 'gp', 'ep', 'sp', 'cp'].map((cc) => (
          <span key={cc} className="coin">{cc.toUpperCase()}: {(d.purse || {})[cc] || 0}</span>
        ))}
      </div>
      <div className="row">
        <input type="number" min="1" value={amount}
               onChange={(e) => setAmount(+e.target.value)} />
        <select value={coin} onChange={(e) => setCoin(e.target.value)}>
          {['pp', 'gp', 'ep', 'sp', 'cp'].map((cc) => <option key={cc}>{cc}</option>)}
        </select>
        <button className="heal" onClick={() => op('character.currency.earn', { [coin]: amount })}>+</button>
        <button className="dmg" onClick={() => op('character.currency.spend', { [coin]: amount })}>-</button>
        <details style={{ position: 'relative' }}>
          <summary className="muted" style={{ cursor: 'pointer' }}
                   title={t('inv.convertTitle')}>⇄</summary>
          <form className="row" onSubmit={(e) => {
            e.preventDefault()
            const f = e.target
            op('character.currency.convert', {
              from: f.cfrom.value, to: f.cto.value,
              amount: +f.camt.value })
          }}>
            <input name="camt" type="number" min="1" required
                   placeholder={t('inv.amount')} style={{ maxWidth: 64 }}
                   aria-label={t('inv.convertAmt')} />
            <select name="cfrom" aria-label={t('inv.from')}>
              {['pp', 'gp', 'ep', 'sp', 'cp'].map((cc) =>
                <option key={cc}>{cc}</option>)}</select>
            <span className="muted">→</span>
            <select name="cto" aria-label={t('inv.to')} defaultValue="gp">
              {['pp', 'gp', 'ep', 'sp', 'cp'].map((cc) =>
                <option key={cc}>{cc}</option>)}</select>
            <button type="submit" className="ghost">{t('inv.convert')}</button>
          </form>
        </details>
      </div>
    </Section>

    <Section title={t('sheet.inventory')}  hidden={!show('inventario')} extraClass="optional">
      <p className="muted">
        {t('inv.attuned')}:{' '}
        {(d.inventory || []).filter((i) => i.attuned).length}/3
      </p>
      <ItemPicker onPick={(it) =>
        op('character.inventory.add',
           { name: it.name, source_id: it.id })} />
      <div className="row">
        <input value={newItem} onChange={(e) => setNewItem(e.target.value)}
               placeholder={t('inv.manualPh')} />
        <button disabled={!newItem.trim()} onClick={() => {
          op('character.inventory.add', { name: newItem.trim() })
          setNewItem('')
        }}>{t('common.add')}</button>
      </div>
      {/* fabricación (downtime): consume ingredientes de la mochila
          y produce el objeto — la operación es reversible */}
      <details>
        <summary className="muted" style={{ cursor: 'pointer' }}>
          {t('inv.craftTitle')}</summary>
        <form className="row" style={{ flexWrap: 'wrap' }}
              onSubmit={(e) => {
          e.preventDefault()
          const f = e.target
          op('character.craft', {
            inputs: [{ name: f.cing.value,
                       quantity: +f.cqty.value || 1 }],
            output: { name: f.cout.value.trim(),
                      quantity: +f.coqty.value || 1 } })
          f.reset()
        }}>
          <select name="cing" required aria-label={t('inv.craftIng')}>
            {(d.inventory || []).map((i) => (
              <option key={i.id} value={i.name}>
                {i.name} ×{i.quantity}</option>))}
          </select>
          <input name="cqty" type="number" min="1" defaultValue="1"
                 style={{ maxWidth: 56 }} aria-label={t('inv.craftQty')} />
          <span className="muted">→</span>
          <input name="cout" required maxLength={40}
                 placeholder={t('inv.craftOutPh')}
                 aria-label={t('inv.craftOutPh')} />
          <input name="coqty" type="number" min="1" defaultValue="1"
                 style={{ maxWidth: 56 }} aria-label={t('inv.craftQty')} />
          <button type="submit">{t('inv.craftGo')}</button>
        </form>
      </details>
      {/* pasar un objeto a otro miembro del grupo — el backend lo
          hace en una transacción atómica e idempotente */}
      {party?.length > 0 && (
        <details>
          <summary className="muted" style={{ cursor: 'pointer' }}>
            {t('inv.giveTitle')}</summary>
          <form className="row" style={{ flexWrap: 'wrap' }}
                onSubmit={async (e) => {
            e.preventDefault()
            const f = e.target
            try {
              await api.transferItem(id, f.gto.value,
                                     f.gitem.value,
                                     +f.gqty.value || 1)
              setRollLog((l) => [t('inv.giveDone'), ...l].slice(0, 10))
              load()
            } catch (ex) {
              setRollLog((l) => [`⚠ ${ex.message}`, ...l].slice(0, 10))
            }
          }}>
            <select name="gitem" required aria-label={t('inv.giveItem')}>
              {(d.inventory || []).map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} ×{i.quantity}</option>))}
            </select>
            <input name="gqty" type="number" min="1" defaultValue="1"
                   style={{ maxWidth: 56 }} aria-label={t('inv.craftQty')} />
            <span className="muted">→</span>
            <select name="gto" required aria-label={t('inv.giveTo')}>
              {party.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>))}
            </select>
            <button type="submit">{t('inv.giveGo')}</button>
          </form>
        </details>)}
      {/* capacidad de carga: FUE × 15 lb — las monedas también
          pesan (regla 5e: 50 monedas = 1 lb) */}
      {(() => {
        const wt = (d.inventory || []).reduce(
          (a, i) => a + (i.weight || 0) * i.quantity, 0)
        const coins = Object.values(d.purse || {})
          .reduce((a, n) => a + (n || 0), 0)
        const total = wt + coins / 50
        if (!total) return null
        const cap = abilityScore(d.abilities, 'str') * 15
        const over = total > cap
        return (
          <div className="row"
               title={tf('inv.capTitle', { cap }) +
                 (coins ? tf('inv.capCoins',
                             { n: coins, w: +(coins / 50).toFixed(1) })
                        : '')}>
            <span className="muted" style={{ fontSize: '.8rem' }}>
              ⚖ {+total.toFixed(1)}/{cap} lb{over
                ? ` — ${t('inv.over')}` : ''}
            </span>
            <div className="hp-bar xp" style={{ flex: 1 }}>
              <div style={{
                width: `${Math.min(100, total / cap * 100)}%`,
                background: over ? 'var(--danger)' : undefined }} />
            </div>
          </div>)
      })()}
      <div className="row tabs" role="tablist"
           aria-label={t('sheet.inventory')}>
        {[['equipado', t('sheet.equipped')], ['mochila', t('sheet.backpack')],
          ['consumibles', t('sheet.consumables')]].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={invTab === k}
                  title={t('inv.dragHint')}
                  onClick={() => setInvTab(k)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault()
                    const iid = e.dataTransfer.getData('text/plain')
                    if (!iid) return
                    if (k === 'equipado')
                      op('character.item.equip', { item_id: iid })
                    else
                      op('character.item.unequip', { item_id: iid })
                  }}>{l}</button>))}
      </div>
      {(d.inventory || []).filter((it) => {
        if (invTab === 'equipado') return it.equipped
        const consum = /poci|potion|scroll|pergamino|antorcha|torch|flecha|arrow|raci[oó]n|ration/i.test(it.name)
        if (invTab === 'consumibles') return consum && !it.equipped
        return !it.equipped && !consum          // mochila
      }).map((it) => (
        <div key={it.id} className="row draggable" draggable
             onDragStart={(e) =>
               e.dataTransfer.setData('text/plain', it.id)}
             title={t('inv.dragItemHint')}>
          <span style={{ flex: 1 }}>
            {it.name} ×{it.quantity}
            {it.weight > 0 && <span className="muted">
              {' '}· {+(it.weight * it.quantity).toFixed(1)} lb</span>}
            {it.equipped &&
              <span className="muted"> · {t('inv.eqTag')}</span>}
            {it.attuned &&
              <span className="muted"> · {t('inv.atTag')}</span>}
            {it.charges_max > 0 && (
              <span className="pips" role="group"
                    aria-label={tf('inv.chargesAria',
                                   { name: it.name,
                                     n: it.charges ?? 0,
                                     max: it.charges_max })}>
                {Array.from({ length: it.charges_max }, (_, j) => {
                  const free = j < (it.charges ?? 0)
                  return (
                    <button key={j}
                            className={`pip${free ? '' : ' used'}`}
                            aria-label={free
                              ? tf('inv.chargeSpend', { name: it.name })
                              : tf('inv.chargeRecover', { name: it.name })}
                            onClick={() => op(free
                              ? 'character.item.charge.use'
                              : 'character.item.charge.restore',
                              free ? { item_id: it.id }
                                   : { item_id: it.id,
                                       charges: (it.charges ?? 0) + 1,
                                       charges_max: it.charges_max })} />)
                })}
              </span>)}
          </span>
          <button className="ghost" style={{ minHeight: 30 }}
                  title={t('inv.weightTitle')}
                  aria-label={tf('inv.weightAria', { name: it.name })}
                  onClick={() => {
            const n = window.prompt(
              tf('inv.weightPrompt', { name: it.name }), it.weight || 0)
            if (n === null) return
            op('character.item.weight.set',
               { item_id: it.id, weight: Math.max(0, +n || 0) })
          }}>⚖</button>
          <button className="ghost" style={{ minHeight: 30 }}
                  title={t('inv.chargeTitle')}
                  aria-label={tf('inv.chargeAria', { name: it.name })}
                  onClick={() => {
            const n = window.prompt(
              tf('inv.chargePrompt', { name: it.name }),
              it.charges_max ?? 3)
            if (n === null) return
            op('character.item.charge.set',
               { item_id: it.id, max: Math.max(0, +n || 0) })
          }}>⚡</button>
          {it.source_id && (
            <button onClick={() => setAtkItem(it)}>
              {t('sheet.attack')}</button>)}
          <button className="ghost" aria-pressed={!!it.attuned}
                  title={it.attuned ? t('inv.unattune') : t('inv.attune')}
                  aria-label={tf('inv.attuneAria', { name: it.name })}
                  onClick={() =>
                    op(it.attuned ? 'character.item.unattune'
                                  : 'character.item.attune',
                       { item_id: it.id })
                  }>{it.attuned ? '⭑' : '☆'}</button>
          <button onClick={() =>
            op(it.equipped ? 'character.item.unequip'
                           : 'character.item.equip',
               { item_id: it.id })
          }>{it.equipped ? t('inv.unequip') : t('inv.equip')}</button>
          <button onClick={() => op('character.inventory.remove',
                                    { item_id: it.id, quantity: 1 })}>
            {invTab === 'consumibles' ? t('common.use') : '-'}</button>
        </div>
      ))}
      {invTab === 'equipado' &&
        !(d.inventory || []).some((i) => i.equipped) && (
        <p className="muted">{t('inv.emptyEquipped')}</p>)}
      {atkItem && (
        <AttackPanel charId={id} item={atkItem}
                     onResult={(line) =>
                       setRollLog((l) => [line, ...l].slice(0, 10))}
                     onClose={() => setAtkItem(null)} />)}
    </Section>

    {shops.length > 0 && (
      <Section title={t('inv.shop')}  hidden={!show('inventario')} extraClass="optional">
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
                    .catch(() => {})  // stock se refresca al reentrar
                }}>{t('inv.buy')}</button>
              </div>
            ))}
          </div>
        ))}
      </Section>
    )}
  </div>)
}
