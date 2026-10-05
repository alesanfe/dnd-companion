import { NavLink, Routes, Route, Link, useNavigate, useLocation }
  from 'react-router-dom'
import { lazy, Suspense, useState, useEffect } from 'react'
import Header from './components/Header.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import Dashboard from './pages/Dashboard.jsx'
import CharacterList from './pages/CharacterList.jsx'
import { useT } from './i18n.jsx'
import { trackPage } from './lib/metrics.js'

// code-splitting: la ficha y las pantallas de DM son la mitad del
// bundle — se cargan bajo demanda al navegar
const CharacterSheet = lazy(() => import('./pages/CharacterSheet.jsx'))
const Wizard = lazy(() => import('./pages/Wizard.jsx'))
const DmBoard = lazy(() => import('./pages/DmBoard.jsx'))
const CampaignBoard = lazy(() => import('./pages/CampaignBoard.jsx'))
const CampaignList = lazy(() => import('./pages/CampaignList.jsx'))
const Search = lazy(() => import('./pages/Search.jsx'))
const Entity = lazy(() => import('./pages/Entity.jsx'))
const Settings = lazy(() => import('./pages/Settings.jsx'))

/** Barra inferior fija en móvil (≤700px): los cinco destinos
    principales a un toque, con "+" que abre el menú de creación. */
function MobileNav() {
  const nav = useNavigate()
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const go = (to) => { setOpen(false); nav(to) }
  // Esc cierra el menú del "+" — como cualquier popover; tocar
  // fuera también (antes quedaba abierto tapando el contenido)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    const onTap = (e) => {
      if (!e.target.closest('.mobile-nav')) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onTap)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', onTap)
    }
  }, [open])
  return (
    <nav className="mobile-nav" aria-label={t('nav.create')}>
      <NavLink to="/" end>{t('nav.home')}</NavLink>
      <NavLink to="/characters">{t('nav.sheets')}</NavLink>
      {/* Campañas también abajo: la nav superior las oculta en móvil
          y sin este enlace el destino quedaba inalcanzable */}
      <NavLink to="/campaigns">{t('nav.campaigns')}</NavLink>
      <button className="fab" aria-label={t('nav.create')} aria-expanded={open}
              onClick={() => setOpen(!open)}>+</button>
      <NavLink to="/search">{t('nav.compendium')}</NavLink>
      <NavLink to="/dm">{t('nav.dm')}</NavLink>
      {open && (
        <div className="fab-menu" role="menu">
          {[
            [t('create.character'), '/new'],
            [t('create.import'), '/characters?import=1'],
            [t('create.campaign'), '/dm'],
            [t('create.content'), '/search'],
          ].map(([label, to]) => (
            <button key={label} role="menuitem"
                    onClick={() => go(to)}>{label}</button>))}
        </div>)}
    </nav>
  )
}

function NotFound() {
  const { t } = useT()
  return (
    <main>
      <h1>{t('nf.title')}</h1>
      <p className="muted">{t('nf.hint')}</p>
      <p><Link to="/">{t('nf.home')}</Link></p>
    </main>)
}

export default function App() {
  const { t } = useT()
  const loc = useLocation()
  // métrica local de uso: qué secciones se visitan (nada sale del
  // dispositivo — se consulta y borra desde Settings)
  useEffect(() => {
    trackPage('/' + (loc.pathname.split('/')[1] || ''))
  }, [loc.pathname])
  // título del documento por sección (WCAG 2.4.2): pestañas del
  // navegador e historial identifican dónde está el usuario
  useEffect(() => {
    const seg = loc.pathname.split('/')
    const map = {
      '': 'nav.home',
      characters: 'charlist.title',
      new: 'wiz.title',
      character: 'nav.sheets',
      search: 'search.title',
      content: 'nav.compendium',
      dm: 'nav.dm',
      campaigns: 'camp.title',
      campaign: 'camp.title',
      settings: 'set.title',
    }
    const key = map[seg[1] || ''] ||
      (seg[1] ? 'nf.title' : 'nav.home')
    document.title = `${t(key)} · D&D Companion`
  }, [loc.pathname, t])
  return (
    <div className="app">
      <a href="#content" className="skip-link">{t('app.skip')}</a>
      <Header />
      <CommandPalette />
      <div id="content" tabIndex={-1}>
      <Suspense fallback={
        <main><p className="muted" role="status" aria-live="polite">
          {t('common.loading')}</p></main>}>
      <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/characters" element={<CharacterList />} />
        <Route path="/new" element={<Wizard />} />
        <Route path="/character/:id" element={<CharacterSheet />} />
        <Route path="/character/:id/:tab" element={<CharacterSheet />} />
        <Route path="/search" element={<Search />} />
        <Route path="/content/:id" element={<Entity />} />
        <Route path="/dm" element={<DmBoard />} />
        <Route path="/campaigns" element={<CampaignList />} />
        <Route path="/campaign/:id" element={<CampaignBoard />} />
        <Route path="/settings" element={<Settings />} />
        {/* comodín: una URL mala no debe dejar la zona de contenido
            en blanco — estado 404 con salida clara */}
        <Route path="*" element={<NotFound />} />
      </Routes>
      </ErrorBoundary>
      </Suspense>
      </div>
      <MobileNav />
    </div>
  )
}
