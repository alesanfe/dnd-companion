import { useState } from 'react'
import { api } from '../../api.js'
import WikiText from '../WikiText.jsx'

const REL_TYPES = ['knows', 'ally', 'enemy', 'family', 'works_for',
                   'owns', 'located_in', 'quest_giver', 'member_of',
                   'hates', 'loves', 'owes']

/** Pestaña Campaña: entidades con visibilidad (PNJ, lugares,
    misiones, facciones, escenas, notas), relaciones entre ellas,
    revelación y VTT export. */
export default function DmCampana({ c }) {
  const { t, tf, dmTab, campaign, playerView,
          entities, setEntities, entForm, setEntForm, refresh } = c
  const [rels, setRels] = useState(null)   // lazy: se cargan al abrir
  const [members, setMembers] = useState(null)
  const [editNotes, setEditNotes] = useState(null) // entidad en edición
  const [shareEnt, setShareEnt] = useState(null)   // entidad compartiendo
  const [notesDraft, setNotesDraft] = useState('')
  if (!campaign) return null
  const show = dmTab === 'campana'
  const reload = () =>
    api.listEntities(campaign.id).then((r) => setEntities(r.entities))
  const loadRels = () =>
    api.listRelationships(campaign.id).then((r) => setRels(r.relationships))
  const nameOf = (eid) =>
    entities.find((e) => e.id === eid)?.name || eid.slice(0, 8)
  return (
    <section className="card" hidden={!show}>
      <h2>{t('dm.entities')}
        <button className="ghost" style={{ float: 'right' }}
                title={t('camp.vttHint')}
                onClick={async () => {
          const data = await api.exportVtt(campaign.id)
          const blob = new Blob([JSON.stringify(data, null, 2)],
                                { type: 'application/json' })
          const a = document.createElement('a')
          a.href = URL.createObjectURL(blob)
          a.download = `${campaign.name || 'campaign'}-vtt.json`
          a.click()
        }}>{t('dm.exportvtt')}</button>
      </h2>
      <div className="row">
        <select value={entForm.kind}
                onChange={(e) => setEntForm({ ...entForm, kind: e.target.value })}>
          <option value="npc">NPC</option>
          <option value="location">{t('camp.kind.location')}</option>
          <option value="quest">{t('camp.kind.quest')}</option>
          <option value="faction">{t('camp.kind.faction')}</option>
          <option value="scene">{t('camp.kind.scene')}</option>
          <option value="shop">{t('camp.k.shop')}</option>
          <option value="note">{t('camp.kind.note')}</option>
        </select>
        <input value={entForm.name} placeholder={t('camp.name')}
               onChange={(e) => setEntForm({ ...entForm, name: e.target.value })} />
        {/* notas con wiki-links: [[Nombre]] enlaza a otra entidad
            (o al compendio si no existe) — estilo Kanka */}
        <input value={entForm.notes || ''}
               placeholder={t('camp.notesPh')}
               title={t('camp.wikiHint')} style={{ flex: 1 }}
               onChange={(e) => setEntForm({ ...entForm,
                                             notes: e.target.value })} />
        {entForm.kind === 'scene' && (
          <input value={entForm.monsters}
                 placeholder={t('camp.monstersPh')}
                 onChange={(e) => setEntForm({ ...entForm, monsters: e.target.value })} />
        )}
        {entForm.kind === 'shop' && (
          <input value={entForm.stock || ''} style={{ flex: 1 }}
                 placeholder={t('camp.stockPh')}
                 title={t('camp.stockHint')}
                 onChange={(e) => setEntForm({ ...entForm, stock: e.target.value })} />
        )}
        <button disabled={!entForm.name} onClick={async () => {
          const data = { notes: entForm.notes }
          if (entForm.kind === 'scene' && entForm.monsters.trim()) {
            // resuelve nombres a ids de contenido (primer resultado)
            const ids = []
            for (const term of entForm.monsters.split(',')) {
              const s = await api.search(term.trim(), 'monster')
              if (s.results[0]) ids.push(s.results[0].id)
            }
            data.monsters = ids
          }
          if (entForm.kind === 'shop' && entForm.stock?.trim()) {
            // stock: "nombre | precio_cp | cantidad" separado por comas
            data.stock = entForm.stock.split(',').map((x) => {
              const [nm, pr, qt] = x.split('|').map((s) => s.trim())
              return nm ? { name: nm, price_cp: +pr || 0,
                            quantity: +qt || 1 } : null
            }).filter(Boolean)
          }
          await api.createEntity(campaign.id, {
            kind: entForm.kind, name: entForm.name,
            data,
            // las tiendas nacen públicas: los jugadores compran
            // directamente en su ficha (inv.shop)
            visibility: entForm.kind === 'shop' ? 'public' : 'dm',
          })
          setEntForm({ ...entForm, name: '', notes: '', monsters: '',
                       stock: '' })
          reload()
        }}>{t('camp.createPrivate')}</button>
      </div>
      <button onClick={reload}>{t('camp.loadList')}</button>
      {entities
        .filter((e) => !playerView || e.visibility === 'public')
        .map((e) => (
        <div key={e.id} id={`ent-${e.id}`}>
        <div className="row">
          <span className="muted">{e.kind}</span>
          <span style={{ flex: 1 }}>{e.name}</span>
          {!playerView && (
            <>
              <button className="ghost" aria-label={tf('camp.deleteAria',
                                        { name: e.name })}
                      onClick={async () => {
                if (!confirm(tf('camp.deleteConfirm', { name: e.name }))) return
                await api.deleteEntity(campaign.id, e.id)
                reload()
              }}>×</button>
              {e.kind === 'shop' && (
                <button className="ghost" title={t('camp.stockHint')}
                        aria-label={tf('camp.restockAria',
                                       { name: e.name })}
                        onClick={async () => {
                  const line = prompt(t('camp.restockPrompt'))
                  if (!line?.trim()) return
                  const [nm, pr, qt] = line.split('|').map((s) => s.trim())
                  if (!nm) return
                  // append con optimistic lock + rebase — stock se
                  // toca desde varios sitios (compra del jugador)
                  await api.patchEntityRebase(campaign.id, e, (d) => ({
                    ...d,
                    stock: [...(d.stock || []),
                            { name: nm, price_cp: +pr || 0,
                              quantity: +qt || 1 }],
                  }))
                  reload()
                }}>📦</button>)}
              {e.kind === 'scene' && (e.data.monsters || []).length > 0 && (
                <button style={{ minHeight: 32 }} onClick={async () => {
                  const r = await api.startScene(campaign.id, e.id)
                  refresh(r.combat_id)
                }}>▶ {t('ses.combatBtn')}</button>
              )}
              {e.visibility === 'dm' && (
                <button onClick={async () => {
                  await api.revealEntity(campaign.id, e.id)
                  reload()
                }}>{t('dm.reveal')}</button>
              )}
              {/* 📺 proyectar al grupo: la entidad pública aparece como
                  modal en la pantalla de todos los jugadores */}
              {e.visibility === 'public' && (
                <button className="ghost"
                        title={t('camp.present')}
                        aria-label={`${t('camp.present')} ${e.name}`}
                        onClick={() =>
                          api.present(campaign.id, e.id)
                            .catch(() => {})}>📺</button>)}
              <button className="ghost" title={t('camp.editNotes')}
                      aria-label={tf('camp.notesAria',
                                     { name: e.name })}
                      aria-expanded={editNotes === e.id}
                      onClick={() => {
                setEditNotes(editNotes === e.id ? null : e.id)
                setNotesDraft(e.data?.notes || '')
              }}>✎</button>
              {/* 👥 visibilidad parcial: known_to + auto-revelado —
                  el schema/endpoint existían sin ninguna UI */}
              {e.visibility !== 'public' && (
                <button className="ghost" title={t('camp.share')}
                        aria-label={`${t('camp.share')} ${e.name}`}
                        aria-expanded={shareEnt === e.id}
                        onClick={() => {
                  setShareEnt(shareEnt === e.id ? null : e.id)
                  if (shareEnt !== e.id && !members)
                    api.listMembers(campaign.id)
                      .then((r) => setMembers(r.members))
                      .catch(() => {})
                }}>👥</button>)}
            </>)}
        </div>
        {shareEnt === e.id && (
          <div className="row" style={{ flexWrap: 'wrap',
                                       fontSize: '.85rem' }}>
            {/* known_to: jugadores que ven esta entidad aunque no
                sea pública */}
            <label className="muted">{t('camp.knownTo')}
              <select aria-label={t('camp.knownTo')} value=""
                      onChange={async (ev) => {
                const uid = ev.target.value
                if (!uid) return
                const kt = [...new Set([...(e.known_to || []), uid])]
                try {
                  await api.patchEntity(campaign.id, e.id, {
                    known_to: kt, expected_version: e.version })
                } catch { reload(); return }   // 409 → lista fresca
                reload()
              }}>
                <option value="">—</option>
                {(members || [])
                  .filter((m) => !['owner', 'co_dm'].includes(m.role))
                  .filter((m) => !(e.known_to || [])
                            .includes(m.user_id))
                  .map((m) => <option key={m.user_id}
                                      value={m.user_id}>
                    {m.user_id}</option>)}
              </select></label>
            {(e.known_to || []).map((uid) => (
              <button key={uid} className="ghost"
                      title={t('camp.unshare')}
                      onClick={async () => {
                try {
                  await api.patchEntity(campaign.id, e.id, {
                    known_to: (e.known_to || [])
                              .filter((u) => u !== uid),
                    expected_version: e.version })
                } catch { /* 409 → la lista se refresca igual */ }
                reload()
              }}>{uid} ×</button>))}
            {/* reveal_condition: auto-revelar al arrancar sesión */}
            <label className="muted">{t('camp.autoReveal')}
              <select value={e.reveal_condition || 'manual'}
                      aria-label={t('camp.autoReveal')}
                      onChange={async (ev) => {
                try {
                  await api.patchEntity(campaign.id, e.id, {
                    reveal_condition: ev.target.value === 'manual'
                      ? null : ev.target.value,
                    expected_version: e.version })
                } catch { /* 409 → la lista se refresca igual */ }
                reload()
              }}>
                <option value="manual">{t('camp.revealManual')}</option>
                <option value="session_active">
                  {t('camp.revealSession')}</option>
              </select></label>
          </div>)}
        {/* notas con wiki-links — el mismo texto lo ven los
            jugadores en su tablero cuando la entidad es pública */}
        {e.data?.notes && editNotes !== e.id && (
          <p className="muted" style={{ margin: '0 0 .3rem' }}>
            <WikiText text={e.data.notes} entities={entities} /></p>)}
        {editNotes === e.id && (
          <div>
            <textarea value={notesDraft} rows={3}
                      aria-label={t('camp.notesAria2')}
                      title={t('camp.wikiHint')}
                      onChange={(ev) => setNotesDraft(ev.target.value)}
                      style={{ width: '100%' }} />
            <div className="row">
              {/* insertar [[mención]] sin recordar la sintaxis */}
              <select value="" aria-label={t('camp.insertMention')}
                      onChange={(ev) => {
                const n = ev.target.value
                if (n) setNotesDraft((d) =>
                  `${d}${d && !d.endsWith(' ') ? ' ' : ''}[[${n}]]`)
              }}>
                <option value="">{t('camp.insertMention')}</option>
                {entities.filter((x) => x.id !== e.id).map((x) => (
                  <option key={x.id} value={x.name}>{x.name}</option>))}
              </select>
              <button onClick={async () => {
                try {
                  // data se mergea en el servidor — el draft escribe
                  // sobre la copia fresca si hubo una carrera (409)
                  await api.patchEntityRebase(campaign.id, e, (d) => ({
                    ...d, notes: notesDraft }))
                } catch { return }   // entidad borrada: conservar draft
                setEditNotes(null)
                reload()
              }}>{t('common.save')}</button>
            </div>
          </div>)}
        </div>
      ))}

      {/* quién está dentro de la campaña (rol + alta) */}
      <details onToggle={(e) =>
                 e.target.open && members === null &&
                 api.listMembers(campaign.id)
                   .then((r) => setMembers(r.members))
                   .catch(() => setMembers([]))}>
        <summary className="muted" style={{ cursor: 'pointer' }}>
          {t('mem.title')} {members ? `(${members.length})` : ''}</summary>
        {(members || []).map((m) => (
          <div key={m.user_id} className="row">
            <span style={{ flex: 1 }}>{m.user_id}</span>
            <span className="muted">{m.role}</span>
          </div>))}
        {members?.length === 0 && (
          <p className="muted">{t('mem.empty')}</p>)}
      </details>

      {/* grafo de relaciones entre entidades (aliados, enemigos,
          dueños de tiendas, gancho de misión…) — las públicas se
          muestran a los jugadores en el tablero */}
      {entities.length > 1 && (
        <details onToggle={(e) =>
                   e.target.open && rels === null && loadRels()}>
          <summary className="muted" style={{ cursor: 'pointer' }}>
            {t('rel.title')} {rels ? `(${rels.length})` : ''}</summary>
          <form className="row" style={{ flexWrap: 'wrap' }}
                onSubmit={async (e) => {
            e.preventDefault()
            const f = e.target
            if (!f.rtype.value.trim()) return
            await api.createRelationship(campaign.id, {
              from_id: f.rfrom.value, to_id: f.rto.value,
              type: f.rtype.value.trim(),
              description: f.rdesc.value.trim() || null,
              world_date: f.rdate.value.trim() || null,
              visibility: f.rpub.checked ? 'public' : 'dm',
            })
            f.rdesc.value = ''; f.rdate.value = ''
            loadRels()
          }}>
            <select name="rfrom" required aria-label={t('rel.from')}>
              {entities.map((e) => (
                <option key={e.id} value={e.id}>{e.name}</option>))}
            </select>
            <input name="rtype" required maxLength={30}
                   list="rel-types" placeholder={t('rel.typePh')}
                   aria-label={t('rel.typePh')} />
            <datalist id="rel-types">
              {REL_TYPES.map((x) => <option key={x} value={x} />)}
            </datalist>
            <select name="rto" required aria-label={t('rel.to')}>
              {entities.map((e) => (
                <option key={e.id} value={e.id}>{e.name}</option>))}
            </select>
            <input name="rdesc" maxLength={80}
                   placeholder={t('rel.descPh')}
                   aria-label={t('rel.descPh')}
                   style={{ width: '10rem' }} />
            <input name="rdate" maxLength={20}
                   placeholder={t('rel.datePh')} title={t('rel.datePh')}
                   aria-label={t('rel.datePh')}
                   style={{ width: '7rem' }} />
            <label className="muted" style={{ fontSize: '.85rem' }}>
              <input type="checkbox" name="rpub" />
              {' '}{t('rel.public')}</label>
            <button type="submit">{t('common.add')}</button>
          </form>
          {(rels || []).map((r) => (
            <div key={r.id} className="row">
              <span style={{ flex: 1 }}
                    title={r.description || undefined}>
                {r.world_date &&
                  <span className="muted">{r.world_date} · </span>}
                {nameOf(r.from_id)} —<i>{r.type}</i>→ {nameOf(r.to_id)}
                {r.status && r.status !== 'active' && (
                  <span className="muted"> ({r.status})</span>)}
              </span>
              <span className="muted"
                    title={r.visibility === 'public'
                           ? t('rel.pubTag') : t('rel.dmTag')}>
                {r.visibility === 'public' ? '👁' : '🙈'}</span>
              {!playerView && (
                <button className="ghost"
                        aria-label={t('rel.delAria')}
                        onClick={async () => {
                  await api.deleteRelationship(campaign.id, r.id)
                  loadRels()
                }}>×</button>)}
            </div>))}
        </details>)}
    </section>
  )
}
