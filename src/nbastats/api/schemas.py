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


class PlayerSeasonOut(BaseModel):
    season_id: str
    season_type: str
    team: str
    games_played: int
    games_with_minutes: int
    min_per_game: float | None = None
    pts_per_game: float | None = None
    reb_per_game: float | None = None
    ast_per_game: float | None = None
    pts_per_36: float | None = None
    reb_per_36: float | None = None
    ast_per_36: float | None = None
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
