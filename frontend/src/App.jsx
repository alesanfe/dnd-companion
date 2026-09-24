import { Routes, Route } from 'react-router-dom'
import Header from './components/Header.jsx'
import CharacterList from './pages/CharacterList.jsx'
import CharacterSheet from './pages/CharacterSheet.jsx'
import Wizard from './pages/Wizard.jsx'
import DmBoard from './pages/DmBoard.jsx'
import CampaignBoard from './pages/CampaignBoard.jsx'
import Search from './pages/Search.jsx'
import Entity from './pages/Entity.jsx'

export default function App() {
  return (
    <div className="app">
      <Header />
      <Routes>
        <Route path="/" element={<CharacterList />} />
        <Route path="/new" element={<Wizard />} />
        <Route path="/character/:id" element={<CharacterSheet />} />
        <Route path="/search" element={<Search />} />
        <Route path="/content/:id" element={<Entity />} />
        <Route path="/dm" element={<DmBoard />} />
        <Route path="/campaign/:id" element={<CampaignBoard />} />
      </Routes>
    </div>
  )
}
