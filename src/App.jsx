import { lazy, Suspense } from 'react'
import Dashboard from './components/Dashboard'
import { esTablero } from './lib/tablero'

// El tablero de la tele (#tele): otra pantalla, sin login, que no carga el dashboard.
const TableroTele = lazy(() => import('./components/jarvis/TableroTele'))

function App() {
  if (esTablero(window.location.hash)) {
    return <Suspense fallback={null}><TableroTele /></Suspense>
  }
  return <Dashboard />
}

export default App
