"""Consultas a la base. Todo lee de las vistas materializadas.

Los nombres de columna se resuelven SIEMPRE contra `catalog.STATS`, nunca desde
texto del cliente. Es lo que permite construir el SQL con f-strings sin abrir un
hueco de inyección: el único camino desde la petición hasta la consulta pasa por
un enum validado por FastAPI.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from nbastats.api.catalog import DIAS, MESES, STATS, Dimension, Stat
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


def search_players(session: Session, query: str, limit: int = 25) -> list[dict]:
    sql = text("""
        SELECT p.player_id, p.full_name, p.position, p.birthdate,
               MIN(r.season_id) AS primera, MAX(r.season_id) AS ultima,
               SUM(CASE WHEN r.season_type='regular' THEN 1 ELSE 0 END) AS partidos
        FROM players p
        JOIN mv_player_game_rates r USING (player_id)
        -- immutable_unaccent() hace que "Jokic" encuentre a "Nikola Jokić" y
        -- "Doncic" a "Dončić". Nadie teclea los diacríticos al buscar.
        WHERE (:q = '' OR lower(immutable_unaccent(p.full_name))
                          LIKE lower(immutable_unaccent(:like)))
        GROUP BY p.player_id, p.full_name, p.position, p.birthdate
        ORDER BY partidos DESC, p.full_name
        LIMIT :limit
    """)
    filas = session.execute(
        sql, {"q": query, "like": f"%{query}%", "limit": limit}
    ).mappings().all()
    return [dict(f) for f in filas]


def get_player(session: Session, player_id: int) -> dict | None:
    sql = text("""
        SELECT p.*,
               ARRAY_AGG(DISTINCT r.season_id ORDER BY r.season_id) AS seasons,
               ARRAY_AGG(DISTINCT t.abbreviation)                   AS teams
        FROM players p
        LEFT JOIN mv_player_game_rates r USING (player_id)
        LEFT JOIN teams t ON t.team_id = r.team_id
        WHERE p.player_id = :pid
        GROUP BY p.player_id
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
               s.games_played, s.games_with_minutes, s.min_per_game,
               s.pts_per_game, s.reb_per_game, s.ast_per_game,
               s.pts_per_36, s.reb_per_36, s.ast_per_36,
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
               g.tipoff_utc, r.seconds_played,
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
}


def get_split_groups(
    session: Session,
    player_id: int,
    stat: Stat,
    dimension: Dimension,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> dict[str, list[float]]:
    """Agrupa los valores de un jugador por los niveles de una dimensión."""
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
