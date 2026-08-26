import type {
  AgeCurve,
  GameExpected,
  StabilityTable,
  Backtest, Catalog, GameDetail, HeadToHead, LeadersResponse, Player, PlayerFilters,
  PlayerListResponse, PlayerRanks, PlayerSeason, RecentGame, SplitsResponse,
  Prediction, RatingsResponse, Standing, Team, TeamGame, TeamSplits, TeamSummary,
  TeamTrend, Trend,
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
  players: (f: PlayerFilters = {}) =>
    get<PlayerListResponse>('/players', {
      ...(f.search ? { search: f.search } : {}),
      ...(f.status ? { status: f.status } : {}),
      ...(f.team_id ? { team_id: f.team_id } : {}),
      ...(f.position ? { position: f.position } : {}),
      ...(f.season ? { season: f.season } : {}),
      ...(f.min_games ? { min_games: f.min_games } : {}),
      // 0 significa «no filtres», no «sin valor»: omitirlo dejaría que la
      // API aplicase su suelo automático justo cuando se le pide que no.
      ...(f.min_fg3a !== undefined ? { min_fg3a: f.min_fg3a } : {}),
      ...(f.min_tsa !== undefined ? { min_tsa: f.min_tsa } : {}),
      ...(f.country ? { country: f.country } : {}),
      ...(f.sort ? { sort: f.sort } : {}),
      ...(f.dir ? { dir: f.dir } : {}),
      limit: f.limit ?? 50,
      ...(f.offset ? { offset: f.offset } : {}),
    }),
  // Atajo para los buscadores con autocompletado, que solo quieren nombres.
  searchPlayers: (search: string, limit = 25) =>
    api.players({ search, limit }).then((r) => r.items),
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
  teamTrend: (id: number, stat: string, seasons?: string[]) =>
    get<TeamTrend>(`/teams/${id}/trend`, {
      stat, ...(seasons?.length ? { seasons: seasons.join(',') } : {}),
    }),
  teamSplits: (id: number, dimension: string, stat: string, seasons?: string[]) =>
    get<TeamSplits>(`/teams/${id}/splits`, {
      dimension, stat, ...(seasons?.length ? { seasons: seasons.join(',') } : {}),
    }),
  // --- Fuerza de equipo y pronóstico ---
  ratings: (season?: string) =>
    get<RatingsResponse>('/ratings', season ? { season } : {}),
  backtest: (season?: string) =>
    get<Backtest>('/model/backtest', season ? { season } : {}),
  predict: (p: {
    home: number
    away: number
    season?: string
    neutral?: boolean
    rest_home?: number
    rest_away?: number
    b2b_home?: boolean
    b2b_away?: boolean
    absent_home?: number
    absent_away?: number
  }) =>
    get<Prediction>('/predict', {
      home: p.home,
      away: p.away,
      ...(p.season ? { season: p.season } : {}),
      ...(p.neutral ? { neutral: 'true' } : {}),
      ...(p.rest_home !== undefined ? { rest_home: p.rest_home } : {}),
      ...(p.rest_away !== undefined ? { rest_away: p.rest_away } : {}),
      ...(p.b2b_home ? { b2b_home: 'true' } : {}),
      ...(p.b2b_away ? { b2b_away: 'true' } : {}),
      ...(p.absent_home ? { absent_home: p.absent_home } : {}),
      ...(p.absent_away ? { absent_away: p.absent_away } : {}),
    }),

  teamCatalog: () => get<{ stats: { value: string; label: string }[] }>('/team-catalog'),

  // --- Partido ---
  // El id va como TEXTO: lleva ceros a la izquierda y codifica el tipo de
  // partido en la tercera posición.
  game: (gameId: string) => get<GameDetail>(`/games/${gameId}`),
  gameExpected: (gameId: string) => get<GameExpected>(`/games/${gameId}/expected`),

  // --- Curva de edad ---
  ageCurve: (stat = 'pts_per_36') => get<AgeCurve>('/age-curve', { stat }),

  // --- Qué se repite ---
  stability: (season?: string) =>
    get<StabilityTable>('/stability', season ? { season } : {}),
}
