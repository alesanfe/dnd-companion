import { IdentityEditor } from './sheetParts.jsx'

// tinte determinista por nombre/clase — retrato de iniciales sin
// imagen subida
export const avatarHue = (name = '') => {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

// cabecera de la ficha: avatar + quién-es (clases, especie, trasfondo)
// + editor de identidad — extraído de pages/CharacterSheet.jsx (AU-22)
export default function SheetIdentity({
  char, d, portrait, classLine, speciesName, bgName, totalLevel,
  fileRef, onPortrait, setPortrait, t, op,
}) {
  return (
    <div className="identity">
      <button className="avatar" aria-label={t('sheet.portraitAria')}
              title={t('sheet.portraitHint')}
              onClick={() => fileRef.current?.click()}
              onContextMenu={(e) => {
                e.preventDefault()
                localStorage.removeItem(`dnd-portrait-${char.id}`)
                setPortrait(null)
                op('character.narrative.set',
                   { field: 'portrait_url', value: null })
              }}
              style={portrait
                ? { backgroundImage: `url(${portrait})` }
                : { background:
                    `hsl(${avatarHue(
                      d.classes?.[0]?.class_id || char.name)
                    } 45% 42%)` }}>
        {!portrait && (char.name || '?')[0].toUpperCase()}
      </button>
      <input ref={fileRef} type="file" accept="image/*" hidden
             onChange={onPortrait} />
      <div className="identity-txt">
        <h1>{char.name}
          <span className="muted" style={{ fontSize: '0.9rem' }}>
            {' '}{t('sheet.level')} {totalLevel}
          </span>
        </h1>
        {(classLine || speciesName || bgName) && (
          <p className="identity-sub">
            {classLine && <span className="cls">{classLine}</span>}
            {[speciesName, bgName, d.alignment,
              d.player_name && `${t('sheet.playerTag')}: ${d.player_name}`]
              .filter(Boolean)
              .map((s, i) => <span key={i}>
                {classLine || i > 0 ? ' · ' : ''}{s}</span>)}
          </p>)}
        {/* editor de identidad — campos de cabecera de la hoja */}
        <IdentityEditor d={d} name={char.name} op={op} />
      </div>
    </div>
  )
}
