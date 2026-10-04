import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errText } from '../api.js'
import { useT } from '../i18n.jsx'
import { trackTask } from '../metrics.js'

const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha']
const STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
// prioridad de características por clase (orden de asignación)
const CLASS_PRIORITY = {
  barbarian: ['str', 'con', 'dex', 'wis', 'cha', 'int'],
  bard: ['cha', 'dex', 'con', 'wis', 'int', 'str'],
  cleric: ['wis', 'str', 'con', 'dex', 'int', 'cha'],
  druid: ['wis', 'con', 'dex', 'int', 'cha', 'str'],
  fighter: ['str', 'con', 'dex', 'wis', 'cha', 'int'],
  monk: ['dex', 'wis', 'con', 'str', 'cha', 'int'],
  paladin: ['str', 'cha', 'con', 'wis', 'dex', 'int'],
  ranger: ['dex', 'wis', 'con', 'str', 'int', 'cha'],
  rogue: ['dex', 'int', 'con', 'cha', 'wis', 'str'],
  sorcerer: ['cha', 'con', 'dex', 'wis', 'int', 'str'],
  warlock: ['cha', 'con', 'dex', 'wis', 'int', 'str'],
  wizard: ['int', 'dex', 'con', 'wis', 'cha', 'str'],
}

const DRAFT_KEY = 'dc.wizard-draft'

function loadDraft() {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY)) || {} }
  catch { return {} }
}

export default function Wizard() {
  const { t, tf } = useT()
  const nav = useNavigate()
  const [draft] = useState(loadDraft)
  const [step, setStep] = useState(draft.step ?? 0)
  const [name, setName] = useState(draft.name ?? '')
  const [ruleset, setRuleset] = useState(draft.ruleset ?? 'dnd5e-2014')
  const [classes, setClasses] = useState([])
  const [species, setSpecies] = useState([])
  const [backgrounds, setBackgrounds] = useState([])
  const [classId, setClassId] = useState(draft.classId ?? '')
  const [speciesId, setSpeciesId] = useState(draft.speciesId ?? '')
  const [backgroundId, setBackgroundId] = useState(draft.backgroundId ?? '')
  const [abilities, setAbilities] = useState(draft.abilities ?? {})
  const [remaining, setRemaining] = useState([...STANDARD_ARRAY])
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  // nombre legible de la opción elegida (las listas traen .name);
  // fallback: slug humanizado por si la lista aún no cargó
  const disp = (list, id) =>
    id ? (list.find((o) => o.id === id)?.name ??
          id.split(':').pop().split('|')[0].replace(/-/g, ' '))
       : '—'

  // con all_sources el corpus puede traer cientos de opciones
  // homebrew — SRD/Open5e primero para que lo oficial no quede
  // enterrado alfabéticamente
  const officialFirst = (opts = []) => [...opts].sort((a, b) => {
    const off = (o) => /srd-|open5e|5e-bits/.test(o.source_id || '') ? 0 : 1
    return off(a) - off(b) || (a.name || '').localeCompare(b.name || '')
  })

  useEffect(() => {
    // all_sources: ofrece también homebrew/UA/terceros importados
    api.contentOptions('class', ruleset, true)
      .then((r) => setClasses(officialFirst(r.options)))
      .catch((e) => setErr(errText(e, t)))
    // 2024 usa 'species'; 2014 usa 'race'; 'mixed' trae ambos
    Promise.all([
      api.contentOptions('race', ruleset, true),
      api.contentOptions('species', ruleset, true),
    ]).then(([a, b]) => {
      const seen = new Set()
      setSpecies(officialFirst([...a.options, ...b.options]
        .filter((o) => !seen.has(o.id) && seen.add(o.id))))
    }).catch(() => {})
    api.contentOptions('background', ruleset, true)
      .then((r) => setBackgrounds(officialFirst(r.options))).catch(() => {})
  }, [ruleset])

  // borrador persistente: salir del wizard o cerrar la pestaña no
  // debe destruir medio personaje (UX: conservar trabajo en curso)
  useEffect(() => {
    const d = { step, name, ruleset, classId, speciesId,
                backgroundId, abilities }
    if (!name && !classId && !Object.keys(abilities).length &&
        step === 0) {
      localStorage.removeItem(DRAFT_KEY)   // nada empezado
      return
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify(d))
  }, [step, name, ruleset, classId, speciesId, backgroundId, abilities])

  const assign = (ab, val) => {
    const prev = abilities[ab]
    const next = { ...abilities, [ab]: +val }
    const used = Object.values(next)
    const left = STANDARD_ARRAY.filter((v) => {
      const i = used.indexOf(v)
      if (i === -1) return true
      used.splice(i, 1)
      return false
    })
    setAbilities(next)
    setRemaining(left)
    void prev
  }

  const submit = async () => {
    if (busy) return                        // doble clic = doble ficha
    setBusy(true)
    try {
      const r = await api.createFromOptions({
        name, ruleset, class_id: classId,
        species_id: speciesId || null,
        background_id: backgroundId || null,
        abilities,
      })
      localStorage.removeItem(DRAFT_KEY)
      trackTask('wizard', true)
      nav(`/character/${r.id}`)
    } catch (e) { setErr(errText(e, t)); setBusy(false); trackTask('wizard', false) }
  }

  const sel = (list, value, set) => (
    <SearchableSelect list={list} value={value} onChange={set} />
  )

  return (
    <main>
      <h1>{t('wiz.title')}</h1>
      {err && <p className="error" role="alert">{err}</p>}

      <p className="muted" aria-label={t('wiz.progress')}>
        {[t('wiz.step0'), t('wiz.step1'), t('wiz.step2'), t('wiz.step3'),
          t('wiz.step4')]
          .map((s, i) => (
            <span key={s} style={{ fontWeight: i === step ? 700 : 400,
                                   color: i <= step ? 'var(--accent)'
                                                    : undefined }}>
              {i ? ' ─ ' : ''}{s}</span>))}
      </p>

      <div className="wizard-cols">
      <div>
      {step === 0 && (
        <section className="card">
          <h2>1. {t('wiz.name')} + {t('search.edition')}</h2>
          {/* etiqueta visible — el placeholder desaparece al escribir
              y no cuenta como label persistente (WCAG 3.3.2) */}
          <label htmlFor="wiz-name" className="muted"
                 style={{ display: 'block', marginBottom: '.3rem' }}>
            {t('wiz.name')}
          </label>
          <input id="wiz-name" value={name}
                 onChange={(e) => setName(e.target.value)}
                 placeholder={t('wiz.namePh')} />
          {[
            ['dnd5e-2024', 'wizard.rules.2024'],
            ['dnd5e-2014', 'wizard.rules.2014'],
            ['mixed', 'wizard.rules.mixed'],
          ].map(([v, k]) => (
            <button key={v} className="ghost" aria-pressed={ruleset === v}
              style={{ display: 'block', width: '100%', textAlign: 'left',
                       marginBottom: '.4rem', padding: '.7rem',
                       borderColor: ruleset === v
                         ? 'var(--accent)' : undefined }}
              onClick={() => setRuleset(v)}>
              <strong>{t(`${k}.name`)}</strong>{' '}
              <span className="muted">{t(`${k}.desc`)}</span>
              {v === 'dnd5e-2024' &&
                <span className="chip" style={{ float: 'right' }}>
                  {t('wiz.recommended')}</span>}
            </button>))}
          <button className="primary" disabled={!name.trim()}
                  onClick={() => setStep(1)}>{t('wiz.next')}</button>
          {/* el borrador se restaura solo — botón para empezar de
              cero sin tener que borrar campo a campo */}
          {(draft.name || draft.classId || draft.speciesId) && (
            <button className="ghost" onClick={() => {
              localStorage.removeItem(DRAFT_KEY)
              setStep(0); setName(''); setRuleset('dnd5e-2014')
              setClassId(''); setSpeciesId(''); setBackgroundId('')
              setAbilities({}); setRemaining([...STANDARD_ARRAY])
            }}>{t('wiz.startOver')}</button>)}
        </section>
      )}

      {step === 1 && (
        <section className="card">
          <h2>2. {t('wiz.class')}</h2>
          <div className="card-grid" role="radiogroup"
               aria-label={t('wiz.class')}>
            {classes.map((o) => (
              <button key={o.id} className="ghost pick-card"
                      role="radio" aria-checked={classId === o.id}
                      style={{ borderColor: classId === o.id
                        ? 'var(--accent)' : undefined }}
                      onClick={() => setClassId(o.id)}>
                <strong>{o.name}</strong>
                {o.source_id && !o.source_id.startsWith('srd-') &&
                  <span className="muted" style={{ fontSize: '.75rem' }}>
                    {o.source_id}</span>}
              </button>))}
          </div>
          <div className="row">
            <button onClick={() => setStep(0)}>{t('wiz.back')}</button>
            <button disabled={!classId} onClick={() => setStep(2)}>{t('wiz.next')}</button>
          </div>
        </section>
      )}

      {step === 2 && (
        <section className="card">
          <h2>3. {t('wiz.species')} + {t('wiz.background')}</h2>
          <h3 style={{ marginTop: 0 }}>{t('wiz.species')}</h3>
          {sel(species, speciesId, setSpeciesId)}
          <h3>{t('wiz.background')}</h3>
          {sel(backgrounds, backgroundId, setBackgroundId)}
          <GrantPreview speciesId={speciesId}
                        backgroundId={backgroundId} />
          <div className="row">
            <button onClick={() => setStep(1)}>{t('wiz.back')}</button>
            <button onClick={() => setStep(3)}>{t('wiz.next')}</button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <h2>4. {t('wiz.abilities')} <span className="muted">({t('wiz.stdArray')}: {remaining.join(', ') || '—'})</span></h2>
          {ABILITIES.map((ab) => {
            const others = Object.entries(abilities)
              .filter(([k]) => k !== ab).map(([, v]) => v)
            const score = abilities[ab]
            return (
              <div key={ab} className="row">
                <span style={{ width: 110 }}>{t(`stat.${ab}`)}</span>
                <select value={score || ''}
                        onChange={(e) => assign(ab, e.target.value)}>
                  <option value="">—</option>
                  {STANDARD_ARRAY.map((v) => (
                    <option key={v} value={v}
                            disabled={others.includes(v)}>{v}</option>))}
                </select>
                <span className="ability-bar" aria-hidden="true">
                  <span style={{ width: score
                    ? `${Math.round(score / 20 * 100)}%` : 0 }} />
                </span>
                <span className="muted">{score ? `mod ${Math.floor((score - 10) / 2) >= 0 ? '+' : ''}${Math.floor((score - 10) / 2)}` : ''}</span>
              </div>
            )})}
          <div className="row">
            <button className="ghost" onClick={() => {
              // mejor ajuste por prioridad de clase si la conocemos
              const key = Object.keys(CLASS_PRIORITY).find((k) =>
                classId.toLowerCase().includes(k))
              const order = key ? CLASS_PRIORITY[key] : ABILITIES
              setAbilities(Object.fromEntries(
                order.map((ab, i) => [ab, STANDARD_ARRAY[i]])))
              setRemaining([])
            }}>{t('wiz.recommendedAssign')}{classId &&
              ` (${classId.split(':').pop().split('|')[0]
                .replace(/-/g, ' ')})`}</button>
            <button className="ghost" onClick={() => {
              setAbilities({}); setRemaining([...STANDARD_ARRAY])
            }}>{t('wiz.reset')}</button>
          </div>
          <div className="row">
            <button onClick={() => setStep(2)}>{t('wiz.back')}</button>
            <button disabled={ABILITIES.some((a) => !abilities[a])}
                    onClick={() => setStep(4)}>{t('wiz.review')}</button>
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="card">
          <h2>5. {t('wiz.summary')}</h2>
          <p><strong>{name}</strong></p>
          <p className="muted">
            {[disp(classes, classId), disp(species, speciesId),
              disp(backgrounds, backgroundId)]
              .filter((x) => x !== '—').join(' · ')}
            {' · '}
            {t(`ruleset.${ruleset}`)}
          </p>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {ABILITIES.map((ab) => (
              <span key={ab} className="chip">{ab.toUpperCase()} {abilities[ab]}
                {' '}({Math.floor((abilities[ab] - 10) / 2) >= 0 ? '+' : ''}
                  {Math.floor((abilities[ab] - 10) / 2)})</span>))}
          </div>
          {[classId, speciesId, backgroundId].some((x) =>
              x && !/srd-|open5e|5e-bits/.test(x)) && (
            <p className="notice" role="note">
              ⚠ {t('wiz.homebrewWarn')}
            </p>)}
          {ruleset === 'mixed' && (
            <p className="notice" role="note">
              ⚠ {t('wiz.mixedWarn')}
            </p>)}
          <div className="row">
            <button onClick={() => setStep(3)}>{t('wiz.back')}</button>
            <button className="primary"
                    onClick={submit}>{t('wiz.finish')}</button>
          </div>
        </section>
      )}
      </div>

      <aside className="card wizard-summary"
             aria-label={t('wiz.summaryAria')}>
        <h3 style={{ marginTop: 0 }}>{t('wiz.summaryAside')}</h3>
        <p><strong>{name || t('wiz.unnamed')}</strong></p>
        <p className="muted">
          {t(`ruleset.${ruleset}`)}</p>
        <dl>
          <dt>{t('wiz.class')}</dt>
          <dd>{disp(classes, classId)}</dd>
          <dt>{t('wiz.species')}</dt>
          <dd>{disp(species, speciesId)}</dd>
          <dt>{t('wiz.background')}</dt>
          <dd>{disp(backgrounds, backgroundId)}</dd>
        </dl>
        {Object.values(abilities).some(Boolean) && (
          <p className="muted">
            {ABILITIES.map((ab) => `${ab.toUpperCase()} ${abilities[ab]}`)
              .join(' · ')}</p>)}
      </aside>
      </div>
    </main>
  )
}


/** Vista previa acumulada: qué conceden especie + trasfondo. */
function GrantPreview({ speciesId, backgroundId }) {
  const { t } = useT()
  const [info, setInfo] = useState([])
  useEffect(() => {
    setInfo([])
    for (const id of [speciesId, backgroundId].filter(Boolean)) {
      api.entityRender(id).then((r) => {
        const grants = []
        if (r.render?.fields)
          grants.push(...r.render.fields.map((f) =>
            `${f.label}: ${f.value}`))
        if (r.render?.desc)
          grants.push(r.render.desc.slice(0, 160))
        setInfo((prev) => [...prev, { id, name: r.name, grants }])
      }).catch(() => {})
    }
  }, [speciesId, backgroundId])
  if (!info.length) return null
  return (
    <div className="card" style={{ background: 'var(--card-raised)' }}>
      <h3 style={{ marginTop: 0 }}>{t('wiz.grantPreview')}</h3>
      {info.map((x) => (
        <p key={x.id} className="muted">
          <strong>{x.name}</strong>{' '}
          {x.grants.slice(0, 4).join(' · ')}</p>))}
    </div>
  )
}


/** Select buscable — el corpus importado puede tener miles de
    opciones por tipo (p.ej. ~130 especies/razas). */
function SearchableSelect({ list, value, onChange }) {
  const { t, tf } = useT()
  const [filter, setFilter] = useState('')
  const shown = filter.trim()
    ? list.filter((o) =>
        o.name.toLowerCase().includes(filter.trim().toLowerCase()))
        .slice(0, 60)
    : list.slice(0, 60)
  return (
    <div>
      <input value={filter} onChange={(e) => setFilter(e.target.value)}
             placeholder={tf('wiz.filterPh', { n: list.length })}
             aria-label={t('wiz.filterAria')} />
      <select value={value} onChange={(e) => onChange(e.target.value)}
              size={Math.min(8, shown.length + 1)}>
        <option value="">{t('wiz.choose')}</option>
        {shown.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
            {o.source_id && !o.source_id.startsWith('srd-')
              ? ` · ${o.source_id}` : ''}
          </option>))}
      </select>
    </div>
  )
}
