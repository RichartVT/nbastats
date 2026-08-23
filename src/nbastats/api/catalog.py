"""Catálogo de estadísticas y dimensiones expuestas por la API.

Fuente única de verdad para "qué se puede pedir". Cumple tres funciones a la vez:

1. **Seguridad.** Los nombres de columna nunca llegan desde el cliente a la
   consulta: se resuelven contra este catálogo o se rechazan. No hay
   interpolación de texto del usuario en el SQL.
2. **Documentación.** FastAPI genera el desplegable de valores válidos en
   `/docs` a partir de estos enums.
3. **Honestidad.** Cada estadística declara si es una TASA. Las tasas no
   admiten partidos de 0 minutos, y esa distinción decide qué filas entran en
   cada análisis.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class StatDef:
    column: str
    label: str
    is_rate: bool
    """True si la métrica está normalizada por tiempo o por intento.

    Importa porque las tasas son NULL en los partidos de 0 minutos, y porque
    para detectar declive hay que trabajar en tasas: un jugador que pasa de 20 a
    15 puntos puede estar jugando peor o simplemente jugando menos, y solo la
    tasa distingue las dos cosas.
    """

    decimals: int = 2


class Stat(enum.StrEnum):
    """Estadísticas consultables. El valor es lo que se pasa por la URL."""

    # --- Tasas (recomendadas para tendencias) ---
    PTS_36 = "pts_per_36"
    REB_36 = "reb_per_36"
    AST_36 = "ast_per_36"
    STL_36 = "stl_per_36"
    BLK_36 = "blk_per_36"
    TOV_36 = "tov_per_36"
    TS = "ts_pct"
    EFG = "efg_pct"
    USG = "usg_pct"
    GAME_SCORE = "game_score"

    # --- Totales por partido (para promedios que se comparan con NBA.com) ---
    PTS = "pts"
    REB = "reb"
    AST = "ast"
    STL = "stl"
    BLK = "blk"
    TOV = "tov"
    PLUS_MINUS = "plus_minus"
    MINUTES = "seconds_played"


STATS: dict[Stat, StatDef] = {
    Stat.PTS_36: StatDef("pts_per_36", "Puntos por 36 min", True),
    Stat.REB_36: StatDef("reb_per_36", "Rebotes por 36 min", True),
    Stat.AST_36: StatDef("ast_per_36", "Asistencias por 36 min", True),
    Stat.STL_36: StatDef("stl_per_36", "Robos por 36 min", True),
    Stat.BLK_36: StatDef("blk_per_36", "Tapones por 36 min", True),
    Stat.TOV_36: StatDef("tov_per_36", "Pérdidas por 36 min", True),
    Stat.TS: StatDef("ts_pct", "True Shooting %", True, decimals=3),
    Stat.EFG: StatDef("efg_pct", "Efective FG %", True, decimals=3),
    Stat.USG: StatDef("usg_pct", "Usage %", True, decimals=3),
    Stat.GAME_SCORE: StatDef("game_score", "Game Score", True),
    Stat.PTS: StatDef("pts", "Puntos", False),
    Stat.REB: StatDef("reb", "Rebotes", False),
    Stat.AST: StatDef("ast", "Asistencias", False),
    Stat.STL: StatDef("stl", "Robos", False),
    Stat.BLK: StatDef("blk", "Tapones", False),
    Stat.TOV: StatDef("tov", "Pérdidas", False),
    Stat.PLUS_MINUS: StatDef("plus_minus", "+/-", False),
    Stat.MINUTES: StatDef("seconds_played", "Minutos (en segundos)", False),
}


class Dimension(enum.StrEnum):
    """Dimensiones por las que se puede partir la carrera de un jugador."""

    DAY_OF_WEEK = "dow"
    HOME_AWAY = "home_away"
    REST = "rest"
    OPPONENT = "opponent"
    MONTH = "month"
    BACK_TO_BACK = "b2b"
    SEASON = "season"


DIAS = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves",
        5: "viernes", 6: "sábado", 7: "domingo"}

MESES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
         7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre",
         11: "noviembre", 12: "diciembre"}


@dataclass(frozen=True)
class DimensionDef:
    label: str
    typical_levels: int
    """Cuántos niveles tiene. Multiplica las comparaciones y por tanto el riesgo
    de falsos positivos: 7 días son 7 comparaciones, 29 rivales son 29."""

    warning: str = ""


DIMENSIONS: dict[Dimension, DimensionDef] = {
    Dimension.DAY_OF_WEEK: DimensionDef(
        "Día de la semana", 7,
        "Con una sola temporada hay ~12 partidos por día: insuficiente. Con cinco, "
        "~60 por día — pero entonces se mezclan edades muy distintas del jugador.",
    ),
    Dimension.HOME_AWAY: DimensionDef(
        "Local / visitante", 2,
        "Excluye los partidos en sede neutral: ahí no hay ventaja de campo.",
    ),
    Dimension.REST: DimensionDef(
        "Días de descanso", 4,
        "Muy correlacionado con el día de la semana y con la calidad del rival. "
        "Un aparente efecto de día suele ser en realidad este.",
    ),
    Dimension.OPPONENT: DimensionDef(
        "Rival", 29,
        "~15 partidos por rival en cinco temporadas, y con plantillas que cambiaron "
        "por completo en ese periodo. Además son 29 comparaciones simultáneas.",
    ),
    Dimension.MONTH: DimensionDef(
        "Mes", 7,
        "Enero concentra back-to-backs: controla por descanso antes de concluir.",
    ),
    Dimension.BACK_TO_BACK: DimensionDef("Segundo partido en 2 días", 2),
    Dimension.SEASON: DimensionDef("Temporada", 5),
}
