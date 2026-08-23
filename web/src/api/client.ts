import type {
  Catalog, HeadToHead, LeadersResponse, Player, PlayerRanks,
  PlayerSearchResult, PlayerSeason, RecentGame, SplitsResponse,
  Standing, Team, TeamGame, TeamSummary, Trend,
} from './types'

const BASE = '/api'

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== '' && v !== undefined && v !== null) url.searchParams.set(k, String(v))
  }
  const res = await fetch(url)
  if (!res.ok) {
    const detalle = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${detalle ? ` — ${detalle}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  catalog: () => get<Catalog>('/catalog'),
  searchPlayers: (search: string, limit = 25) =>
    get<PlayerSearchResult[]>('/players', { search, limit }),
  player: (id: number) => get<Player>(`/players/${id}`),
  seasons: (id: number) => get<PlayerSeason[]>(`/players/${id}/seasons`),
  trend: (id: number, stat: string, window = 25) =>
    get<Trend>(`/players/${id}/trend`, { stat, window }),
  splits: (id: number, dimension: string, stat: string) =>
    get<SplitsResponse>(`/players/${id}/splits`, { dimension, stat }),
  leaders: (direction: string, stat: string, minGames = 150, limit = 25) =>
    get<LeadersResponse>('/leaders/trending', {
      direction, stat, min_games: minGames, limit,
    }),

  // --- Ficha de jugador ---
  recent: (id: number, limit = 5) =>
    get<RecentGame[]>(`/players/${id}/recent`, { limit }),
  ranks: (id: number, season: string) =>
    get<PlayerRanks | null>(`/players/${id}/ranks`, { season }),

  // --- Equipos ---
  teams: (season?: string) => get<TeamSummary[]>('/teams', season ? { season } : {}),
  team: (id: number, season?: string) =>
    get<Team>(`/teams/${id}`, season ? { season } : {}),
  teamGames: (id: number, seasons?: string[], limit?: number) =>
    get<TeamGame[]>(`/teams/${id}/games`, {
      ...(seasons?.length ? { seasons: seasons.join(',') } : {}),
      ...(limit ? { limit } : {}),
    }),
  standings: (season?: string) =>
    get<Standing[]>('/standings', season ? { season } : {}),
  headToHead: (a: number, b: number) => get<HeadToHead>(`/teams/${a}/vs/${b}`),
  teamTrend: (id: number, stat: string) =>
    get<Record<string, unknown>>(`/teams/${id}/trend`, { stat }),
  teamSplits: (id: number, dimension: string, stat: string) =>
    get<Record<string, unknown>>(`/teams/${id}/splits`, { dimension, stat }),
  teamCatalog: () => get<{ stats: { value: string; label: string }[] }>('/team-catalog'),
}
