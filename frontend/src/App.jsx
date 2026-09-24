import { Routes, Route, Link } from 'react-router-dom'
import CharacterList from './pages/CharacterList.jsx'
import CharacterSheet from './pages/CharacterSheet.jsx'
import Search from './pages/Search.jsx'

export default function App() {
  return (
    <div className="app">
      <nav className="nav">
        <Link to="/">Fichas</Link>
        <Link to="/search">Buscar</Link>
        <Link to="/dm">Mesa DM</Link>
      </nav>
      <Routes>
        <Route path="/" element={<CharacterList />} />
        <Route path="/character/:id" element={<CharacterSheet />} />
        <Route path="/search" element={<Search />} />
        <Route path="/dm" element={<main><h1>Mesa del DM</h1><p>Próximamente.</p></main>} />
      </Routes>
    </div>
  )
}
