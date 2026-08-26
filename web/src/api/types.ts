/** Tipos espejo de los esquemas Pydantic de la API. */

export type Reliability = 'alta' | 'media' | 'baja' | 'insuficiente'
export type TrendDirection = 'alza' | 'declive' | 'estable' | 'indeterminada'

export type PlayerStatusKey = 'activo' | 'agente_libre' | 'fuera_liga' | 'sin_datos'

/** Situación del jugador, derivada en el backend. `team_label` no es
 *  decorativo: dice si el equipo que acompaña a la fila es el ACTUAL o el
 *  ÚLTIMO, y esa palabra es lo único que separa un fichaje de un exjugador. */
export interface PlayerStatus {
  key: PlayerStatusKey
  label: string
  note: string
  on_roster: boolean
  team_label: string
}

export interface PlayerListItem {
  player_id: number
  full_name: string
  status: PlayerStatus

  position: string | null
  jersey_number: string | null
  birthdate: string | null
  age: number | null
  height_cm: number | null
  weight_kg: number | null
  country: string | null
  draft_year: number | null
  draft_round: number | null
  draft_number: number | null
  season_experience: number | null

  current_team_id: number | null
  current_team_abbr: string | null
  current_team_name: string | null

  primera: string
  ultima: string
  ultima_nba: string
  temporadas: number
  equipos: string[]

  // Referidos al alcance pedido: con filtro de temporada son los de esa
  // temporada, sin él los de las cinco cargadas.
  partidos: number
  partidos_post: number
  min_per_game: number | null
  pts_per_game: number | null
  reb_per_game: number | null
  ast_per_game: number | null
  ts_pct: number | null
  // El porcentaje de triples nunca se enseña solo: sin los intentos no se
  // distingue al tirador de volumen del que metió dos de dos.
  fg3_pct: number | null
  fg3a_per_game: number | null
  /** Intentos TOTALES del alcance: el n del que depende la precisión del
   *  porcentaje. 46% en 79 intentos y 46% en 1.436 no valen lo mismo. */
  fg3a: number | null
  tsa: number | null
}

export interface PlayerListResponse {
  total: number
  shown: number
  latest_season: string
  season: string | null
  /** Suelo de triples por partido en efecto, lo haya pedido el cliente o no. */
  min_fg3a_applied: number
  /** True si lo puso la API porque se ordenaba por % de triples. */
  min_fg3a_auto: boolean
  min_tsa_applied: number
  min_tsa_auto: boolean
  items: PlayerListItem[]
}

/** Filtros del listado. Todo opcional: sin nada, salen todos. */
export interface PlayerFilters {
  search?: string
  status?: string
  team_id?: number
  position?: string
  season?: string
  min_games?: number
  /** Suelo de triples lanzados en el alcance (totales, no por partido). */
  min_fg3a?: number
  /** Suelo de intentos de tiro verdaderos (fga + 0,44·fta). */
  min_tsa?: number
  country?: string
  /** Uno o varios criterios: 'puntos' o 'edad:desc,puntos:asc'. */
  sort?: string
  dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
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
  status: PlayerStatus
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
  /** Formato "31-10", tal cual lo publica la liga. */
  home_record: string | null
  road_record: string | null
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
  rest_days: number | null
  is_back_to_back: boolean | null
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
  games_started: number | null
  min_per_game: number | null
  pts_per_game: number | null
  reb_per_game: number | null
  ast_per_game: number | null
  pts_per_36: number | null
  reb_per_36: number | null
  ast_per_36: number | null
  fgm: number | null
  fga: number | null
  fg_pct: number | null
  fg3m: number | null
  fg3a: number | null
  fg3_pct: number | null
  fg3m_per_game: number | null
  fg3a_per_game: number | null
  ftm: number | null
  fta: number | null
  ft_pct: number | null
  stl: number | null
  blk: number | null
  tov: number | null
  ts_pct: number | null
  efg_pct: number | null
  avg_game_score: number | null
  plus_minus: number | null
}

export interface PlayerBoxScore {
  player_id: number
  full_name: string
  jersey_number: string | null
  position: string | null
  team_id: number
  minutes: string
  started: boolean | null
  pts: number | null
  fgm: number | null
  fga: number | null
  fg3m: number | null
  fg3a: number | null
  ftm: number | null
  fta: number | null
  oreb: number | null
  dreb: number | null
  reb: number | null
  ast: number | null
  stl: number | null
  blk: number | null
  tov: number | null
  pf: number | null
  plus_minus: number | null
  ts_pct: number | null
  efg_pct: number | null
  usg_pct: number | null
  ast_pct: number | null
  reb_pct: number | null
  off_rating: number | null
  def_rating: number | null
  net_rating: number | null
  pie: number | null
  game_score: number | null
  /** Puntos por periodo, con la clave como texto: {"1": 8, "4": 11}. Un periodo
   *  AUSENTE significa que no jugó ese cuarto, no que anotara cero. */
  points_by_period: Record<string, number>
}

export interface TeamBoxScore {
  team_id: number
  abbreviation: string
  full_name: string
  is_home: boolean
  won: boolean | null
  pts: number | null
  fgm: number | null
  fga: number | null
  fg3m: number | null
  fg3a: number | null
  ftm: number | null
  fta: number | null
  oreb: number | null
  dreb: number | null
  reb: number | null
  ast: number | null
  stl: number | null
  blk: number | null
  tov: number | null
  pf: number | null
  plus_minus: number | null
  possessions: number | null
  pace: number | null
  off_rating: number | null
  def_rating: number | null
  net_rating: number | null
  ts_pct: number | null
  efg_pct: number | null
  rest_days: number | null
  is_back_to_back: boolean | null
  /** Récord con el que el equipo LLEGABA al partido, sin contarlo. */
  wins_before: number | null
  losses_before: number | null
  players: PlayerBoxScore[]
}

export interface PeriodScore {
  team_id: number
  period: number
  points: number
  /** Lo dice la fuente (`periodType`), no se deduce de `period > 4`. */
  is_overtime: boolean
}

export interface Official {
  official_id: number
  name: string
  jersey_number: string | null
}

export interface GameDetail {
  game_id: string
  date: string
  season_id: string
  game_type: GameType
  tipoff_utc: string | null
  ot_periods: number
  is_neutral_site: boolean
  attendance: number | null
  arena_name: string | null
  /** VACÍO significa que el resumen del partido aún no se ha descargado, no
   *  que no hubiera cuartos. Pintar ceros ahí sería inventarse el dato. */
  periods: PeriodScore[]
  officials: Official[]
  home: TeamBoxScore
  away: TeamBoxScore
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

export interface SplitsResponse extends SplitsBase {
  player_id: number
  player_name: string
  seasons: string[]
}

/**
 * Lo que un gráfico de tendencia necesita, sin saber de quién es.
 *
 * Jugadores y equipos comparten forma a propósito: es lo que permite que
 * `TrendChart` sirva a los dos sin ramificar, igual que en el backend
 * `analyze_trend` no sabe si los números vienen de una persona o de una
 * franquicia.
 */
export interface TrendBase {
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

export interface Trend extends TrendBase {
  player_id: number
  player_name: string
}

export interface TeamTrend extends TrendBase {
  team_id: number
  team_name: string
}

/** Igual que TrendBase, para los splits. */
export interface SplitsBase {
  stat: string
  stat_label: string
  dimension: string
  dimension_label: string
  total_games: number
  splits: Split[]
  caveat: string
  any_distinguishable: boolean
}

export interface TeamSplits extends SplitsBase {
  team_id: number
  team_name: string
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

export interface CatalogOption {
  value: string
  label: string
}

export interface Catalog {
  stats: CatalogStat[]
  dimensions: CatalogDimension[]
}
