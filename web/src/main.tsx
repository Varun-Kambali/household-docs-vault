import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './app/App.tsx'
import './styles/tokens.css'
import './styles/base.css'
import './styles/app.css'
import './styles/search.css'
import './styles/list.css'

const root = document.getElementById('root')
if (root === null) throw new Error('index.html has no #root')
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
