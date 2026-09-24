import { Routes, Route, Link } from 'react-router-dom'

export default function App() {
  return (
    <div className="app">
      <nav className="nav">
        <Link to="/">Fichas</Link>
        <Link to="/search">Buscar</Link>
        <Link to="/dm">Mesa DM</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/dm" element={<DmBoard />} />
      </Routes>
    </div>
  )
}

function Home() {
  return <main><h1>Mis personajes</h1><p>Hojas de personaje — próximamente.</p></main>
}

function Search() {
  return <main><h1>Buscador de reglas</h1><p>FTS5 + comandos (/spell, /monster, /rule) — próximamente.</p></main>
}

function DmBoard() {
  return <main><h1>Mesa del DM</h1><p>Tracker de combate, campañas, escenas — próximamente.</p></main>
}
