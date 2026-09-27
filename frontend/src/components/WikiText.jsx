import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'

/** Texto con wiki-links estilo Kanka/LegendKeeper: [[Nombre]]
    enlaza a una entidad de la campaña (ancla #ent-<id>, resaltada
    con :target) o, si no hay ninguna con ese nombre, al primer
    resultado del compendio — así las notas del mundo se enlazan
    también a monstruos, conjuros u objetos. */
export default function WikiText({ text, entities = [] }) {
  const navigate = useNavigate()
  const goContent = async (name) => {
    try {
      const r = await api.search(name)
      if (r.results?.[0])
        return navigate(
          `/content/${encodeURIComponent(r.results[0].id)}`)
    } catch { /* offline → búsqueda local */ }
    navigate('/search')
  }
  return (
    <>
      {String(text || '').split(/(\[\[[^\]]+\]\])/g)
        .map((p, i) => {
          const m = p.match(/^\[\[([^\]]+)\]\]$/)
          if (!m) return <span key={i}>{p}</span>
          const q = m[1].trim()
          const ent = entities.find((e) =>
            (e.name || '').toLowerCase() === q.toLowerCase())
          if (ent)
            return <a key={i} href={`#ent-${ent.id}`}
                      className="wikilink">{ent.name}</a>
          return (
            <button key={i} type="button"
                    className="wikilink linklike"
                    onClick={() => goContent(q)}>{q}</button>)
        })}
    </>
  )
}
