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
    FG3M_36 = "fg3m_per_36"
    FG3A_36 = "fg3a_per_36"
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
    FG3M = "fg3m"
    FG3A = "fg3a"


STATS: dict[Stat, StatDef] = {
    Stat.PTS_36: StatDef("pts_per_36", "Puntos por 36 min", True),
    Stat.REB_36: StatDef("reb_per_36", "Rebotes por 36 min", True),
    Stat.AST_36: StatDef("ast_per_36", "Asistencias por 36 min", True),
    Stat.STL_36: StatDef("stl_per_36", "Robos por 36 min", True),
    Stat.BLK_36: StatDef("blk_per_36", "Tapones por 36 min", True),
    Stat.TOV_36: StatDef("tov_per_36", "Pérdidas por 36 min", True),
    # El VOLUMEN de triple es decisión, y la decisión se estabiliza mucho antes
    # que el acierto: por eso va como tasa y no solo como total.
    Stat.FG3M_36: StatDef("fg3m_per_36", "Triples anotados por 36 min", True),
    Stat.FG3A_36: StatDef("fg3a_per_36", "Triples intentados por 36 min", True),
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
    Stat.FG3M: StatDef("fg3m", "Triples anotados", False),
    Stat.FG3A: StatDef("fg3a", "Triples intentados", False),
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
    PERIOD = "period"
    STARTER = "starter"


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
    Dimension.STARTER: DimensionDef(
        "Titular o suplente", 2,
        "Salir de inicio no es una condición del jugador, es una decisión del "
        "entrenador que suele seguir al rendimiento y a las lesiones de otros. "
        "Un jugador que rinde mejor de titular puede estar diciendo que juega "
        "mejor con los titulares, no que le siente bien el rol.",
    ),
    Dimension.PERIOD: DimensionDef(
        "Cuarto", 4,
        "Los minutos no se reparten igual entre cuartos: el cuarto cuarto mezcla "
        "cerrar partidos igualados con estar sentado en las palizas. Mira los puntos "
        "junto a los minutos de ese cuarto, nunca solos.",
    ),
}


# =========================================================================
# Filtros del listado de jugadores
#
# Mismo principio que el resto del catálogo: el cliente manda una clave de un
# enum, nunca un trozo de SQL ni un nombre de columna.
# =========================================================================


class PlayerStatusFilter(enum.StrEnum):
    """Situación del jugador. Ver `analysis.player_status` para el porqué de
    estas tres y no de un "Retirado" que los datos no permiten afirmar."""

    ACTIVO = "activo"
    AGENTE_LIBRE = "agente_libre"
    FUERA_LIGA = "fuera_liga"


PLAYER_STATUS_LABELS: dict[PlayerStatusFilter, str] = {
    PlayerStatusFilter.ACTIVO: "En plantilla",
    PlayerStatusFilter.AGENTE_LIBRE: "Agentes libres",
    PlayerStatusFilter.FUERA_LIGA: "Fuera de la liga",
}


class PositionGroup(enum.StrEnum):
    """Puesto, agrupado.

    La NBA no publica los cinco puestos clásicos: solo Guard / Forward /
    Center y sus combinaciones con guion. Ofrecer "Base" y "Escolta" por
    separado sería inventarse una precisión que el dato no tiene.
    """

    GUARD = "guard"
    FORWARD = "forward"
    CENTER = "center"


@dataclass(frozen=True)
class PositionDef:
    label: str
    db_word: str
    """Palabra tal cual la escribe la NBA. Se busca por LIKE para que 'Guard'
    encuentre también a los 'Guard-Forward': un escolta-alero es las dos
    cosas, y dejarlo fuera de los dos filtros lo haría invisible."""


POSITIONS: dict[PositionGroup, PositionDef] = {
    PositionGroup.GUARD: PositionDef("Exteriores (G)", "Guard"),
    PositionGroup.FORWARD: PositionDef("Aleros (F)", "Forward"),
    PositionGroup.CENTER: PositionDef("Interiores (C)", "Center"),
}


class PlayerSort(enum.StrEnum):
    """Columna por la que se ordena el listado. Se combina con `SortDir`."""

    NOMBRE = "nombre"
    EDAD = "edad"
    ALTURA = "altura"
    PARTIDOS = "partidos"
    MINUTOS = "minutos"
    PUNTOS = "puntos"
    REBOTES = "rebotes"
    ASISTENCIAS = "asistencias"
    TS = "ts"
    TRIPLES = "triples"


class SortDir(enum.StrEnum):
    DESC = "desc"
    ASC = "asc"


PLAYER_SORT_LABELS: dict[PlayerSort, str] = {
    PlayerSort.NOMBRE: "Nombre",
    PlayerSort.EDAD: "Edad",
    PlayerSort.ALTURA: "Altura",
    PlayerSort.PARTIDOS: "Partidos",
    PlayerSort.MINUTOS: "Minutos por partido",
    PlayerSort.PUNTOS: "Puntos por partido",
    PlayerSort.REBOTES: "Rebotes por partido",
    PlayerSort.ASISTENCIAS: "Asistencias por partido",
    PlayerSort.TS: "True Shooting %",
    PlayerSort.TRIPLES: "% de triples",
}


# Suelo de intentos de triple, POR PARTIDO. Es la unidad correcta aquí: un
# mínimo de intentos totales cambiaría de significado según el alcance —82
# triples son muchos en una temporada y pocos en cinco—, mientras que "2 por
# partido" quiere decir lo mismo en cualquiera de los dos.
#
# Sin este filtro, ordenar por % de triples encabeza con un pívot que metió
# 1 de 1 en cinco temporadas. El porcentaje es correcto; el ranking, inútil.
# =========================================================================
# Suelos de volumen para los porcentajes
#
# Un porcentaje sin volumen no es una medida, es una anécdota. Ordenar por él
# sin suelo pone arriba a quien metió 1 de 1, con un 100% correcto y un puesto
# que no significa nada.
#
# EL SUELO VA EN INTENTOS TOTALES, NO POR PARTIDO. La precisión de una
# proporción depende del número de intentos y de nada más: el error típico es
# raíz(p(1-p)/n). Un suelo por partido no controla ese n — deja pasar 5,6
# triples por partido en 14 partidos, que son 79 intentos y un margen de ±5,6
# puntos, por delante de quien lleva 1.436 con ±2,6. Los dos números se
# escriben igual y no valen lo mismo.
#
# Referencia: la NBA exige 82 triples ANOTADOS para entrar en su ranking de
# temporada, que son ~230 intentos. De ahí sale el suelo automático.
#
# Son valores por defecto, no imposiciones: pedir 0 explícito los desactiva, y
# la interfaz enseña que están puestos y cómo quitarlos.
MIN_FG3A_AUTO = 200.0

MIN_FG3A_OPTIONS: tuple[tuple[float, str], ...] = (
    (0, "Sin mínimo"),
    (100, "100+ triples lanzados"),
    (200, "200+ lanzados"),
    (400, "400+ lanzados"),
    (800, "800+ lanzados"),
)

# Para el TS% el volumen no son los tiros de campo: son los intentos de tiro
# verdaderos, fga + 0,44 · fta, que es el denominador de la propia fórmula.
# Contar solo los tiros de campo dejaría fuera a quien vive en la línea de
# personal, que es justo quien más TS% saca.
MIN_TSA_AUTO = 500.0

MIN_TSA_OPTIONS: tuple[tuple[float, str], ...] = (
    (0, "Sin mínimo"),
    (200, "200+ tiros"),
    (500, "500+ tiros"),
    (1000, "1000+ tiros"),
    (2000, "2000+ tiros"),
)

# Tope de criterios encadenados. Con cuatro ya se han agotado los empates
# reales; permitir más solo alarga el ORDER BY sin mover una sola fila.
MAX_CRITERIOS_ORDEN = 4


def parse_sort(sort: str, default_dir: str = "desc") -> list[tuple[str, str]]:
    """Traduce el parámetro `sort` a una cadena de criterios.

    Acepta "puntos", "puntos:asc" y "edad:desc,puntos:asc,asistencias:desc".
    Una clave sin dirección hereda `default_dir`, que es lo que mantiene viva
    la forma antigua `?sort=puntos&dir=asc`.

    Se descartan las claves repetidas quedándose con la PRIMERA aparición: en
    una cadena, la primera es la que manda, y volver a ordenar por algo que ya
    está ordenado no puede cambiar nada.

    >>> parse_sort("puntos")
    [('puntos', 'desc')]
    >>> parse_sort("edad:desc,puntos:asc")
    [('edad', 'desc'), ('puntos', 'asc')]
    """
    criterios: list[tuple[str, str]] = []
    vistas: set[str] = set()

    for trozo in sort.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        clave, _, direccion = trozo.partition(":")
        clave = clave.strip().lower()
        direccion = (direccion.strip().lower() or default_dir)

        if clave not in {s.value for s in PlayerSort}:
            raise ValueError(
                f"Orden desconocido: '{clave}'. "
                f"Válidos: {', '.join(s.value for s in PlayerSort)}"
            )
        if direccion not in {d.value for d in SortDir}:
            raise ValueError(f"Dirección desconocida: '{direccion}'. Válidas: asc, desc")

        if clave not in vistas:
            vistas.add(clave)
            criterios.append((clave, direccion))

    return criterios or [(PlayerSort.PARTIDOS.value, default_dir)]

# Los promedios ordenan mal sin un suelo de partidos: quien jugó dos encuentros
# y anotó 20 en uno encabeza la lista de anotadores. No se impone un mínimo por
# defecto —esconder jugadores sin avisar es peor— pero se ofrece el control y
# la interfaz lo sugiere cuando el orden es por promedio.
MIN_GAMES_OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "Sin mínimo"),
    (20, "20+ partidos"),
    (41, "41+ partidos (media temporada)"),
    (58, "58+ partidos (mínimo oficial NBA)"),
)


# Por cuarto NO hay tasas. `player_period_stats` guarda totales y segundos, y
# nada más: extrapolar a 36 minutos desde los 4 que alguien jugó en un tercer
# cuarto produce los mismos disparates que el `pace` de jugador. Pedir una tasa
# con dimensión "cuarto" es un error de la petición, no un hueco que rellenar.
STATS_POR_CUARTO = tuple(s for s in Stat if not STATS[s].is_rate)
