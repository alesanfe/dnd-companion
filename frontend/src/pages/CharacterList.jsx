import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'

export default function CharacterList() {
  const [chars, setChars] = useState([])
  const [name, setName] = useState('')
  const [err, setErr] = useState(null)
  const [menu, setMenu] = useState(null)   // id del char con ⋮ abierto
  const [filter, setFilter] = useState('')

  const load = () => api.listCharacters()
    .then((r) => setChars(r.characters))
    .catch((e) => setErr(e.message))

  useEffect(() => { load() }, [])

  const create = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    await api.createCharacter(name.trim())
    setName('')
    load()
  }

  const act = async (c, action) => {
    setMenu(null)
    if (action === 'export') {
      const ex = await api.exportCharacter(c.id)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob(
        [JSON.stringify(ex, null, 2)], { type: 'application/json' }))
      a.download = `${c.name}.json`; a.click()
    } else if (action === 'duplicate') {
      const ex = await api.exportCharacter(c.id)
      const data = ex.character?.data || ex.data || ex
      await api.importCharacter(
        { ...ex, name: `${c.name} (copia)`, data })
      load()
    } else if (action === 'delete') {
      if (!confirm(`¿Borrar a ${c.name}? Esta acción no se puede deshacer.`))
        return
      await fetch(`/api/characters/${c.id}`, { method: 'DELETE' })
      load()
    }
  }

  const shown = filter.trim()
    ? chars.filter((c) =>
        c.name.toLowerCase().includes(filter.trim().toLowerCase()))
    : chars

  return (
    <main>
      <h1>Mis personajes</h1>
      {err && <p className="error">Backend no disponible: {err}</p>}
      <form onSubmit={create} className="row">
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Nombre rápido (vacío)" />
        <button type="submit">Crear</button>
        <Link to="/new"><button type="button">Wizard →</button></Link>
        <label className="ghost" style={{ cursor: 'pointer',
             display: 'inline-flex', alignItems: 'center',
             minHeight: 44, padding: '0 1rem', borderRadius: 6,
             border: '1px solid var(--border)' }}>
          Importar
          <input type="file" accept=".json" hidden
                 aria-label="Importar personaje desde JSON"
                 onChange={async (e) => {
                   const f = e.target.files[0]
                   if (!f) return
                   try {
                     const data = JSON.parse(await f.text())
                     await api.importCharacter(data)
                     load()
                   } catch (ex) { setErr(`Importación: ${ex.message}`) }
                 }} />
        </label>
      </form>

      {chars.length === 0 && !err && (
        <div className="card empty">
          <p><strong>Todavía no tienes personajes</strong></p>
          <p>Crea una ficha guiada con el wizard — usa datos reales
             de todas las fuentes instaladas.</p>
          <Link to="/new">
            <button className="primary">Crear personaje</button></Link>
        </div>)}

      {chars.length > 4 && (
        <input value={filter} onChange={(e) => setFilter(e.target.value)}
               placeholder={`Buscar entre ${chars.length} personajes…`}
               aria-label="Buscar personaje" />)}

      <div className="char-grid">
        {shown.map((c) => {
          const pct = c.hp_max
            ? Math.round(100 * (c.hp_current ?? c.hp_max) / c.hp_max) : 100
          return (
            <div key={c.id} className="card char-card">
              <div className="row" style={{ marginTop: 0 }}>
                <Link to={`/character/${c.id}`}
                      style={{ flex: 1, fontSize: '1.1rem',
                               fontWeight: 700, textDecoration: 'none',
                               color: 'inherit' }}>
                  {c.name}</Link>
                <button className="ghost"
                        aria-label={`Opciones de ${c.name}`}
                        onClick={() => setMenu(menu === c.id ? null : c.id)}>
                  ⋮</button>
              </div>
              <p className="muted" style={{ margin: '0 0 .4rem' }}>
                {(c.class_names || []).join(' / ') || 'Sin clase'}
                {' · '}Nivel {c.level || 1} · {c.ruleset.replace('dnd5e-', 'reglas ')}
              </p>
              {c.hp_max != null && (
                <>
                  <div className="hp-bar" role="img"
                       aria-label={`PG ${c.hp_current} de ${c.hp_max}`}>
                    <div style={{ width: `${pct}%` }} />
                  </div>
                  <p className="muted" style={{ margin: '.2rem 0 0' }}>
                    {c.hp_current}/{c.hp_max} PG</p>
                </>)}
              {menu === c.id && (
                <div className="row" role="menu">
                  <Link to={`/character/${c.id}`}>
                    <button className="ghost">Abrir</button></Link>
                  <button className="ghost"
                          onClick={() => act(c, 'duplicate')}>Duplicar</button>
                  <button className="ghost"
                          onClick={() => act(c, 'export')}>Exportar</button>
                  <button className="ghost"
                          onClick={() => act(c, 'delete')}>Eliminar</button>
                </div>)}
            </div>)})}
      </div>
    </main>
  )
}
