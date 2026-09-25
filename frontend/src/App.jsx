import { NavLink, Routes, Route, useNavigate }
  from 'react-router-dom'
import { useState } from 'react'
import Header from './components/Header.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import CharacterList from './pages/CharacterList.jsx'
import CharacterSheet from './pages/CharacterSheet.jsx'
import Wizard from './pages/Wizard.jsx'
import DmBoard from './pages/DmBoard.jsx'
import CampaignBoard from './pages/CampaignBoard.jsx'
import CampaignList from './pages/CampaignList.jsx'
import Search from './pages/Search.jsx'
import Entity from './pages/Entity.jsx'

/** Barra inferior fija en móvil (≤700px): los cinco destinos
    principales a un toque, con "+" que abre el menú de creación. */
function MobileNav() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const go = (to) => { setOpen(false); nav(to) }
  return (
    <nav className="mobile-nav" aria-label="Navegación móvil">
      <NavLink to="/" end>Fichas</NavLink>
      <NavLink to="/campaigns">Campañas</NavLink>
      <button className="fab" aria-label="Crear" aria-expanded={open}
              onClick={() => setOpen(!open)}>+</button>
      <NavLink to="/search">Compendio</NavLink>
      <NavLink to="/dm">DM</NavLink>
      {open && (
        <div className="fab-menu" role="menu">
          {[
            ['Personaje', '/new'],
            ['Importar personaje', '/?import=1'],
            ['Campaña / mesa', '/dm'],
            ['Contenido (compendio)', '/search'],
          ].map(([label, to]) => (
            <button key={label} role="menuitem"
                    onClick={() => go(to)}>{label}</button>))}
        </div>)}
    </nav>
  )
}

export default function App() {
  return (
    <div className="app">
      <Header />
      <CommandPalette />
      <Routes>
        <Route path="/" element={<CharacterList />} />
        <Route path="/new" element={<Wizard />} />
        <Route path="/character/:id" element={<CharacterSheet />} />
        <Route path="/character/:id/:tab" element={<CharacterSheet />} />
        <Route path="/search" element={<Search />} />
        <Route path="/content/:id" element={<Entity />} />
        <Route path="/dm" element={<DmBoard />} />
        <Route path="/campaigns" element={<CampaignList />} />
        <Route path="/campaign/:id" element={<CampaignBoard />} />
      </Routes>
      <MobileNav />
    </div>
  )
}
