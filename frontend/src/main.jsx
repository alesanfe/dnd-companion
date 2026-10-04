import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { LangProvider } from './i18n.jsx'
import { DialogProvider } from './components/ui/Dialogs.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <LangProvider>
        <DialogProvider>
          <App />
        </DialogProvider>
      </LangProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
