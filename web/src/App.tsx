import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ComparePage } from './pages/ComparePage'
import { GamePage } from './pages/GamePage'
import { LeadersPage } from './pages/LeadersPage'
import { PlayerPage } from './pages/PlayerPage'
import { SearchPage } from './pages/SearchPage'
import { StandingsPage } from './pages/StandingsPage'
import { TeamPage } from './pages/TeamPage'
import { TeamsPage } from './pages/TeamsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Los datos son históricos y solo cambian cuando corre la ingesta, así
      // que no tiene sentido revalidarlos al volver a la pestaña.
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<SearchPage />} />
            <Route path="/jugador/:id" element={<PlayerPage />} />
            <Route path="/equipos" element={<TeamsPage />} />
            <Route path="/equipo/:id" element={<TeamPage />} />
            <Route path="/clasificacion" element={<StandingsPage />} />
            <Route path="/partido/:id" element={<GamePage />} />
            <Route path="/comparar" element={<ComparePage />} />
            <Route path="/tendencias" element={<LeadersPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
