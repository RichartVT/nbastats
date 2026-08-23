/** Tipos espejo de los esquemas Pydantic de la API. */

export type Reliability = 'alta' | 'media' | 'baja' | 'insuficiente'
export type TrendDirection = 'alza' | 'declive' | 'estable' | 'indeterminada'

export interface PlayerSearchResult {
  player_id: number
  full_name: string
  position: string | null
  birthdate: string | null
  primera: string
  ultima: string
  partidos: number
}

export interface Player {
  player_id: number
  full_name: string
  position: string | null
  height_cm: number | null
  weight_kg: number | null
  birthdate: string | null
  age: number | null
  country: string | null
  draft_year: number | null
  seasons: string[]
  teams: string[]
}

export interface PlayerSeason {
  season_id: string
  season_type: string
  team: string
  games_played: number
  games_with_minutes: number
  min_per_game: number | null
  pts_per_game: number | null
  reb_per_game: number | null
  ast_per_game: number | null
  pts_per_36: number | null
  reb_per_36: number | null
  ast_per_36: number | null
  ts_pct: number | null
  efg_pct: number | null
  avg_game_score: number | null
  plus_minus: number | null
}

/** Un nivel de un split. `value` ya viene resuelto por el backend: es la media
 *  cruda si el split se distingue del resto, y la encogida si no. El frontend
 *  no debe recalcularlo ni preferir `raw_mean` "porque queda mejor". */
export interface Split {
  label: string
  n: number
  value: number | null
  raw_mean: number | null
  shrunk_mean: number | null
  baseline: number | null
  diff_vs_baseline: number | null
  ci95_low: number | null
  ci95_high: number | null
  reliability: Reliability
  distinguishable: boolean
  q_value: number
  note: string
}

export interface SplitsResponse {
  player_id: number
  player_name: string
  stat: string
  stat_label: string
  dimension: string
  dimension_label: string
  seasons: string[]
  total_games: number
  splits: Split[]
  caveat: string
  any_distinguishable: boolean
}

export interface Trend {
  player_id: number
  player_name: string
  stat: string
  stat_label: string
  n: number
  direction: TrendDirection
  reliability: Reliability
  slope_per_season: number | null
  ci95_low: number | null
  ci95_high: number | null
  r_squared: number | null
  mk_p_value: number | null
  tau: number | null
  change_points: number[]
  note: string
  series: number[]
  rolling: (number | null)[]
  dates: string[]
}

export interface Leader {
  player_id: number
  player_name: string
  n: number
  slope_per_season: number
  ci95_low: number
  ci95_high: number
  tau: number
  q_value: number
  direction: TrendDirection
  reliability: Reliability
  current_value: number | null
}

export interface LeadersResponse {
  stat: string
  stat_label: string
  direction: string
  min_games: number
  players_scanned: number
  players_significant: number
  caveat: string
  leaders: Leader[]
}

export interface CatalogStat {
  value: string
  label: string
  is_rate: boolean
  decimals: number
}

export interface CatalogDimension {
  value: string
  label: string
  levels: number
  warning: string
}

export interface Catalog {
  stats: CatalogStat[]
  dimensions: CatalogDimension[]
}
