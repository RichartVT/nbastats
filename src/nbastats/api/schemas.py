"""Esquemas de la API.

Son también el contrato del frontend: de aquí salen los tipos de TypeScript.

La decisión de diseño que atraviesa todo el fichero: **ninguna respuesta de
split devuelve un número solo**. Siempre viaja acompañado de `n`, intervalo de
confianza y semáforo de confiabilidad, porque el número sin ese contexto invita
a leer ruido como patrón. Lo mismo con las tendencias.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from nbastats.analysis.reliability import Reliability, SplitEstimate
from nbastats.analysis.trends import TrendDirection, TrendResult
from nbastats.api.catalog import Dimension, Stat


class PlayerStatusOut(BaseModel):
    """Situación del jugador, derivada en `analysis.player_status`."""

    key: str = Field(description="activo | agente_libre | fuera_liga | sin_datos")
    label: str
    note: str = Field(description="Qué significa exactamente, con las fechas")
    on_roster: bool
    team_label: str = Field(description='"Equipo actual" o "Último equipo"')


class PlayerListItemOut(BaseModel):
    """Una fila del listado de jugadores.

    Trae el equipo aunque el jugador ya no esté en activo: para quien no
    pertenece a ninguna plantilla es el ÚLTIMO en el que estuvo, y por eso
    `status.team_label` dice cómo hay que llamarlo. Enseñarlo sin esa distinción
    convierte a un jugador retirado en fichaje de los Lakers.
    """

    player_id: int
    full_name: str
    status: PlayerStatusOut

    position: str | None = None
    jersey_number: str | None = None
    birthdate: dt.date | None = None
    age: float | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    country: str | None = None
    draft_year: int | None = None
    draft_round: int | None = None
    draft_number: int | None = None
    season_experience: int | None = None

    current_team_id: int | None = None
    current_team_abbr: str | None = None
    current_team_name: str | None = None

    primera: str
    ultima: str
    ultima_nba: str = Field(description="Última temporada con partidos, ignorando filtros")
    temporadas: int
    equipos: list[str] = Field(default_factory=list)

    # Los promedios corresponden al ALCANCE pedido: si se filtró por temporada
    # son los de esa temporada, no los de la carrera.
    partidos: int
    partidos_post: int
    min_per_game: float | None = None
    pts_per_game: float | None = None
    reb_per_game: float | None = None
    ast_per_game: float | None = None
    ts_pct: float | None = None

    # El porcentaje de triples nunca viaja solo: sin los intentos por partido
    # no se distingue al tirador de volumen del que metió dos de dos.
    fg3_pct: float | None = None
    fg3a_per_game: float | None = None
    # Los intentos TOTALES del alcance. Son el n del que depende la precisión
    # del porcentaje: 46% en 79 intentos y 46% en 1.436 se escriben igual y no
    # valen lo mismo.
    fg3a: int | None = None
    tsa: int | None = Field(None, description="Intentos de tiro verdaderos: fga + 0,44·fta")


class PlayerListResponse(BaseModel):
    total: int = Field(description="Jugadores que cumplen los filtros, antes del límite")
    shown: int
    latest_season: str
    season: str | None = Field(None, description="Temporada del alcance; null = todas")
    # Un filtro que se aplica solo tiene que decirse: si la respuesta no
    # declarase el suelo, el cliente enseñaría una lista recortada sin saberlo
    # y sin poder explicar por qué falta gente.
    min_fg3a_applied: float = Field(0, description="Suelo de triples lanzados en efecto")
    min_fg3a_auto: bool = Field(
        False, description="True si lo puso la API porque se ordenaba por % de triples"
    )
    min_tsa_applied: float = Field(0, description="Suelo de intentos de tiro en efecto")
    min_tsa_auto: bool = Field(
        False, description="True si lo puso la API porque se ordenaba por TS%"
    )
    items: list[PlayerListItemOut]


class PlayerOut(BaseModel):
    player_id: int
    full_name: str
    position: str | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    birthdate: dt.date | None = None
    age: float | None = Field(None, description="Edad hoy, en años")
    country: str | None = None
    draft_year: int | None = None
    from_year: int | None = None
    to_year: int | None = None
    seasons: list[str] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=list)

    # --- Ficha ---
    jersey_number: str | None = None
    roster_status: str | None = Field(None, description="Active / Inactive")
    season_experience: int | None = None
    current_team_id: int | None = None
    current_team_abbr: str | None = None
    current_team_name: str | None = None
    draft_round: int | None = None
    draft_number: int | None = None
    school: str | None = None

    # El mismo estado derivado que el listado. Va aquí para que la ficha no
    # pueda contradecir a la lista desde la que se llega a ella, que es lo que
    # pasaría si cada una interpretase `roster_status` por su cuenta.
    status: PlayerStatusOut


class PlayerSeasonOut(BaseModel):
    season_id: str
    season_type: str
    team: str
    games_played: int
    games_with_minutes: int
    games_started: int | None = None
    min_per_game: float | None = None

    pts_per_game: float | None = None
    reb_per_game: float | None = None
    ast_per_game: float | None = None
    pts_per_36: float | None = None
    reb_per_36: float | None = None
    ast_per_36: float | None = None

    # --- Tiro ---
    # Los totales viajan junto a los porcentajes a propósito: un 45% en triples
    # con 2 intentos por partido y un 38% con 10 no describen la misma
    # habilidad, y el porcentaje solo no permite distinguirlos.
    fgm: int | None = None
    fga: int | None = None
    fg_pct: float | None = None
    fg3m: int | None = None
    fg3a: int | None = None
    fg3_pct: float | None = None
    fg3m_per_game: float | None = None
    fg3a_per_game: float | None = None
    ftm: int | None = None
    fta: int | None = None
    ft_pct: float | None = None

    stl: int | None = None
    blk: int | None = None
    tov: int | None = None

    ts_pct: float | None = None
    efg_pct: float | None = None
    avg_game_score: float | None = None
    plus_minus: int | None = None


class GameLogEntryOut(BaseModel):
    game_id: str
    date: dt.date
    season_id: str
    season_type: str
    team: str
    opponent: str
    is_home: bool
    is_neutral_site: bool
    won: bool | None = None
    rest_days: int | None = None
    is_back_to_back: bool | None = None
    tipoff_utc: dt.datetime | None = None
    minutes: str = Field(description='Formato "MM:SS"')
    pts: int | None = None
    reb: int | None = None
    ast: int | None = None
    stl: int | None = None
    blk: int | None = None
    tov: int | None = None
    plus_minus: int | None = None
    ts_pct: float | None = None
    usg_pct: float | None = None
    game_score: float | None = None


class SplitOut(BaseModel):
    """Un nivel de un split, con todo lo necesario para no malinterpretarlo."""

    label: str
    n: int = Field(description="Partidos en este split")
    value: float | None = Field(
        None, description="Lo que se debe MOSTRAR: media encogida si no es distinguible"
    )
    raw_mean: float | None = Field(None, description="Media cruda, sin encoger")
    shrunk_mean: float | None = None
    baseline: float | None = Field(None, description="Su promedio en el resto de partidos")
    diff_vs_baseline: float | None = None
    ci95_low: float | None = None
    ci95_high: float | None = None
    reliability: Reliability
    distinguishable: bool = Field(
        description="Si es False, la diferencia no se distingue del azar"
    )
    q_value: float = Field(description="p corregido por comparaciones múltiples (FDR)")
    note: str

    @classmethod
    def from_estimate(cls, e: SplitEstimate) -> SplitOut:
        def limpio(x: float) -> float | None:
            return None if x != x or x in (float("inf"), float("-inf")) else round(x, 4)

        return cls(
            label=e.label,
            n=e.n,
            value=limpio(e.display_mean),
            raw_mean=limpio(e.raw_mean),
            shrunk_mean=limpio(e.shrunk_mean),
            baseline=limpio(e.baseline),
            diff_vs_baseline=limpio(e.diff_vs_baseline),
            ci95_low=limpio(e.ci95_low),
            ci95_high=limpio(e.ci95_high),
            reliability=e.reliability,
            distinguishable=e.distinguishable,
            q_value=round(e.q_value, 4),
            note=e.note,
        )


class SplitsResponse(BaseModel):
    player_id: int
    player_name: str
    stat: Stat
    stat_label: str
    dimension: Dimension
    dimension_label: str
    seasons: list[str]
    total_games: int
    splits: list[SplitOut]
    caveat: str = Field(
        description="Aviso sobre esta dimensión concreta. Debe mostrarse en la UI."
    )
    any_distinguishable: bool = Field(
        description="False significa: no hay ningún patrón aquí, solo ruido."
    )


class TrendOut(BaseModel):
    player_id: int
    player_name: str
    stat: Stat
    stat_label: str
    n: int
    direction: TrendDirection
    reliability: Reliability
    slope_per_season: float | None = Field(
        None, description="Cambio esperado cada 82 partidos"
    )
    ci95_low: float | None = None
    ci95_high: float | None = None
    r_squared: float | None = None
    mk_p_value: float | None = None
    tau: float | None = None
    change_points: list[int] = Field(
        default_factory=list, description="Índices donde el nivel cambia de escalón"
    )
    note: str
    series: list[float] = Field(default_factory=list, description="Valores crudos")
    rolling: list[float | None] = Field(
        default_factory=list, description="Media móvil, solo para dibujar"
    )
    dates: list[dt.date] = Field(default_factory=list)

    @classmethod
    def from_result(
        cls,
        r: TrendResult,
        *,
        player_id: int,
        player_name: str,
        stat: Stat,
        stat_label: str,
        series: list[float],
        rolling: list[float | None],
        dates: list[dt.date],
    ) -> TrendOut:
        def limpio(x: float) -> float | None:
            return None if x != x else round(x, 4)

        return cls(
            player_id=player_id,
            player_name=player_name,
            stat=stat,
            stat_label=stat_label,
            n=r.n,
            direction=r.direction,
            reliability=r.reliability,
            slope_per_season=limpio(r.slope_per_season),
            ci95_low=limpio(r.slope_ci95[0] * 82),
            ci95_high=limpio(r.slope_ci95[1] * 82),
            r_squared=limpio(r.r_squared),
            mk_p_value=limpio(r.mk_p_value),
            tau=limpio(r.tau),
            change_points=r.change_points,
            note=r.note,
            series=[round(v, 4) for v in series],
            rolling=[None if v is None else round(v, 4) for v in rolling],
            dates=dates,
        )


class LeaderOut(BaseModel):
    player_id: int
    player_name: str
    n: int
    slope_per_season: float
    ci95_low: float
    ci95_high: float
    tau: float
    q_value: float = Field(description="Corregido por FDR sobre todos los jugadores")
    direction: TrendDirection
    reliability: Reliability
    current_value: float | None = Field(None, description="Media de los últimos 25 partidos")


class LeadersResponse(BaseModel):
    stat: Stat
    stat_label: str
    direction: str
    min_games: int
    players_scanned: int
    players_significant: int
    caveat: str
    leaders: list[LeaderOut]


# =========================================================================
# Tipo de partido y últimos partidos
# =========================================================================


class GameTypeOut(BaseModel):
    key: str = Field(description="Identificador estable: regular, cup, playoffs…")
    label: str = Field(description="Texto para la insignia: 'NBA Cup · Grupo'")
    is_postseason: bool


class RecentGameOut(BaseModel):
    game_id: str
    date: dt.date
    season_id: str
    game_type: GameTypeOut
    team: str
    opponent: str
    opponent_id: int
    is_home: bool
    is_neutral_site: bool
    won: bool | None = None
    team_pts: int | None = None
    opp_pts: int | None = None
    minutes: str
    pts: int | None = None
    reb: int | None = None
    ast: int | None = None
    stl: int | None = None
    blk: int | None = None
    tov: int | None = None
    fgm: int | None = None
    fga: int | None = None
    fg3m: int | None = None
    fg3a: int | None = None
    ftm: int | None = None
    fta: int | None = None
    plus_minus: int | None = None
    ts_pct: float | None = None
    game_score: float | None = None


class RankedStat(BaseModel):
    value: float | None = None
    rank: int | None = Field(None, description="Puesto en la liga, 1 es el mejor")


class PlayerRanksOut(BaseModel):
    season_id: str
    qualified_players: int = Field(
        description="Cuántos jugadores cumplen el mínimo. El puesto se lee contra esto."
    )
    games_played: int
    pts: RankedStat
    reb: RankedStat
    ast: RankedStat
    stl: RankedStat
    blk: RankedStat
    fg_pct: RankedStat
    ts_pct: RankedStat


# =========================================================================
# Equipos
# =========================================================================


class TeamSummaryOut(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    city: str | None = None
    nickname: str | None = None
    conference: str | None = None
    division: str | None = None
    arena: str | None = None
    wins: int | None = None
    losses: int | None = None
    win_pct: float | None = None
    playoff_rank: int | None = None
    diff_points_pg: float | None = None
    # Formato "31-10", tal cual lo publica la liga.
    home_record: str | None = None
    road_record: str | None = None


class RosterEntryOut(BaseModel):
    player_id: int
    full_name: str
    jersey_number: str | None = None
    position: str | None = None
    age: float | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    roster_status: str | None = None
    season_experience: int | None = None
    how_acquired: str | None = None
    games: int = 0
    min_per_game: float | None = None
    pts_per_game: float | None = None
    reb_per_game: float | None = None
    ast_per_game: float | None = None


class TeamOut(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    city: str | None = None
    nickname: str | None = None
    conference: str | None = None
    division: str | None = None
    arena: str | None = None
    arena_capacity: int | None = None
    owner: str | None = None
    general_manager: str | None = None
    head_coach: str | None = None
    year_founded: int | None = None

    season_id: str | None = None
    wins: int | None = None
    losses: int | None = None
    win_pct: float | None = None
    playoff_rank: int | None = None
    conference_record: str | None = None
    division_record: str | None = None
    home_record: str | None = None
    road_record: str | None = None
    last_10: str | None = None
    current_streak: int | None = None
    points_pg: float | None = None
    opp_points_pg: float | None = None
    diff_points_pg: float | None = None

    roster: list[RosterEntryOut] = Field(default_factory=list)


class TeamGameOut(BaseModel):
    game_id: str
    date: dt.date
    season_id: str
    game_type: GameTypeOut
    opponent: str
    opponent_id: int
    is_home: bool
    is_neutral_site: bool
    won: bool | None = None
    rest_days: int | None = None
    is_back_to_back: bool | None = None
    pts: int | None = None
    opp_pts: int | None = None
    point_diff: int | None = None
    reb: int | None = None
    ast: int | None = None
    tov: int | None = None
    off_rating: float | None = None
    def_rating: float | None = None
    pace: float | None = None
    ts_pct: float | None = None


class StandingOut(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    conference: str | None = None
    division: str | None = None
    playoff_rank: int | None = None
    wins: int | None = None
    losses: int | None = None
    win_pct: float | None = None
    games_back: float | None = None
    conference_record: str | None = None
    division_record: str | None = None
    home_record: str | None = None
    road_record: str | None = None
    last_10: str | None = None
    current_streak: int | None = None
    points_pg: float | None = None
    opp_points_pg: float | None = None
    diff_points_pg: float | None = None


class HeadToHeadOut(BaseModel):
    team_a: TeamSummaryOut
    team_b: TeamSummaryOut
    seasons: list[str]
    games_played: int
    team_a_wins: int
    team_b_wins: int
    avg_point_diff: float | None = Field(
        None, description="Diferencial medio desde la perspectiva del primer equipo"
    )
    games: list[TeamGameOut] = Field(default_factory=list)


# =========================================================================
# Detalle de un partido: todo lo que hay
# =========================================================================


class PlayerBoxScoreOut(BaseModel):
    """La línea completa de un jugador en un partido."""

    player_id: int
    full_name: str
    jersey_number: str | None = None
    position: str | None = None
    team_id: int
    minutes: str
    started: bool | None = None

    pts: int | None = None
    fgm: int | None = None
    fga: int | None = None
    fg3m: int | None = None
    fg3a: int | None = None
    ftm: int | None = None
    fta: int | None = None
    oreb: int | None = None
    dreb: int | None = None
    reb: int | None = None
    ast: int | None = None
    stl: int | None = None
    blk: int | None = None
    tov: int | None = None
    pf: int | None = None
    plus_minus: int | None = None

    # Avanzadas
    ts_pct: float | None = None
    efg_pct: float | None = None
    usg_pct: float | None = None
    ast_pct: float | None = None
    reb_pct: float | None = None
    off_rating: float | None = None
    def_rating: float | None = None
    net_rating: float | None = None
    pie: float | None = None
    game_score: float | None = None


class TeamBoxScoreOut(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    is_home: bool
    won: bool | None = None

    pts: int | None = None
    fgm: int | None = None
    fga: int | None = None
    fg3m: int | None = None
    fg3a: int | None = None
    ftm: int | None = None
    fta: int | None = None
    oreb: int | None = None
    dreb: int | None = None
    reb: int | None = None
    ast: int | None = None
    stl: int | None = None
    blk: int | None = None
    tov: int | None = None
    pf: int | None = None
    plus_minus: int | None = None

    possessions: float | None = None
    pace: float | None = None
    off_rating: float | None = None
    def_rating: float | None = None
    net_rating: float | None = None
    ts_pct: float | None = None
    efg_pct: float | None = None

    rest_days: int | None = None
    is_back_to_back: bool | None = None

    players: list[PlayerBoxScoreOut] = Field(default_factory=list)


class GameDetailOut(BaseModel):
    """Todo lo que sabemos de un partido.

    No hay más en la base: sin play-by-play, no existe desglose por cuarto,
    ni secuencia de anotación, ni datos de tiro por zona. `CAPABILITIES.md` §2
    lista lo que haría falta cargar para cada una de esas cosas.
    """

    game_id: str
    date: dt.date
    season_id: str
    game_type: GameTypeOut
    tipoff_utc: dt.datetime | None = None
    ot_periods: int = 0
    is_neutral_site: bool = False
    attendance: int | None = None

    home: TeamBoxScoreOut
    away: TeamBoxScoreOut
