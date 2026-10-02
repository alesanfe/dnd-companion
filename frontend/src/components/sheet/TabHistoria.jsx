import { Section } from './panels.jsx'

/** Campos narrativos de la hoja oficial (página 2): se guardan al
    perder el foco vía character.narrative.set — reversible.
    Las etiquetas salen del i18n con clave nar.<campo>. */
const NARRATIVE_FIELDS = [
  'personality', 'ideals', 'bonds', 'flaws', 'appearance', 'backstory',
  'allies', 'goals', 'secrets',
]

/** Pestaña Historia: trasfondo narrativo completo + diario. */
export default function TabHistoria({ c }) {
  const { d, op, t, focus, hud, tab, journalEntry, setJournalEntry } = c
  const show = (g) => focus ? hud.has(g) : tab === g
  const nar = d.narrative || {}
  return (<div className="sheet-cols">
    <Section title={t('nar.personalitySec')} hidden={!show('historia')}
             extraClass="optional">
      {NARRATIVE_FIELDS.slice(0, 4).map((field) => (
        <NarrativeField key={field} field={field}
                        label={t(`nar.${field}`)}
                        value={nar[field]} op={op} rows={2} />))}
    </Section>

    <Section title={t('nar.appearanceSec')} hidden={!show('historia')}
             extraClass="optional">
      {/* ficha física de la página 2: edad, altura, peso, ojos, piel, pelo */}
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {['age', 'height', 'weight', 'eyes', 'skin', 'hair'].map(
          (field) => {
            const label = t(`nar.${field}`)
            return (
            <label key={field} className="muted"
                   style={{ fontSize: '.8rem' }}>{label}
              <input defaultValue={nar[field] || ''}
                     aria-label={label} style={{ maxWidth: 110 }}
                     onBlur={(e) => e.target.value !== (nar[field] || '') &&
                       op('character.narrative.set',
                          { field, value: e.target.value })} />
            </label>)})}
      </div>
      <NarrativeField field="appearance"
                      label={t('nar.appearanceFree')}
                      value={nar.appearance} op={op} rows={2} />
    </Section>

    <Section title={t('nar.historySec')} hidden={!show('historia')}
             extraClass="optional">
      {['backstory', 'allies', 'goals', 'secrets'].map((field) => (
        <div key={field}>
          <NarrativeField field={field} label={t(`nar.${field}`)}
                          value={nar[field]} op={op}
                          rows={field === 'backstory' ? 4 : 2} />
          {field === 'allies' && <OrgSymbol nar={nar} op={op} t={t} />}
        </div>))}
    </Section>

    <Section title={t('sheet.journal')}  hidden={!show('historia')} extraClass="optional">
      <div className="row">
        <input value={journalEntry} placeholder={t('nar.journalPh')}
               aria-label={t('nar.journalPh')}
               onChange={(e) => setJournalEntry(e.target.value)} />
        <button disabled={!journalEntry.trim()} onClick={() => {
          op('character.journal.add', { entry: journalEntry.trim() })
          setJournalEntry('')
        }}>{t('sheet.write')}</button>
      </div>
      <ul>{(nar.journal || []).map((j, i) => (
        <li key={i}>{j}
          {/* solo la última entrada es borrable — la pila de
              operaciones es FIFO (journal.pop) */}
          {i === nar.journal.length - 1 && (
            <button className="ghost" aria-label={t('nar.journalDel')}
                    style={{ minHeight: 26, padding: '0 .5rem' }}
                    onClick={() => op('character.journal.pop', {})}>
              ×</button>)}
        </li>))}</ul>
    </Section>
  </div>)
}

/** Emblema de aliados/organización (página 2 de la hoja) — data-URL
    reducida a 128px, persistida en narrative.org_symbol. */
function OrgSymbol({ nar, op, t }) {
  const upload = (f) => {
    if (!f) return
    const img = new Image()
    img.onload = () => {
      const s = Math.min(1, 128 / Math.max(img.width, img.height))
      const cnv = document.createElement('canvas')
      cnv.width = Math.round(img.width * s)
      cnv.height = Math.round(img.height * s)
      cnv.getContext('2d').drawImage(img, 0, 0, cnv.width, cnv.height)
      op('character.narrative.set',
         { field: 'org_symbol', value: cnv.toDataURL('image/jpeg', 0.85) })
      URL.revokeObjectURL(img.src)
    }
    img.src = URL.createObjectURL(f)
  }
  return (
    <div className="row" style={{ marginBottom: '.5rem' }}>
      {nar.org_symbol && (
        <img src={nar.org_symbol} alt={t('nar.orgAlt')}
             style={{ height: 44, borderRadius: 6 }} />)}
      <label className="ghost" role="button" tabIndex={0}
             style={{ cursor: 'pointer' }}>
        {nar.org_symbol ? t('nar.orgChange') : t('nar.orgUpload')}
        <input type="file" accept="image/*" hidden
               onChange={(e) => upload(e.target.files?.[0])} />
      </label>
      {nar.org_symbol && (
        <button className="ghost" aria-label={t('nar.orgRemove')}
                onClick={() => op('character.narrative.set',
                                  { field: 'org_symbol', value: null })}>
          ×</button>)}
    </div>
  )
}

/** Textarea con guardado al perder el foco — solo lanza la operación
    si el valor cambió (las operaciones son reversibles, no gratis). */
function NarrativeField({ field, label, value, op, rows = 2 }) {
  return (
    <label style={{ display: 'block', marginBottom: '.5rem' }}>
      <span className="muted" style={{ fontSize: '.8rem' }}>{label}</span>
      <textarea rows={rows} defaultValue={value || ''}
                aria-label={label}
                onBlur={(e) => e.target.value !== (value || '') &&
                  op('character.narrative.set',
                     { field, value: e.target.value })} />
    </label>
  )
}
