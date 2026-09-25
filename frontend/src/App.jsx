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
import { useT } from './i18n.jsx'

/** Barra inferior fija en móvil (≤700px): los cinco destinos
    principales a un toque, con "+" que abre el menú de creación. */
function MobileNav() {
  const nav = useNavigate()
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const go = (to) => { setOpen(false); nav(to) }
  return (
    <nav className="mobile-nav" aria-label={t('nav.create')}>
      <NavLink to="/" end>{t('nav.sheets')}</NavLink>
      <NavLink to="/campaigns">{t('nav.campaigns')}</NavLink>
      <button className="fab" aria-label={t('nav.create')} aria-expanded={open}
              onClick={() => setOpen(!open)}>+</button>
      <NavLink to="/search">{t('nav.compendium')}</NavLink>
      <NavLink to="/dm">{t('nav.dm')}</NavLink>
      {open && (
        <div className="fab-menu" role="menu">
          {[
            [t('create.character'), '/new'],
            [t('create.import'), '/?import=1'],
            [t('create.campaign'), '/dm'],
            [t('create.content'), '/search'],
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
