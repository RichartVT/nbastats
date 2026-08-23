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
  jersey_number: string | null
  roster_status: string | null
  season_experience: number | null
  current_team_id: number | null
  current_team_abbr: string | null
  current_team_name: string | null
  draft_round: number | null
  draft_number: number | null
  school: string | null
}

export interface GameType {
  key: string
  label: string
  is_postseason: boolean
}

export interface RecentGame {
  game_id: string
  date: string
  season_id: string
  game_type: GameType
  team: string
  opponent: string
  opponent_id: number
  is_home: boolean
  is_neutral_site: boolean
  won: boolean | null
  team_pts: number | null
  opp_pts: number | null
  minutes: string
  pts: number | null
  reb: number | null
  ast: number | null
  stl: number | null
  blk: number | null
  tov: number | null
  fgm: number | null
  fga: number | null
  fg3m: number | null
  fg3a: number | null
  ftm: number | null
  fta: number | null
  plus_minus: number | null
  ts_pct: number | null
  game_score: number | null
}

export interface RankedStat {
  value: number | null
  rank: number | null
}

export interface PlayerRanks {
  season_id: string
  qualified_players: number
  games_played: number
  pts: RankedStat
  reb: RankedStat
  ast: RankedStat
  stl: RankedStat
  blk: RankedStat
  fg_pct: RankedStat
  ts_pct: RankedStat
}

export interface TeamSummary {
  team_id: number
  abbreviation: string
  full_name: string
  city: string | null
  nickname: string | null
  conference: string | null
  division: string | null
  arena: string | null
  wins: number | null
  losses: number | null
  win_pct: number | null
  playoff_rank: number | null
  diff_points_pg: number | null
}

export interface RosterEntry {
  player_id: number
  full_name: string
  jersey_number: string | null
  position: string | null
  age: number | null
  height_cm: number | null
  weight_kg: number | null
  roster_status: string | null
  season_experience: number | null
  how_acquired: string | null
  games: number
  min_per_game: number | null
  pts_per_game: number | null
  reb_per_game: number | null
  ast_per_game: number | null
}

export interface Team extends TeamSummary {
  arena_capacity: number | null
  owner: string | null
  general_manager: string | null
  head_coach: string | null
  year_founded: number | null
  season_id: string | null
  conference_record: string | null
  division_record: string | null
  home_record: string | null
  road_record: string | null
  last_10: string | null
  current_streak: number | null
  points_pg: number | null
  opp_points_pg: number | null
  roster: RosterEntry[]
}

export interface TeamGame {
  game_id: string
  date: string
  season_id: string
  game_type: GameType
  opponent: string
  opponent_id: number
  is_home: boolean
  is_neutral_site: boolean
  won: boolean | null
  pts: number | null
  opp_pts: number | null
  point_diff: number | null
  reb: number | null
  ast: number | null
  tov: number | null
  off_rating: number | null
  def_rating: number | null
  pace: number | null
  ts_pct: number | null
}

export interface Standing {
  team_id: number
  abbreviation: string
  full_name: string
  conference: string | null
  division: string | null
  playoff_rank: number | null
  wins: number | null
  losses: number | null
  win_pct: number | null
  games_back: number | null
  conference_record: string | null
  division_record: string | null
  home_record: string | null
  road_record: string | null
  last_10: string | null
  current_streak: number | null
  points_pg: number | null
  opp_points_pg: number | null
  diff_points_pg: number | null
}

export interface HeadToHead {
  team_a: TeamSummary
  team_b: TeamSummary
  seasons: string[]
  games_played: number
  team_a_wins: number
  team_b_wins: number
  avg_point_diff: number | null
  games: TeamGame[]
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
