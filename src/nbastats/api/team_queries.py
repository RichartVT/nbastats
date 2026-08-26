"""Consultas de equipo. Espejo de `queries.py`, sobre `mv_team_game_rates`.

Se separa en su propio módulo y no se mezcla con las de jugador porque el
vocabulario cambia: los equipos se normalizan **per-100 posesiones**, no
per-36 minutos. Un equipo siempre juega 48 minutos; lo que varía entre equipos
y entre épocas es cuántas posesiones caben ahí.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from nbastats.api.catalog import DIAS, MESES, Dimension

_TIPOS_DEFECTO = ("regular",)

# Estadísticas de equipo consultables. Mismo patrón que `catalog.STATS`: el
# nombre de columna nunca viene del cliente, se resuelve contra este mapa.
TEAM_STATS: dict[str, tuple[str, str]] = {
    "pts_per_100": ("pts_per_100", "Puntos por 100 posesiones"),
    "reb_per_100": ("reb_per_100", "Rebotes por 100 posesiones"),
    "ast_per_100": ("ast_per_100", "Asistencias por 100 posesiones"),
    "tov_per_100": ("tov_per_100", "Pérdidas por 100 posesiones"),
    "fg3a_per_100": ("fg3a_per_100", "Triples intentados por 100"),
    "off_rating": ("off_rating", "Rating ofensivo"),
    "def_rating": ("def_rating", "Rating defensivo"),
    "net_rating": ("net_rating", "Rating neto"),
    "pace": ("pace", "Ritmo"),
    "ts_pct": ("ts_pct", "True Shooting %"),
    "efg_pct": ("efg_pct", "Efective FG %"),
    "point_diff": ("point_diff", "Diferencial de puntos"),
    "pts": ("pts", "Puntos"),
}


def _filtro_temporadas(seasons: list[str] | None, alias: str = "r") -> tuple[str, dict]:
    if not seasons:
        return "", {}
    return f" AND {alias}.season_id = ANY(:seasons)", {"seasons": seasons}


# =========================================================================
# Ficha y listado
# =========================================================================


def list_teams(session: Session, season: str | None = None) -> list[dict]:
    """Los 30 equipos con su récord en la temporada indicada."""
    sql = text("""
        SELECT t.team_id, t.abbreviation, t.full_name, t.city, t.nickname,
               t.conference, t.division, t.arena,
               s.wins, s.losses, s.win_pct, s.playoff_rank, s.diff_points_pg,
               s.home_record, s.road_record
        FROM teams t
        LEFT JOIN team_standings s
               ON s.team_id = t.team_id
              AND s.season_id = COALESCE(
                    :season, (SELECT MAX(season_id) FROM team_standings))
        ORDER BY t.full_name
    """)
    return [dict(f) for f in session.execute(sql, {"season": season}).mappings()]


def get_team(session: Session, team_id: int, season: str | None = None) -> dict | None:
    sql = text("""
        SELECT t.*,
               s.wins, s.losses, s.win_pct, s.playoff_rank,
               s.conference_record, s.division_record, s.home_record, s.road_record,
               s.last_10, s.current_streak, s.games_back,
               s.points_pg, s.opp_points_pg, s.diff_points_pg,
               s.season_id AS standings_season
        FROM teams t
        LEFT JOIN team_standings s
               ON s.team_id = t.team_id
              AND s.season_id = COALESCE(
                    :season, (SELECT MAX(season_id) FROM team_standings))
        WHERE t.team_id = :tid
    """)
    fila = session.execute(sql, {"tid": team_id, "season": season}).mappings().first()
    return dict(fila) if fila else None


def get_roster(session: Session, team_id: int, season: str | None = None) -> list[dict]:
    """Plantilla de una temporada, ordenada por minutos jugados.

    Se ordena por minutos y no por dorsal porque lo primero que se busca en una
    plantilla es quién juega, no quién lleva el número más bajo.
    """
    sql = text("""
        SELECT r.player_id, p.full_name, r.jersey_number, r.position, r.age,
               r.how_acquired, p.height_cm, p.weight_kg, p.roster_status,
               p.season_experience,
               COALESCE(agg.games, 0)   AS games,
               agg.min_per_game, agg.pts_per_game, agg.reb_per_game, agg.ast_per_game
        FROM team_season_rosters r
        JOIN players p USING (player_id)
        LEFT JOIN (
            SELECT player_id, team_id, season_id,
                   SUM(games_played) AS games,
                   AVG(min_per_game) AS min_per_game,
                   AVG(pts_per_game) AS pts_per_game,
                   AVG(reb_per_game) AS reb_per_game,
                   AVG(ast_per_game) AS ast_per_game
            FROM mv_player_season
            WHERE season_type = 'regular'
            GROUP BY player_id, team_id, season_id
        ) agg ON agg.player_id = r.player_id
             AND agg.team_id  = r.team_id
             AND agg.season_id = r.season_id
        WHERE r.team_id = :tid
          AND r.season_id = COALESCE(
                :season, (SELECT MAX(season_id) FROM team_season_rosters))
        ORDER BY agg.min_per_game DESC NULLS LAST, p.full_name
    """)
    return [dict(f) for f in session.execute(sql, {"tid": team_id, "season": season}).mappings()]


def get_team_games(
    session: Session,
    team_id: int,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = ("regular", "playin", "playoffs"),
    limit: int | None = None,
) -> list[dict]:
    """Historial de partidos de un equipo, del más reciente al más antiguo."""
    extra, params = _filtro_temporadas(seasons)
    tope = f" LIMIT {int(limit)}" if limit else ""
    sql = text(f"""
        SELECT r.game_id, r.game_date_local AS date, r.season_id,
               r.season_type::text AS season_type,
               r.game_label, r.game_sublabel,
               opp.team_id AS opponent_id, opp.abbreviation AS opponent,
               r.is_home, r.is_neutral_site, r.won,
               r.rest_days, r.is_back_to_back,
               r.pts, r.opp_pts, r.point_diff,
               r.reb, r.ast, r.tov,
               r.off_rating, r.def_rating, r.pace, r.ts_pct
        FROM mv_team_game_rates r
        JOIN teams opp ON opp.team_id = r.opponent_team_id
        WHERE r.team_id = :tid
          AND r.season_type::text = ANY(:types){extra}
        ORDER BY r.game_date_local DESC, r.game_id DESC{tope}
    """)
    filas = session.execute(
        sql, {"tid": team_id, "types": list(season_types), **params}
    ).mappings()
    return [dict(f) for f in filas]


# =========================================================================
# Clasificación
# =========================================================================


def get_standings(session: Session, season: str | None = None) -> list[dict]:
    sql = text("""
        SELECT s.*, t.abbreviation, t.full_name, t.city, t.nickname
        FROM team_standings s
        JOIN teams t USING (team_id)
        WHERE s.season_id = COALESCE(
                :season, (SELECT MAX(season_id) FROM team_standings))
        ORDER BY s.conference, s.playoff_rank
    """)
    return [dict(f) for f in session.execute(sql, {"season": season}).mappings()]


# =========================================================================
# Enfrentamientos directos
# =========================================================================


def get_head_to_head(
    session: Session,
    team_a: int,
    team_b: int,
    seasons: list[str] | None = None,
) -> list[dict]:
    """Partidos entre dos equipos, desde la perspectiva del primero."""
    extra, params = _filtro_temporadas(seasons)
    sql = text(f"""
        SELECT r.game_id, r.game_date_local AS date, r.season_id,
               r.season_type::text AS season_type,
               r.game_label, r.game_sublabel,
               -- El rival es siempre :b, pero se seleccionan igualmente sus
               -- datos: así la fila tiene la misma forma que la de
               -- get_team_games() y ambas alimentan el mismo esquema.
               opp.team_id AS opponent_id, opp.abbreviation AS opponent,
               r.is_home, r.is_neutral_site, r.won,
               r.rest_days, r.is_back_to_back,
               r.pts, r.opp_pts, r.point_diff,
               r.reb, r.ast, r.tov,
               r.off_rating, r.def_rating, r.pace, r.ts_pct
        FROM mv_team_game_rates r
        JOIN teams opp ON opp.team_id = r.opponent_team_id
        WHERE r.team_id = :a AND r.opponent_team_id = :b{extra}
        ORDER BY r.game_date_local DESC
    """)
    filas = session.execute(sql, {"a": team_a, "b": team_b, **params}).mappings()
    return [dict(f) for f in filas]


# =========================================================================
# Series y splits (alimentan analyze_trend / analyze_splits sin cambios)
# =========================================================================


def get_team_series(
    session: Session,
    team_id: int,
    stat: str,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> tuple[list[float], list]:
    col = TEAM_STATS[stat][0]
    extra, params = _filtro_temporadas(seasons)
    sql = text(f"""
        SELECT r.game_date_local AS fecha, r.{col} AS valor
        FROM mv_team_game_rates r
        WHERE r.team_id = :tid
          AND r.season_type::text = ANY(:types)
          AND r.{col} IS NOT NULL{extra}
        ORDER BY r.game_date_local, r.game_id
    """)
    filas = session.execute(
        sql, {"tid": team_id, "types": list(season_types), **params}
    ).all()
    return [float(f.valor) for f in filas], [f.fecha for f in filas]


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


def get_team_split_groups(
    session: Session,
    team_id: int,
    stat: str,
    dimension: Dimension,
    seasons: list[str] | None = None,
    season_types: tuple[str, ...] = _TIPOS_DEFECTO,
) -> dict[str, list[float]]:
    col = TEAM_STATS[stat][0]
    expr = _DIMENSION_SQL[dimension]
    extra, params = _filtro_temporadas(seasons)
    # Igual que en jugadores: los partidos en sede neutral solo se excluyen del
    # split local/visitante, donde falsearían las dos ramas a la vez.
    neutrales = " AND NOT r.is_neutral_site" if dimension is Dimension.HOME_AWAY else ""

    sql = text(f"""
        SELECT {expr} AS nivel, r.{col} AS valor
        FROM mv_team_game_rates r
        JOIN teams opp ON opp.team_id = r.opponent_team_id
        WHERE r.team_id = :tid
          AND r.season_type::text = ANY(:types)
          AND r.{col} IS NOT NULL{extra}{neutrales}
    """)
    filas = session.execute(
        sql, {"tid": team_id, "types": list(season_types), **params}
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
    if dimension is Dimension.DAY_OF_WEEK:
        orden = list(DIAS.values())
    elif dimension is Dimension.MONTH:
        meses = list(MESES.values())
        orden = meses[9:] + meses[:9]
    elif dimension is Dimension.REST:
        orden = ["0 (back-to-back)", "1 día", "2 días", "3+ días", "sin dato"]
    else:
        orden = sorted(grupos)
    return {k: grupos[k] for k in orden if k in grupos}
