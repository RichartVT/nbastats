"""Quién es dueño de cada columna, y que el upsert lo respete.

EL FALLO QUE ESTOS TESTS FIJAN. `upsert()` actualizaba TODAS las columnas que
no fueran clave, y `EXCLUDED` vale NULL en las que no viajan en el INSERT. Como
`daily` recarga la temporada en curso entera cada noche, cada pasada borraba lo
que escribe otra ingesta: la titularidad (starters.py), la asistencia y el
pabellón (summaries.py), la ficha de franquicia (teams.py) y las cuatro
derivadas de derive.sql.

No se veía porque la columna nunca llegaba a estar *mal*: estaba vacía. Y
`games_started` a 0 o un split que mete a los cinco titulares en 'suplente'
—`CASE WHEN NULL` cae al ELSE— son respuestas plausibles.

No tocan la red ni la base: compilan la sentencia y miran qué columnas lleva.
"""

from __future__ import annotations

import inspect

from sqlalchemy.dialects import postgresql

from nbastats.db.models import PlayerGameStats, Season
from nbastats.ingest.bulk import (
    _build_games,
    _build_player_stats,
    _build_team_stats,
    upsert,
)


class _SesionFalsa:
    """Captura la sentencia en vez de ejecutarla."""

    def __init__(self) -> None:
        self.sentencias: list = []

    def execute(self, stmt) -> None:
        self.sentencias.append(stmt)


def _sql(sesion: _SesionFalsa) -> str:
    return str(sesion.sentencias[0].compile(dialect=postgresql.dialect()))


def _set_clause(sql: str) -> str:
    _, _, cola = sql.partition("DO UPDATE SET")
    return cola


# ---------------------------------------------------------------- upsert


def test_upsert_no_actualiza_columnas_ausentes_de_las_filas():
    sesion = _SesionFalsa()
    upsert(
        sesion,
        PlayerGameStats,
        [{"game_id": "0022400001", "player_id": 1, "team_id": 2, "pts": 30}],
        keys=["game_id", "player_id"],
    )
    sql = _sql(sesion)

    # `started` y `dnp_reason` son de starters.py: no aparecen ni en el INSERT
    # ni en el SET, así que una recarga no las toca.
    assert "started" not in sql
    assert "dnp_reason" not in sql
    # Lo que sí viaja sí se actualiza: la fuente es autoritativa para lo suyo.
    assert "pts" in _set_clause(sql)
    assert "team_id" in _set_clause(sql)


def test_upsert_no_mete_en_el_set_la_clave():
    sesion = _SesionFalsa()
    upsert(
        sesion,
        PlayerGameStats,
        [{"game_id": "0022400001", "player_id": 1, "pts": 30}],
        keys=["game_id", "player_id"],
    )
    assert "player_id" not in _set_clause(_sql(sesion))


def test_upsert_sin_nada_que_actualizar_no_genera_un_set_vacio():
    """Un `SET` vacío es un error de sintaxis en Postgres."""
    sesion = _SesionFalsa()
    upsert(sesion, Season, [{"season_id": "2024-25"}], keys=["season_id"])
    sql = _sql(sesion)
    assert "DO NOTHING" in sql
    assert "DO UPDATE" not in sql


# ------------------------------------------------- dueños de cada columna

GAME_LOG = [
    {
        "GAME_ID": "0022400001",
        "TEAM_ID": 1610612747,
        "MATCHUP": "LAL vs. BOS",
        "GAME_DATE": "2025-01-11T00:00:00",
        "WL": "W",
        "MIN": 240,
        "PTS": 110,
    },
    {
        "GAME_ID": "0022400001",
        "TEAM_ID": 1610612738,
        "MATCHUP": "BOS @ LAL",
        "GAME_DATE": "2025-01-11T00:00:00",
        "WL": "L",
        "MIN": 240,
        "PTS": 104,
    },
]


def test_build_games_no_pisa_lo_que_escriben_enrich_y_summaries():
    juegos, _ = _build_games(GAME_LOG, [], client=None)
    assert len(juegos) == 1
    claves = set(juegos[0])
    # enrich.py: hora de inicio y etiquetas (NBA Cup, París...).
    assert "tipoff_utc" not in claves
    assert "game_label" not in claves
    assert "game_sublabel" not in claves
    # summaries.py: asistencia y pabellón.
    assert "attendance" not in claves
    assert "arena_name" not in claves


def test_build_team_stats_no_pisa_las_derivadas():
    _, rivales = _build_games(GAME_LOG, [], client=None)
    filas = _build_team_stats(GAME_LOG, [], rivales, {"0022400001": 1610612747})
    assert filas
    claves = set(filas[0])
    for derivada in (
        "rest_days",
        "is_back_to_back",
        "wins_before",
        "losses_before",
        "absent_minutes",
        "absent_players",
    ):
        assert derivada not in claves, derivada


def test_build_player_stats_no_pisa_la_titularidad():
    filas = _build_player_stats(
        [
            {
                "GAME_ID": "0022400001",
                "PLAYER_ID": 2544,
                "TEAM_ID": 1610612747,
                "MIN_SEC": "35:12",
                "PTS": 28,
            }
        ],
        {"0022400001"},
    )
    assert len(filas) == 1
    assert "started" not in filas[0]
    assert "dnp_reason" not in filas[0]
    # Y lo que sí es suyo sigue viajando.
    assert filas[0]["pts"] == 28


# ------------------------------------------------------------- cableado


def test_daily_reingesta_la_titularidad():
    """La ingesta existía y no la llamaba nadie: 0 referencias fuera del módulo.

    Sin esta línea el arreglo del upsert no basta, porque `ingest_seasons`
    inserta a los que jugaron SIN `started`, y esas filas nuevas nacen sin
    informar aunque ya no se borren las viejas.
    """
    from nbastats.cli import daily

    fuente = inspect.getsource(daily)
    assert "ingest_starters" in fuente


def test_existe_el_comando_ingest_starters():
    from nbastats.cli import app

    nombres = {c.name for c in app.registered_commands}
    assert "ingest-starters" in nombres
