import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha']
const STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
const ABILITY_NAMES = {
  str: 'Fuerza', dex: 'Destreza', con: 'Constitución',
  int: 'Inteligencia', wis: 'Sabiduría', cha: 'Carisma',
}

export default function Wizard() {
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [ruleset, setRuleset] = useState('dnd5e-2014')
  const [classes, setClasses] = useState([])
  const [species, setSpecies] = useState([])
  const [backgrounds, setBackgrounds] = useState([])
  const [classId, setClassId] = useState('')
  const [speciesId, setSpeciesId] = useState('')
  const [backgroundId, setBackgroundId] = useState('')
  const [abilities, setAbilities] = useState({})
  const [remaining, setRemaining] = useState([...STANDARD_ARRAY])
  const [err, setErr] = useState(null)

  useEffect(() => {
    // all_sources: ofrece también homebrew/UA/terceros importados
    api.contentOptions('class', ruleset, true)
      .then((r) => setClasses(r.options)).catch((e) => setErr(e.message))
    // 2024 usa 'species'; 2014 usa 'race'; 'mixed' trae ambos
    Promise.all([
      api.contentOptions('race', ruleset, true),
      api.contentOptions('species', ruleset, true),
    ]).then(([a, b]) => {
      const seen = new Set()
      setSpecies([...a.options, ...b.options]
        .filter((o) => !seen.has(o.id) && seen.add(o.id)))
    }).catch(() => {})
    api.contentOptions('background', ruleset, true)
      .then((r) => setBackgrounds(r.options)).catch(() => {})
  }, [ruleset])

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
    try {
      const r = await api.createFromOptions({
        name, ruleset, class_id: classId,
        species_id: speciesId || null,
        background_id: backgroundId || null,
        abilities,
      })
      nav(`/character/${r.id}`)
    } catch (e) { setErr(e.message) }
  }

  const sel = (list, value, set) => (
    <SearchableSelect list={list} value={value} onChange={set} />
  )

  return (
    <main>
      <h1>Nuevo personaje</h1>
      {err && <p className="error">{err}</p>}

      <p className="muted" aria-label="Progreso">
        {['Concepto', 'Clase', 'Origen', 'Características', 'Revisión']
          .map((s, i) => (
            <span key={s} style={{ fontWeight: i === step ? 700 : 400,
                                   color: i <= step ? 'var(--accent)'
                                                    : undefined }}>
              {i ? ' ─ ' : ''}{s}</span>))}
      </p>

      {step === 0 && (
        <section className="card">
          <h2>1. Nombre y reglas</h2>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="Nombre" />
          {[
            ['dnd5e-2024', 'Reglas 2024',
             'Edición revisada (SRD 5.2). Recomendada.'],
            ['dnd5e-2014', 'Reglas 2014',
             'Edición original de 5e (SRD 5.1).'],
            ['mixed', 'Modo mixto',
             'Combina 2014 y 2024 — puede mezclar reglas incompatibles.'],
          ].map(([v, t, d]) => (
            <button key={v} className="ghost" aria-pressed={ruleset === v}
              style={{ display: 'block', width: '100%', textAlign: 'left',
                       marginBottom: '.4rem', padding: '.7rem',
                       borderColor: ruleset === v
                         ? 'var(--accent)' : undefined }}
              onClick={() => setRuleset(v)}>
              <strong>{t}</strong>{' '}
              <span className="muted">{d}</span>
              {v === 'dnd5e-2024' &&
                <span className="chip" style={{ float: 'right' }}>
                  recomendado</span>}
            </button>))}
          <button className="primary" disabled={!name.trim()}
                  onClick={() => setStep(1)}>Siguiente</button>
        </section>
      )}

      {step === 1 && (
        <section className="card">
          <h2>2. Clase</h2>
          {sel(classes, classId, setClassId)}
          <div className="row">
            <button onClick={() => setStep(0)}>Atrás</button>
            <button disabled={!classId} onClick={() => setStep(2)}>Siguiente</button>
          </div>
        </section>
      )}

      {step === 2 && (
        <section className="card">
          <h2>3. Especie y trasfondo</h2>
          <h3 style={{ marginTop: 0 }}>Especie</h3>
          {sel(species, speciesId, setSpeciesId)}
          <h3>Trasfondo</h3>
          {sel(backgrounds, backgroundId, setBackgroundId)}
          <GrantPreview speciesId={speciesId}
                        backgroundId={backgroundId} />
          <div className="row">
            <button onClick={() => setStep(1)}>Atrás</button>
            <button onClick={() => setStep(3)}>Siguiente</button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <h2>4. Características <span className="muted">(array estándar: {remaining.join(', ') || '—'})</span></h2>
          {ABILITIES.map((ab) => {
            const others = Object.entries(abilities)
              .filter(([k]) => k !== ab).map(([, v]) => v)
            return (
              <div key={ab} className="row">
                <span style={{ width: 110 }}>{ABILITY_NAMES[ab]}</span>
                <select value={abilities[ab] || ''}
                        onChange={(e) => assign(ab, e.target.value)}>
                  <option value="">—</option>
                  {STANDARD_ARRAY.map((v) => (
                    <option key={v} value={v}
                            disabled={others.includes(v)}>{v}</option>))}
                </select>
                <span className="muted">{abilities[ab] ? `mod ${Math.floor((abilities[ab] - 10) / 2) >= 0 ? '+' : ''}${Math.floor((abilities[ab] - 10) / 2)}` : ''}</span>
              </div>
            )})}
          <div className="row">
            <button className="ghost" onClick={() => {
              setAbilities({}); setRemaining([...STANDARD_ARRAY])
            }}>Restablecer</button>
          </div>
          <div className="row">
            <button onClick={() => setStep(2)}>Atrás</button>
            <button disabled={ABILITIES.some((a) => !abilities[a])}
                    onClick={() => setStep(4)}>Revisar</button>
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="card">
          <h2>5. Revisión</h2>
          <p><strong>{name}</strong></p>
          <p className="muted">
            {[classId, speciesId, backgroundId]
              .filter(Boolean).map((x) =>
                x.split(':').pop().split('|')[0].replace(/-/g, ' '))
              .join(' · ')}
            {' · '}
            {{ 'dnd5e-2014': 'Reglas 2014', 'dnd5e-2024': 'Reglas 2024',
               mixed: 'Modo mixto' }[ruleset]}
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
              ⚠ Usarás contenido privado/homebrew — procedencia no oficial.
            </p>)}
          {ruleset === 'mixed' && (
            <p className="notice" role="note">
              ⚠ Modo mixto: puede combinar reglas 2014 y 2024
              incompatibles entre sí.
            </p>)}
          <div className="row">
            <button onClick={() => setStep(3)}>Atrás</button>
            <button className="primary"
                    onClick={submit}>Crear personaje</button>
          </div>
        </section>
      )}
    </main>
  )
}


/** Vista previa acumulada: qué conceden especie + trasfondo. */
function GrantPreview({ speciesId, backgroundId }) {
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
      <h3 style={{ marginTop: 0 }}>Tu personaje recibirá</h3>
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
  const [filter, setFilter] = useState('')
  const shown = filter.trim()
    ? list.filter((o) =>
        o.name.toLowerCase().includes(filter.trim().toLowerCase()))
        .slice(0, 60)
    : list.slice(0, 60)
  return (
    <div>
      <input value={filter} onChange={(e) => setFilter(e.target.value)}
             placeholder={`Buscar… (${list.length} opciones)`}
             aria-label="Filtrar opciones" />
      <select value={value} onChange={(e) => onChange(e.target.value)}
              size={Math.min(8, shown.length + 1)}>
        <option value="">— elegir —</option>
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
