"""Consultas a la base. Todo lee de las vistas materializadas.

Los nombres de columna se resuelven SIEMPRE contra `catalog.STATS`, nunca desde
texto del cliente. Es lo que permite construir el SQL con f-strings sin abrir un
hueco de inyección: el único camino desde la petición hasta la consulta pasa por
un enum validado por FastAPI.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from nbastats.api.catalog import (
    DIAS,
    MAX_CRITERIOS_ORDEN,
    MESES,
    STATS,
    Dimension,
    Stat,
)
from nbastats.ingest.transforms import format_seconds

# Los partidos de pretemporada nunca entran; ya se excluyen en la vista.
_TIPOS_DEFECTO = ("regular",)


def _filtro_temporadas(seasons: list[str] | None) -> tuple[str, dict]:
    if not seasons:
        return "", {}
    return " AND r.season_id = ANY(:seasons)", {"seasons": seasons}


# =========================================================================
# Jugadores
# =========================================================================


# Las expresiones derivadas viven aquí y no incrustadas en el SELECT porque el
# ORDER BY necesita las MISMAS. Postgres deja ordenar por un alias de salida
# suelto, pero no por una expresión que lo contenga —`ROUND(pts_per_game, 1)`
# no compila—, así que o se comparten o se escriben dos veces y se separan.
_CALCULADAS: dict[str, str] = {
    "min_per_game": "(a.segundos / 60.0 / NULLIF(a.partidos, 0))",
    "pts_per_game": "(a.pts::numeric / NULLIF(a.partidos, 0))",
    "reb_per_game": "(a.reb::numeric / NULLIF(a.partidos, 0))",
    "ast_per_game": "(a.ast::numeric / NULLIF(a.partidos, 0))",
    "tsa": "(a.fga + 0.44 * a.fta)",
    "ts_pct": "(a.pts / NULLIF(2 * (a.fga + 0.44 * a.fta), 0))",
    "fg3_pct": "(a.fg3m::numeric / NULLIF(a.fg3a, 0))",
    "fg3a_per_game": "(a.fg3a::numeric / NULLIF(a.partidos, 0))",
    # Años cumplidos, no la fecha de nacimiento: es lo que se enseña en la
    # columna y lo que hace que "ordenar por edad y luego por puntos" agrupe a
    # todos los de 30 en vez de dejar 300 grupos de uno.
    "edad": "((CURRENT_DATE - p.birthdate) / 365.25)",
}


@dataclass(frozen=True)
class OrdenDef:
    exacta: str
    """Expresión con toda la precisión que hay en la base."""

    mostrada: str
    """La misma, redondeada a lo que el usuario ve en pantalla."""

    invertir: bool = False
    """Para las columnas donde "de mayor a menor" es ASC en SQL: el nombre
    (A-Z es lo natural, no Z-A)."""


# Orden del listado. El cliente manda claves de este diccionario y direcciones,
# nunca un trozo de SQL: es lo que permite construir el ORDER BY con f-string
# sin abrir un hueco de inyección.
_ORDEN_JUGADORES: dict[str, OrdenDef] = {
    "nombre": OrdenDef("p.full_name", "p.full_name", invertir=True),
    "edad": OrdenDef(_CALCULADAS["edad"], f"FLOOR({_CALCULADAS['edad']})"),
    "altura": OrdenDef("p.height_cm", "p.height_cm"),
    "partidos": OrdenDef("a.partidos", "a.partidos"),
    "minutos": OrdenDef(_CALCULADAS["min_per_game"], f"ROUND({_CALCULADAS['min_per_game']}, 1)"),
    "puntos": OrdenDef(_CALCULADAS["pts_per_game"], f"ROUND({_CALCULADAS['pts_per_game']}, 1)"),
    "rebotes": OrdenDef(_CALCULADAS["reb_per_game"], f"ROUND({_CALCULADAS['reb_per_game']}, 1)"),
    "asistencias": OrdenDef(
        _CALCULADAS["ast_per_game"], f"ROUND({_CALCULADAS['ast_per_game']}, 1)"
    ),
    "ts": OrdenDef(_CALCULADAS["ts_pct"], f"ROUND({_CALCULADAS['ts_pct']}, 3)"),
    "triples": OrdenDef(_CALCULADAS["fg3_pct"], f"ROUND({_CALCULADAS['fg3_pct']}, 3)"),
}

def _orden(criterios: list[tuple[str, str]]) -> str:
    """Construye el ORDER BY de una cadena de criterios.

    LA REGLA QUE HACE QUE ENCADENAR SIRVA DE ALGO: los criterios que NO son el
    último ordenan por el valor REDONDEADO A LO QUE SE VE, y el último por el
    valor exacto.

    Sin eso, "por edad y luego por puntos" no cambiaría ni una fila: la edad
    exacta es la fecha de nacimiento, casi única por jugador, así que no habría
    dos empatados y el segundo criterio no llegaría a aplicarse nunca. El
    usuario pediría una combinación y vería exactamente la misma lista.

    Redondear solo los criterios intermedios mantiene lo otro que importa: con
    un único criterio, el orden sigue siendo el exacto, sin agrupar por el
    decimal que se enseña.
    """
    criterios = criterios[:MAX_CRITERIOS_ORDEN] or [("partidos", "desc")]

    partes = []
    for i, (clave, direccion) in enumerate(criterios):
        d = _ORDEN_JUGADORES.get(clave)
        if d is None:
            continue
        es_ultimo = i == len(criterios) - 1
        expresion = d.exacta if es_ultimo else d.mostrada
        descendente = (direccion != "asc") != d.invertir
        # NULLS LAST en las dos direcciones: un jugador sin porcentaje de tiro
        # no es el peor tirador de la liga, es un jugador del que no hay dato,
        # y encabezar con él la lista ascendente sería leerlo como lo primero.
        partes.append(f"{expresion} {'DESC' if descendente else 'ASC'} NULLS LAST")

    if not partes:
        partes = [f"{_ORDEN_JUGADORES['partidos'].exacta} DESC NULLS LAST"]

    # Desempate final estable: sin él, dos jugadores con los mismos valores
    # pueden intercambiarse entre peticiones y hacer que "Mostrar más" repita
    # o se salte filas.
    return ", ".join(partes) + ", p.full_name, p.player_id"


# Traducción del estado mostrable a SQL, para poder filtrar por él sin traerse
# los 1.030 jugadores a Python. Las etiquetas y las notas las sigue escribiendo
# `analysis.player_status`; aquí solo está el predicado, y `test_player_status`
# comprueba que los dos digan lo mismo.
_CONDICION_ESTADO = {
    "activo": "p.roster_status = 'Active'",
    "agente_libre": (
        "p.roster_status IS DISTINCT FROM 'Active' "
        "AND c.ultima_nba = CAST(:latest AS varchar)"
    ),
    "fuera_liga": (
        "p.roster_status IS DISTINCT FROM 'Active' "
        "AND c.ultima_nba < CAST(:latest AS varchar)"
    ),
}


def latest_season(session: Session) -> str:
    """La temporada más reciente CON PARTIDOS CARGADOS.

    No se lee de la tabla `seasons`: ahí puede haber una temporada declarada
    cuya ingesta todavía no ha corrido, y entonces todo el mundo aparecería
    como "fuera de la liga" por un dato que no ha llegado.
    """
    return session.execute(
        text("SELECT MAX(season_id) FROM mv_player_season")
    ).scalar() or ""


def list_seasons(session: Session) -> list[str]:
    """Temporadas con partidos, de la más reciente a la más antigua."""
    filas = session.execute(
        text("SELECT DISTINCT season_id FROM mv_player_season ORDER BY season_id DESC")
    ).scalars().all()
    return list(filas)


def dataset_counts(session: Session) -> dict:
    """Qué hay cargado, para que la interfaz no lo lleve escrito a mano.

    `Layout.tsx` mostraba "5 temporadas · 6.602 partidos" como texto fijo, que
    es la misma trampa que la lista de temporadas a mano: en cuanto entra una
    temporada nueva, miente y nadie se entera.
    """
    f = session.execute(
        text("""
            SELECT COUNT(*) AS partidos,
                   COUNT(DISTINCT season_id) AS temporadas,
                   MAX(game_date_local) AS ultimo
            FROM games
        """)
    ).mappings().one()
    return {
        "games": int(f["partidos"]),
        "seasons": int(f["temporadas"]),
        "last_game_date": f["ultimo"],
    }


def list_countries(session: Session) -> list[dict]:
    """Países presentes en la plantilla de jugadores, con cuántos hay de cada uno.

    Es el campo COUNTRY de la ficha oficial: el país de origen que publica la
    NBA, no necesariamente al que representa en competición internacional. Se
    devuelve tal cual lo escribe la liga ("USA", "Bosnia and Herzegovina") en
    vez de traducirlo: una tabla de traducción a mano se desincroniza en cuanto
    aparece un país nuevo, y media lista en español y media en inglés se lee
    peor que toda en el idioma de la fuente.
    """
    filas = session.execute(
        text("""
            SELECT p.country, COUNT(*) AS n
            FROM players p
            WHERE p.country IS NOT NULL
              AND EXISTS (SELECT 1 FROM mv_player_season s
                          WHERE s.player_id = p.player_id)
            GROUP BY p.country
            ORDER BY p.country
        """)
    ).mappings().all()
    return [dict(f) for f in filas]


def search_players(
    session: Session,
    query: str = "",
    limit: int = 25,
    *,
    offset: int = 0,
    status: str | None = None,
    team_id: int | None = None,
    position: str | None = None,
    season: str | None = None,
    min_games: int = 0,
    country: str | None = None,
    min_fg3a: float = 0,
    min_tsa: float = 0,
    criterios: list[tuple[str, str]] | None = None,
) -> dict:
    """Listado de jugadores con su situación actual, filtrable.

    Devuelve `{"total", "latest_season", "items"}`. El total es el de jugadores
    que cumplen los filtros ANTES del límite: sin él, una lista recortada a 100
    se lee como si esos 100 fueran todos.

    Se agregan DOS cosas distintas, y la diferencia importa:

    - `carrera` recorre todas las temporadas cargadas y sirve para una sola
      cosa: cuándo jugó por última vez, que es lo que decide su estado.
    - `alcance` respeta el filtro de temporada, y de ahí salen los números.

    Separarlas es lo que evita que, al filtrar por 2022-23, todos los que no
    están en plantilla parezcan llevar tres años fuera de la liga: dentro de
    ese filtro su última temporada es 2022-23 para todos.
    """
    condiciones: list[str] = [
        # immutable_unaccent() hace que "Jokic" encuentre a "Nikola Jokić" y
        # "Doncic" a "Dončić". Nadie teclea los diacríticos al buscar.
        "(:q = '' OR lower(immutable_unaccent(p.full_name))"
        " LIKE lower(immutable_unaccent(:like)))",
        "(:min_games = 0 OR a.partidos >= :min_games)",
        "(CAST(:team_id AS bigint) IS NULL OR p.current_team_id = :team_id)",
        # 'Guard' casa también con 'Guard-Forward', que es lo que se quiere: un
        # escolta-alero es las dos cosas, no una tercera.
        "(CAST(:position AS varchar) IS NULL OR p.position LIKE :position_like)",
        "(CAST(:country AS varchar) IS NULL OR p.country = :country)",
        # Los suelos van sobre los intentos TOTALES del alcance: es el n del
        # que depende la precisión del porcentaje.
        "(:min_fg3a = 0 OR a.fg3a >= :min_fg3a)",
        f"(:min_tsa = 0 OR {_CALCULADAS['tsa']} >= :min_tsa)",
    ]
    if status in _CONDICION_ESTADO:
        condiciones.append(f"({_CONDICION_ESTADO[status]})")

    orden = _orden(criterios or [])

    C = _CALCULADAS
    sql = text(f"""
        WITH carrera AS (
            SELECT player_id, MAX(season_id) AS ultima_nba
            FROM mv_player_season
            GROUP BY player_id
        ),
        alcance AS (
            SELECT s.player_id,
                   MIN(s.season_id) AS primera,
                   MAX(s.season_id) AS ultima,
                   COUNT(DISTINCT s.season_id) AS temporadas,
                   ARRAY_AGG(DISTINCT t.abbreviation) AS equipos,
                   COALESCE(SUM(s.games_played)
                       FILTER (WHERE s.season_type = 'regular'), 0) AS partidos,
                   COALESCE(SUM(s.games_played)
                       FILTER (WHERE s.season_type <> 'regular'), 0) AS partidos_post,
                   -- Los promedios salen de los TOTALES, no de promediar los
                   -- promedios de cada fila: un traspasado tiene dos filas con
                   -- distinto número de partidos, y la media de las dos medias
                   -- no es su media.
                   SUM(s.pts) FILTER (WHERE s.season_type = 'regular') AS pts,
                   SUM(s.reb) FILTER (WHERE s.season_type = 'regular') AS reb,
                   SUM(s.ast) FILTER (WHERE s.season_type = 'regular') AS ast,
                   SUM(s.fga) FILTER (WHERE s.season_type = 'regular') AS fga,
                   SUM(s.fta) FILTER (WHERE s.season_type = 'regular') AS fta,
                   SUM(s.fg3m) FILTER (WHERE s.season_type = 'regular') AS fg3m,
                   SUM(s.fg3a) FILTER (WHERE s.season_type = 'regular') AS fg3a,
                   SUM(s.seconds_played)
                       FILTER (WHERE s.season_type = 'regular') AS segundos
            FROM mv_player_season s
            JOIN teams t ON t.team_id = s.team_id
            WHERE (CAST(:season AS varchar) IS NULL OR s.season_id = :season)
            GROUP BY s.player_id
        )
        SELECT p.player_id, p.full_name, p.position, p.birthdate,
               p.height_cm, p.weight_kg, p.country,
               p.jersey_number, p.roster_status, p.season_experience,
               p.draft_year, p.draft_round, p.draft_number,
               p.current_team_id,
               ct.abbreviation AS current_team_abbr,
               ct.full_name    AS current_team_name,
               c.ultima_nba,
               a.primera, a.ultima, a.temporadas, a.equipos,
               a.partidos, a.partidos_post,
               {C['pts_per_game']}::numeric(6,2) AS pts_per_game,
               {C['reb_per_game']}::numeric(6,2) AS reb_per_game,
               {C['ast_per_game']}::numeric(6,2) AS ast_per_game,
               {C['min_per_game']}::numeric(5,2) AS min_per_game,
               {C['ts_pct']}::numeric(6,4) AS ts_pct,
               -- El porcentaje de triples viaja SIEMPRE con los intentos por
               -- partido. Un 45% con 2 intentos y un 38% con 10 no describen la
               -- misma habilidad, y el porcentaje solo no permite distinguirlos.
               {C['fg3_pct']}::numeric(6,4) AS fg3_pct,
               {C['fg3a_per_game']}::numeric(5,2) AS fg3a_per_game,
               a.fg3a,
               {C['tsa']}::int AS tsa,
               COUNT(*) OVER () AS total
        FROM players p
        JOIN alcance a ON a.player_id = p.player_id
        JOIN carrera c ON c.player_id = p.player_id
        LEFT JOIN teams ct ON ct.team_id = p.current_team_id
        WHERE {" AND ".join(condiciones)}
        ORDER BY {orden}
        LIMIT :limit OFFSET :offset
    """)

    ultima_liga = latest_season(session)
    filas = session.execute(
        sql,
        {
            "q": query,
            "like": f"%{query}%",
            "season": season,
            "team_id": team_id,
            "position": position,
            "position_like": f"%{position}%" if position else None,
            "min_games": min_games,
            "country": country,
            "min_fg3a": min_fg3a,
            "min_tsa": min_tsa,
            "latest": ultima_liga,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()

    items = []
    for f in filas:
        d = dict(f)
        d.pop("total", None)
        if d.get("birthdate"):
            d["age"] = round((dt.date.today() - d["birthdate"]).days / 365.25, 1)
        else:
            d["age"] = None
        d["equipos"] = [e for e in (d.get("equipos") or []) if e]
        items.append(d)

    return {
        "total": filas[0]["total"] if filas else 0,
        "latest_season": ultima_liga,
        "items": items,
    }


def get_player(session: Session, player_id: int) -> dict | None:
    sql = text("""
        SELECT p.*,
               ct.abbreviation AS current_team_abbr,
               ct.full_name    AS current_team_name,
               ARRAY_AGG(DISTINCT r.season_id ORDER BY r.season_id) AS seasons,
               ARRAY_AGG(DISTINCT t.abbreviation)                   AS teams
        FROM players p
        LEFT JOIN teams ct ON ct.team_id = p.current_team_id
        LEFT JOIN mv_player_game_rates r USING (player_id)
        LEFT JOIN teams t ON t.team_id = r.team_id
        WHERE p.player_id = :pid
        GROUP BY p.player_id, ct.abbreviation, ct.full_name
    """)
    fila = session.execute(sql, {"pid": player_id}).mappings().first()
    if not fila:
        return None

    datos = dict(fila)
    if datos.get("birthdate"):
        dias = (dt.date.today() - datos["birthdate"]).days
        datos["age"] = round(dias / 365.25, 1)
    datos["seasons"] = [s for s in (datos.get("seasons") or []) if s]
    datos["teams"] = [t for t in (datos.get("teams") or []) if t]
    return datos


def get_player_seasons(session: Session, player_id: int) -> list[dict]:
    sql = text("""
        SELECT s.season_id, s.season_type::text AS season_type,
               t.abbreviation AS team,
               s.games_played, s.games_with_minutes, s.games_started,
               s.min_per_game,
               s.pts_per_game, s.reb_per_game, s.ast_per_game,
               s.pts_per_36, s.reb_per_36, s.ast_per_36,
               s.fgm, s.fga, s.fg_pct,
               s.fg3m, s.fg3a, s.fg3_pct, s.fg3m_per_game, s.fg3a_per_game,
               s.ftm, s.fta, s.ft_pct,
               s.stl, s.blk, s.tov,
               s.ts_pct, s.efg_pct, s.avg_game_score, s.plus_minus
        FROM mv_player_season s
        JOIN teams t ON t.team_id = s.team_id
        WHERE s.player_id = :pid
        ORDER BY s.season_id DESC, s.season_type, t.abbreviation
    """)
    return [dict(f) for f in session.execute(sql, {"pid": player_id}).mappings()]


def get_gamelog(
    session: Session,
    player_id: int,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> list[dict]:
    extra, params = _filtro_temporadas(seasons)
    sql = text(f"""
        SELECT r.game_id, r.game_date_local AS date, r.season_id,
               r.season_type::text AS season_type,
               tm.abbreviation AS team, opp.abbreviation AS opponent,
               r.is_home, r.is_neutral_site, r.won, r.rest_days, r.is_back_to_back,
               g.tipoff_utc, g.game_label, g.game_sublabel, r.seconds_played,
               r.pts, r.reb, r.ast, r.stl, r.blk, r.tov, r.plus_minus,
               r.ts_pct, r.usg_pct, r.game_score
        FROM mv_player_game_rates r
        JOIN games g   ON g.game_id  = r.game_id
        JOIN teams tm  ON tm.team_id = r.team_id
        JOIN teams opp ON opp.team_id = r.opponent_team_id
        WHERE r.player_id = :pid
          AND r.season_type::text = ANY(:types){extra}
        ORDER BY r.game_date_local, r.game_id
    """)
    filas = session.execute(
        sql, {"pid": player_id, "types": list(season_types), **params}
    ).mappings()

    salida = []
    for f in filas:
        d = dict(f)
        d["minutes"] = format_seconds(d.pop("seconds_played") or 0)
        salida.append(d)
    return salida


# =========================================================================
# Series para tendencias
# =========================================================================


def get_stat_series(
    session: Session,
    player_id: int,
    stat: Stat,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> tuple[list[float], list[dt.date]]:
    """Serie cronológica de una estadística, saltando los valores nulos.

    Los NULL se descartan en vez de sustituirse por cero: en una tasa, un
    partido de 0 minutos no vale cero, no vale nada. Meter ceros hundiría
    artificialmente cualquier pendiente.
    """
    col = STATS[stat].column
    extra, params = _filtro_temporadas(seasons)
    sql = text(f"""
        SELECT r.game_date_local AS fecha, r.{col} AS valor
        FROM mv_player_game_rates r
        WHERE r.player_id = :pid
          AND r.season_type::text = ANY(:types)
          AND r.{col} IS NOT NULL{extra}
        ORDER BY r.game_date_local, r.game_id
    """)
    filas = session.execute(
        sql, {"pid": player_id, "types": list(season_types), **params}
    ).all()
    return [float(f.valor) for f in filas], [f.fecha for f in filas]


# =========================================================================
# Splits
# =========================================================================

_DIMENSION_SQL: dict[Dimension, str] = {
    Dimension.DAY_OF_WEEK: "r.day_of_week::text",
    Dimension.HOME_AWAY: "CASE WHEN r.is_home THEN 'local' ELSE 'visitante' END",
    Dimension.REST: (
        "CASE WHEN r.rest_days IS NULL THEN 'sin dato' "
        "WHEN r.rest_days = 0 THEN '0 (back-to-back)' "
        "WHEN r.rest_days = 1 THEN '1 día' "
        "WHEN r.rest_days = 2 THEN '2 días' "
        "ELSE '3+ días' END"
    ),
    Dimension.OPPONENT: "opp.abbreviation",
    Dimension.MONTH: "r.month::text",
    Dimension.BACK_TO_BACK: (
        "CASE WHEN r.is_back_to_back THEN 'segundo en 2 días' ELSE 'con descanso' END"
    ),
    Dimension.SEASON: "r.season_id",
    Dimension.STARTER: "CASE WHEN r.started THEN 'titular' ELSE 'suplente' END",
}


def _grupos_por_cuarto(
    session: Session,
    player_id: int,
    stat: Stat,
    seasons: list[str] | None,
    season_types: tuple[str, ...],
) -> dict[str, list[float]]:
    """Valores del jugador agrupados por cuarto, uno por partido y cuarto.

    Cada observación es lo que hizo en ese cuarto de ese partido, que es
    exactamente la unidad que necesita `analyze_splits`: comparable entre sí
    (todos los cuartos duran 12 minutos) y con muestra de sobra — un titular
    acumula ~70 cuartos cuartos por temporada y ~350 en cinco.

    Solo hay fila cuando el jugador pisó la pista en ese cuarto. Rellenar con
    ceros los cuartos que no jugó hundiría la media de un suplente y diría que
    "anota poco en el primer cuarto" cuando lo que pasa es que no juega.
    """
    col = STATS[stat].column
    extra = " AND g.season_id = ANY(:seasons)" if seasons else ""
    params = {"seasons": seasons} if seasons else {}

    sql = text(f"""
        SELECT p.period AS nivel, p.{col} AS valor
        FROM player_period_stats p
        JOIN games g USING (game_id)
        WHERE p.player_id = :pid
          AND g.season_type::text = ANY(:types)
          AND p.{col} IS NOT NULL{extra}
    """)
    filas = session.execute(
        sql, {"pid": player_id, "types": list(season_types), **params}
    ).all()

    grupos: dict[str, list[float]] = defaultdict(list)
    for f in filas:
        grupos[_etiqueta_cuarto(int(f.nivel))].append(float(f.valor))

    # Orden natural del partido, no alfabético.
    return dict(sorted(grupos.items(), key=lambda kv: _orden_cuarto(kv[0])))


def _etiqueta_cuarto(period: int) -> str:
    """1 -> '1er cuarto'; 5 -> '1ª prórroga'.

    Las prórrogas se numeran desde 1 y no se llaman "periodo 5": nadie lee un
    partido así, y el número de periodo deja de significar nada para quien mira.
    """
    if period <= 4:
        return f"{period}{'er' if period == 1 else 'º'} cuarto"
    return f"{period - 4}ª prórroga"


def _orden_cuarto(etiqueta: str) -> int:
    n = int(etiqueta.split(maxsplit=1)[0].rstrip("erºª"))
    return n if "cuarto" in etiqueta else 4 + n


def get_split_groups(
    session: Session,
    player_id: int,
    stat: Stat,
    dimension: Dimension,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> dict[str, list[float]]:
    """Agrupa los valores de un jugador por los niveles de una dimensión."""
    # El cuarto tiene otra granularidad —jugador × partido × periodo— y por
    # tanto otra tabla, así que se desvía ANTES de resolver nada: en
    # `mv_player_game_rates` una fila ES un partido entero, y un partido no
    # tiene "cuarto", de modo que no hay expresión de dimensión que buscar.
    if dimension is Dimension.PERIOD:
        return _grupos_por_cuarto(session, player_id, stat, seasons, season_types)

    col = STATS[stat].column
    expr = _DIMENSION_SQL[dimension]
    extra, params = _filtro_temporadas(seasons)

    # Los partidos en sede neutral se excluyen SOLO del split local/visitante:
    # ahí no hay ventaja de campo, así que contarlos como local o como
    # visitante mete ruido en las dos direcciones. En el resto de dimensiones
    # son partidos perfectamente válidos.
    neutrales = (
        " AND NOT r.is_neutral_site" if dimension is Dimension.HOME_AWAY else ""
    )

    sql = text(f"""
        SELECT {expr} AS nivel, r.{col} AS valor
        FROM mv_player_game_rates r
        JOIN teams opp ON opp.team_id = r.opponent_team_id
        WHERE r.player_id = :pid
          AND r.season_type::text = ANY(:types)
          AND r.{col} IS NOT NULL{extra}{neutrales}
    """)
    filas = session.execute(
        sql, {"pid": player_id, "types": list(season_types), **params}
    ).all()

    grupos: dict[str, list[float]] = defaultdict(list)
    for f in filas:
        grupos[_etiquetar(dimension, f.nivel)].append(float(f.valor))

    return _ordenar(dimension, grupos)


def _etiquetar(dimension: Dimension, nivel) -> str:
    if nivel is None:
        return "sin dato"
    if dimension is Dimension.DAY_OF_WEEK:
        return DIAS.get(int(nivel), str(nivel))
    if dimension is Dimension.MONTH:
        return MESES.get(int(nivel), str(nivel))
    return str(nivel)


def _ordenar(dimension: Dimension, grupos: dict[str, list[float]]) -> dict[str, list[float]]:
    """Ordena los niveles de forma natural, no alfabética.

    Que los días salgan de lunes a domingo y los meses de octubre a junio no es
    cosmética: un eje desordenado hace que el ojo busque patrones donde no los
    hay, y evitar eso es justo el objetivo del proyecto.
    """
    if dimension is Dimension.DAY_OF_WEEK:
        orden = list(DIAS.values())
    elif dimension is Dimension.MONTH:
        # Orden del calendario NBA: arranca en octubre.
        meses = list(MESES.values())
        orden = meses[9:] + meses[:9]
    elif dimension is Dimension.REST:
        orden = ["0 (back-to-back)", "1 día", "2 días", "3+ días", "sin dato"]
    else:
        orden = sorted(grupos)

    return {k: grupos[k] for k in orden if k in grupos}


# =========================================================================
# Rankings
# =========================================================================


def get_all_player_series(
    session: Session,
    stat: Stat,
    min_games: int,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> dict[int, tuple[str, list[float]]]:
    """Serie de TODOS los jugadores con suficientes partidos, en una consulta.

    Se trae todo de golpe y se analiza en Python en vez de hacer una consulta
    por jugador: son ~600 jugadores × ~350 partidos, unas 200.000 filas, que
    caben de sobra en memoria y se recorren en menos de un segundo.
    """
    col = STATS[stat].column
    extra, params = _filtro_temporadas(seasons)
    sql = text(f"""
        SELECT r.player_id, p.full_name, r.{col} AS valor
        FROM mv_player_game_rates r
        JOIN players p USING (player_id)
        WHERE r.season_type::text = ANY(:types)
          AND r.{col} IS NOT NULL{extra}
        ORDER BY r.player_id, r.game_date_local, r.game_id
    """)
    filas = session.execute(sql, {"types": list(season_types), **params}).all()

    series: dict[int, tuple[str, list[float]]] = {}
    for f in filas:
        if f.player_id not in series:
            series[f.player_id] = (f.full_name, [])
        series[f.player_id][1].append(float(f.valor))

    return {pid: v for pid, v in series.items() if len(v[1]) >= min_games}


def get_recent_games(session: Session, player_id: int, limit: int = 5) -> list[dict]:
    """Los últimos partidos oficiales, de cualquier tipo.

    Incluye playoffs y play-in a propósito, no solo temporada regular: "sus
    últimos partidos" significa los últimos que jugó, y filtrar a regular
    escondería una eliminatoria entera.
    """
    sql = text("""
        SELECT r.game_id, r.game_date_local AS date, r.season_id,
               r.season_type::text AS season_type,
               g.game_label, g.game_sublabel,
               opp.team_id AS opponent_id, opp.abbreviation AS opponent,
               tm.abbreviation AS team,
               r.is_home, r.is_neutral_site, r.won,
               tgs.pts AS team_pts, tgs_opp.pts AS opp_pts,
               r.seconds_played, r.pts, r.reb, r.ast, r.stl, r.blk, r.tov,
               r.fgm, r.fga, r.fg3m, r.fg3a, r.ftm, r.fta,
               r.plus_minus, r.ts_pct, r.game_score
        FROM mv_player_game_rates r
        JOIN games g   ON g.game_id  = r.game_id
        JOIN teams tm  ON tm.team_id = r.team_id
        JOIN teams opp ON opp.team_id = r.opponent_team_id
        JOIN mv_team_game_rates tgs
             ON tgs.game_id = r.game_id AND tgs.team_id = r.team_id
        JOIN mv_team_game_rates tgs_opp
             ON tgs_opp.game_id = r.game_id AND tgs_opp.team_id = r.opponent_team_id
        WHERE r.player_id = :pid
        ORDER BY r.game_date_local DESC, r.game_id DESC
        LIMIT :limit
    """)
    filas = session.execute(sql, {"pid": player_id, "limit": limit}).mappings()

    salida = []
    for f in filas:
        d = dict(f)
        d["minutes"] = format_seconds(d.pop("seconds_played") or 0)
        salida.append(d)
    return salida


# Mínimo para entrar en el ranking de liga: **la regla oficial de la NBA**, que
# exige haber disputado el 70% de los partidos (58 de 82) para aparecer en las
# tablas de líderes por partido.
#
# Se adoptó tras comparar contra ESPN. El umbral anterior (20 partidos y 15
# minutos, heredado de `mv_league_season_baselines`) era mucho más permisivo y
# daba puestos distintos a los publicados: Dončić salía 30º en rebotes cuando
# todas las fuentes decían 22º. Con la regla oficial coincide exacto, igual que
# en puntos (1º) y asistencias (3º).
#
# LÍMITE CONOCIDO: para los PORCENTAJES la NBA no usa partidos sino mínimos de
# intentos (300 tiros de campo anotados para el FG%). Aquí se aplica el mismo
# umbral de partidos a todas las categorías, así que los puestos de FG% y TS%
# pueden diferir de los publicados. Los de puntos, rebotes, asistencias, robos
# y tapones sí coinciden.
GAMES_IN_SEASON = 82
RANK_MIN_GAMES = round(GAMES_IN_SEASON * 0.70)  # 58


def get_league_ranks(session: Session, player_id: int, season: str) -> dict | None:
    """Puesto del jugador en la liga, por estadística.

    Es el «1º, 22º, 3º» que ESPN pone junto a los promedios. Se calcula con
    funciones de ventana sobre `mv_player_season`, filtrando a jugadores
    cualificados.

    Un jugador traspasado tiene varias filas en esa vista (una por equipo), así
    que primero se recombinan sus totales: si no, cada mitad de su temporada
    competiría por separado y ninguna llegaría al mínimo de partidos.
    """
    sql = text("""
        WITH combinados AS (
            SELECT player_id,
                   SUM(games_played)   AS gp,
                   SUM(seconds_played) AS secs,
                   SUM(pts)::numeric / NULLIF(SUM(games_played), 0) AS ppg,
                   SUM(reb)::numeric / NULLIF(SUM(games_played), 0) AS rpg,
                   SUM(ast)::numeric / NULLIF(SUM(games_played), 0) AS apg,
                   SUM(stl)::numeric / NULLIF(SUM(games_played), 0) AS spg,
                   SUM(blk)::numeric / NULLIF(SUM(games_played), 0) AS bpg,
                   SUM(fgm)::numeric / NULLIF(SUM(fga), 0)          AS fg_pct,
                   SUM(pts) / NULLIF(2 * (SUM(fga) + 0.44 * SUM(fta)), 0) AS ts_pct
            FROM mv_player_season
            WHERE season_id = :season AND season_type = 'regular'
            GROUP BY player_id
        ),
        cualificados AS (
            SELECT * FROM combinados WHERE gp >= :min_games
        ),
        puestos AS (
            SELECT player_id, gp,
                   ppg, RANK() OVER (ORDER BY ppg DESC NULLS LAST) AS ppg_rank,
                   rpg, RANK() OVER (ORDER BY rpg DESC NULLS LAST) AS rpg_rank,
                   apg, RANK() OVER (ORDER BY apg DESC NULLS LAST) AS apg_rank,
                   spg, RANK() OVER (ORDER BY spg DESC NULLS LAST) AS spg_rank,
                   bpg, RANK() OVER (ORDER BY bpg DESC NULLS LAST) AS bpg_rank,
                   fg_pct, RANK() OVER (ORDER BY fg_pct DESC NULLS LAST) AS fg_pct_rank,
                   ts_pct, RANK() OVER (ORDER BY ts_pct DESC NULLS LAST) AS ts_pct_rank,
                   COUNT(*) OVER () AS qualified
            FROM cualificados
        )
        SELECT * FROM puestos WHERE player_id = :pid
    """)
    fila = session.execute(
        sql,
        {"pid": player_id, "season": season, "min_games": RANK_MIN_GAMES},
    ).mappings().first()
    return dict(fila) if fila else None


# =========================================================================
# Detalle de un partido
# =========================================================================


def get_game(session: Session, game_id: str) -> dict | None:
    """Cabecera del partido: fecha, tipo, marcador y contexto."""
    sql = text("""
        SELECT g.game_id, g.game_date_local AS date, g.season_id,
               g.season_type::text AS season_type,
               g.game_label, g.game_sublabel,
               g.tipoff_utc, g.ot_periods, g.is_neutral_site, g.attendance,
               g.arena_name,
               g.home_team_id, g.away_team_id, g.home_pts, g.away_pts
        FROM games g WHERE g.game_id = :gid
    """)
    fila = session.execute(sql, {"gid": game_id}).mappings().first()
    return dict(fila) if fila else None


def get_game_periods(session: Session, game_id: str) -> list[dict]:
    """Marcador por periodo de los dos equipos.

    Devuelve lista vacía si el partido todavía no tiene el resumen cargado.
    Vacío significa "no lo hemos descargado", no "no hubo cuartos": el
    frontend tiene que poder distinguirlo para no enseñar un marcador a cero.
    """
    sql = text("""
        SELECT team_id, period, points, is_overtime
        FROM game_period_scores
        WHERE game_id = :gid
        ORDER BY period, team_id
    """)
    return [dict(f) for f in session.execute(sql, {"gid": game_id}).mappings()]


def get_game_officials(session: Session, game_id: str) -> list[dict]:
    sql = text("""
        SELECT official_id, name, jersey_number
        FROM game_officials WHERE game_id = :gid ORDER BY name
    """)
    return [dict(f) for f in session.execute(sql, {"gid": game_id}).mappings()]


def get_game_team_stats(session: Session, game_id: str) -> list[dict]:
    """Box score de los dos equipos, tradicional y avanzado."""
    sql = text("""
        SELECT t.team_id, t.abbreviation, t.full_name, t.city, t.nickname,
               tgs.is_home, tgs.won, tgs.opponent_team_id,
               tgs.pts, tgs.fgm, tgs.fga, tgs.fg3m, tgs.fg3a, tgs.ftm, tgs.fta,
               tgs.oreb, tgs.dreb, tgs.reb, tgs.ast, tgs.stl, tgs.blk,
               tgs.tov, tgs.pf, tgs.plus_minus,
               tgs.possessions, tgs.pace,
               tgs.off_rating, tgs.def_rating, tgs.net_rating,
               tgs.ts_pct, tgs.efg_pct,
               tgs.rest_days, tgs.is_back_to_back,
               tgs.wins_before, tgs.losses_before,
               tgs.absent_minutes, tgs.absent_players
        FROM team_game_stats tgs
        JOIN teams t ON t.team_id = tgs.team_id
        WHERE tgs.game_id = :gid
        ORDER BY tgs.is_home DESC
    """)
    return [dict(f) for f in session.execute(sql, {"gid": game_id}).mappings()]


def get_game_player_periods(session: Session, game_id: str) -> dict[int, dict[int, int]]:
    """Puntos de cada jugador en cada periodo de un partido.

    Devuelve `{player_id: {period: puntos}}`. Se entrega aparte del box score y
    no como columnas fijas porque el número de periodos varía: fijar cuatro
    columnas obligaría a inventar un apaño el día de una prórroga, que es el
    6,5% de los partidos.

    Un jugador sin fila en un periodo no jugó ese periodo, y eso NO es lo mismo
    que anotar cero. La interfaz debe distinguirlo.
    """
    sql = text("""
        SELECT player_id, period, pts
        FROM player_period_stats
        WHERE game_id = :gid AND pts IS NOT NULL
        ORDER BY player_id, period
    """)
    por_jugador: dict[int, dict[int, int]] = defaultdict(dict)
    for f in session.execute(sql, {"gid": game_id}).mappings():
        por_jugador[f["player_id"]][f["period"]] = f["pts"]
    return dict(por_jugador)


def get_game_player_stats(session: Session, game_id: str) -> list[dict]:
    """Box score de todos los jugadores del partido, tradicional y avanzado.

    Ordenado por minutos descendente dentro de cada equipo: en una ficha de
    partido lo primero que se busca es quién jugó, no el orden alfabético.
    """
    sql = text("""
        SELECT pgs.player_id, p.full_name, p.jersey_number, p.position,
               pgs.team_id, pgs.seconds_played, pgs.started,
               pgs.pts, pgs.fgm, pgs.fga, pgs.fg3m, pgs.fg3a, pgs.ftm, pgs.fta,
               pgs.oreb, pgs.dreb, pgs.reb, pgs.ast, pgs.stl, pgs.blk,
               pgs.tov, pgs.pf, pgs.plus_minus,
               pga.ts_pct, pga.efg_pct, pga.usg_pct, pga.ast_pct, pga.reb_pct,
               pga.off_rating, pga.def_rating, pga.net_rating, pga.pie,
               r.game_score
        FROM player_game_stats pgs
        JOIN players p USING (player_id)
        LEFT JOIN player_game_advanced pga
               ON pga.game_id = pgs.game_id AND pga.player_id = pgs.player_id
        LEFT JOIN mv_player_game_rates r
               ON r.game_id = pgs.game_id AND r.player_id = pgs.player_id
        WHERE pgs.game_id = :gid
        ORDER BY pgs.team_id, pgs.seconds_played DESC
    """)
    filas = session.execute(sql, {"gid": game_id}).mappings()

    salida = []
    for f in filas:
        d = dict(f)
        d["minutes"] = format_seconds(d.pop("seconds_played") or 0)
        salida.append(d)
    return salida


def get_game_absences(session: Session, game_id: str) -> dict[int, list[dict]]:
    """Quién NO jugó, de los que sí solían jugar. Por equipo.

    Repite la ventana de `derive.sql` en vez de leerla de una tabla porque lo
    que hay guardado es el AGREGADO (minutos y cuántos), y aquí hacen falta los
    nombres. Se comprobó que los dos caminos dan lo mismo: para el partido con
    más ausencias, 9 y 16 jugadores por equipo en ambos.

    Se restringe a la temporada y a los dos equipos del partido, así que baja de
    los 3,2 M de filas a unos miles: ~20 ms.
    """
    sql = text("""
        WITH partido AS (
            SELECT game_id, season_id, game_date_local AS fecha,
                   home_team_id, away_team_id
            FROM games WHERE game_id = :gid
        ),
        ap AS (
            SELECT pgs.player_id, pgs.team_id, g.game_date_local AS f,
                   pgs.seconds_played
            FROM player_game_stats pgs
            JOIN games g ON g.game_id = pgs.game_id
            WHERE g.season_id = (SELECT season_id FROM partido)
              -- Aparición, no fila: desde la fase 23 la tabla guarda también a
              -- quien no jugó, con su motivo.
              AND pgs.dnp_reason IS NULL
              AND pgs.team_id IN (
                  SELECT home_team_id FROM partido
                  UNION SELECT away_team_id FROM partido)
        ),
        pf AS (
            SELECT player_id, team_id, MIN(f) AS desde, MAX(f) AS hasta,
                   COUNT(*) AS pj, AVG(seconds_played) / 60.0 AS mh
            FROM ap GROUP BY 1, 2
        ),
        ul AS (
            SELECT pgs.player_id, MAX(g.game_date_local) AS u
            FROM player_game_stats pgs
            JOIN games g ON g.game_id = pgs.game_id
            WHERE g.season_id = (SELECT season_id FROM partido)
              AND pgs.dnp_reason IS NULL
            GROUP BY 1
        ),
        fi AS (
            SELECT MAX(game_date_local) AS fin FROM games
            WHERE season_id = (SELECT season_id FROM partido)
        )
        SELECT pf.team_id, pf.player_id, p.full_name,
               ROUND(pf.mh::numeric, 1) AS usual_minutes,
               -- POR QUÉ faltó, cuando la fuente lo dice. Antes solo se podía
               -- deducir el hueco; ahora se distingue una lesión de un
               -- descarte técnico.
               (SELECT x.dnp_reason FROM player_game_stats x
                 WHERE x.game_id = pa.game_id AND x.player_id = pf.player_id) AS reason
        FROM pf
        JOIN ul USING (player_id)
        CROSS JOIN fi
        CROSS JOIN partido pa
        JOIN players p ON p.player_id = pf.player_id
        WHERE pf.mh >= 10
          AND pa.fecha BETWEEN pf.desde
              AND (CASE WHEN pf.hasta = ul.u AND pf.pj >= 10 THEN fi.fin ELSE pf.hasta END)
          AND NOT EXISTS (
              SELECT 1 FROM player_game_stats x
              WHERE x.game_id = pa.game_id AND x.player_id = pf.player_id
                AND x.dnp_reason IS NULL)
        ORDER BY pf.team_id, usual_minutes DESC
    """)
    salida: dict[int, list[dict]] = {}
    for f in session.execute(sql, {"gid": game_id}).mappings():
        salida.setdefault(f["team_id"], []).append(
            {
                "player_id": f["player_id"],
                "full_name": f["full_name"],
                "usual_minutes": float(f["usual_minutes"]),
                "reason": f["reason"],
            }
        )
    return salida


def get_game_expected_inputs(session: Session, game_id: str) -> dict | None:
    """Box scores del partido y totales de temporada de cada equipo SIN él.

    LEAVE-ONE-OUT, y no es un detalle. Si la norma de tiro de un equipo incluye
    el partido que se está explicando, el partido se explica en parte a sí mismo
    y la "suerte" sale sesgada hacia cero. Es la misma condición con la que se
    verificó el motor sobre los 6.150 partidos (residuo 0,000000000000), así que
    el endpoint tiene que respetarla o estaría midiendo otra cosa.
    """
    cab = (
        session.execute(
            text("""
                SELECT g.game_id, g.season_id, g.season_type::text AS season_type,
                       g.home_team_id, g.away_team_id
                FROM games g WHERE g.game_id = :gid
            """),
            {"gid": game_id},
        )
        .mappings()
        .first()
    )
    if not cab:
        return None

    partido = {
        f["team_id"]: dict(f)
        for f in session.execute(
            text("""
                SELECT tgs.team_id, t.abbreviation, t.full_name, tgs.is_home,
                       tgs.pts, tgs.fgm, tgs.fga, tgs.fg3m, tgs.fg3a,
                       tgs.ftm, tgs.fta, tgs.oreb, tgs.dreb, tgs.tov
                FROM team_game_stats tgs
                JOIN teams t ON t.team_id = tgs.team_id
                WHERE tgs.game_id = :gid
            """),
            {"gid": game_id},
        ).mappings()
    }
    if len(partido) != 2:
        return None

    # Totales de la temporada MENOS este partido. El `FILTER` es lo que lo
    # consigue, y es exacto: no aproxima restando promedios.
    SIN_ESTE = """
        COUNT(*)      FILTER (WHERE tgs.game_id <> :gid) AS n_games,
        SUM(tgs.fgm)  FILTER (WHERE tgs.game_id <> :gid) AS fgm,
        SUM(tgs.fga)  FILTER (WHERE tgs.game_id <> :gid) AS fga,
        SUM(tgs.fg3m) FILTER (WHERE tgs.game_id <> :gid) AS fg3m,
        SUM(tgs.fg3a) FILTER (WHERE tgs.game_id <> :gid) AS fg3a,
        SUM(tgs.ftm)  FILTER (WHERE tgs.game_id <> :gid) AS ftm,
        SUM(tgs.fta)  FILTER (WHERE tgs.game_id <> :gid) AS fta
    """
    args = {
        "gid": game_id,
        "season": cab["season_id"],
        "tipo": cab["season_type"],
        "local": cab["home_team_id"],
        "visitante": cab["away_team_id"],
    }
    temporada = {
        f["team_id"]: dict(f)
        for f in session.execute(
            text(f"""
                SELECT tgs.team_id, {SIN_ESTE}
                FROM team_game_stats tgs
                JOIN games g2 ON g2.game_id = tgs.game_id
                WHERE g2.season_id = :season AND g2.season_type = :tipo
                  AND tgs.team_id IN (:local, :visitante)
                GROUP BY tgs.team_id
            """),
            args,
        ).mappings()
    }
    liga = (
        session.execute(
            text(f"""
                SELECT {SIN_ESTE}
                FROM team_game_stats tgs
                JOIN games g2 ON g2.game_id = tgs.game_id
                WHERE g2.season_id = :season AND g2.season_type = :tipo
            """),
            args,
        )
        .mappings()
        .one()
    )

    return {
        "season_id": cab["season_id"],
        "home_team_id": cab["home_team_id"],
        "away_team_id": cab["away_team_id"],
        "boxes": partido,
        "season_totals": temporada,
        "league": dict(liga),
    }


def get_team_game_series(session: Session, season: str | None = None) -> list[dict]:
    """Una fila por equipo-partido con los componentes que se quieren estabilizar.

    Lo concedido sale de la fila del RIVAL en el mismo partido, no de columnas
    `opp_*`: así el volumen concedido (cuántos triples le dejas tirar) y el
    acierto concedido (si entran) quedan separados, que es justamente lo que el
    motor de resultado esperado necesita distinguir.
    """
    sql = text("""
        SELECT t.team_id, t.season_id,
               t.fga, t.fgm, t.fg3a, t.fg3m, t.fta, t.ftm,
               t.oreb, t.dreb, t.tov, t.pace,
               t.pts_paint, t.pts_fastbreak, t.pts_off_turnovers, t.pts_2nd_chance,
               o.fga AS opp_fga, o.fgm AS opp_fgm, o.fg3a AS opp_fg3a,
               o.fg3m AS opp_fg3m, o.dreb AS opp_dreb
        FROM mv_team_game_rates t
        JOIN mv_team_game_rates o
          ON o.game_id = t.game_id AND o.team_id = t.opponent_team_id
        WHERE t.season_type = 'regular'
          -- El cast es necesario: sin él Postgres no puede inferir el tipo
          -- del parámetro dentro de un `IS NULL`.
          AND (CAST(:season AS text) IS NULL OR t.season_id = CAST(:season AS text))
    """)
    return [dict(f) for f in session.execute(sql, {"season": season}).mappings()]


# Estadísticas sobre las que se puede pedir una curva de edad. Todas son TASAS:
# una curva sobre totales mediría sobre todo cuántos minutos le dan a uno, que
# es consecuencia de envejecer y no envejecimiento.
COLUMNAS_EDAD: dict[str, str] = {
    "pts_per_36": "Puntos por 36 min",
    "reb_per_36": "Rebotes por 36 min",
    "ast_per_36": "Asistencias por 36 min",
    "ts_pct": "True Shooting %",
    "efg_pct": "Efective FG %",
    "avg_game_score": "Game Score medio",
    "min_per_game": "Minutos por partido",
}


def get_age_observations(
    session: Session, column: str, *, min_games: int = 30, min_minutes: float = 15.0
) -> list[tuple[int, int, float]]:
    """Tríos `(player_id, edad, valor)`, uno por jugador-temporada.

    Los mínimos no son decorativos: sin ellos entran temporadas de 4 partidos
    cuyo valor es ruido, y el método delta las trataría como un cambio real de
    un año para otro.

    La edad se redondea a años enteros. `avg_age` es la media de la temporada,
    así que un jugador que cumple años en enero aparece con una edad
    intermedia; redondear es lo que permite emparejar temporadas consecutivas.
    """
    if column not in COLUMNAS_EDAD:
        raise ValueError(f"columna no permitida: {column}")

    filas = session.execute(
        text(f"""
            SELECT player_id, ROUND(avg_age)::int AS edad, {column}::float AS valor
            FROM mv_player_season
            WHERE season_type = 'regular'
              AND games_played >= :pj
              AND min_per_game >= :min
              AND avg_age IS NOT NULL
              AND {column} IS NOT NULL
        """),
        {"pj": min_games, "min": min_minutes},
    ).all()
    return [(int(f.player_id), int(f.edad), float(f.valor)) for f in filas]
