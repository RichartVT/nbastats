"""Ingesta de datos de equipo: ficha, plantillas y clasificación.

Tres piezas, todas baratas:

- **Ficha** (`TeamDetails`): 30 peticiones. Estadio, capacidad, propietario,
  director general, entrenador y año de fundación.
- **Plantillas** (`CommonTeamRoster`): 30 × temporada. Se guardan todas las
  temporadas, no solo la actual: sin eso, mirar a los Nuggets de 2022-23
  mostraría la plantilla de 2025-26, que es justo lo contrario de lo que sirve
  para analizar una temporada pasada.
- **Clasificación** (`LeagueStandingsV3`): 1 petición por temporada, con
  `PlayoffRank` ya resuelto y los desempates oficiales aplicados.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from nbastats.db.models import IngestLog, Player, Team, TeamSeasonRoster, TeamStanding
from nbastats.db.session import session_scope
from nbastats.ingest.bulk import upsert
from nbastats.ingest.nba_client import NBAClient

logger = logging.getLogger(__name__)


def _int_or_none(value: Any) -> int | None:
    if value in (None, "", " "):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _num_or_none(value: Any) -> float | None:
    if value in (None, "", " "):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return None if n != n else n


def _txt(value: Any, limite: int) -> str | None:
    """Texto recortado al ancho de la columna.

    La fuente no promete longitudes: el propietario de un equipo puede ser una
    lista de nombres ("Mark Walter & Jeanie Buss") y crecer sin aviso. Recortar
    aquí evita que un cambio en la NBA reviente la ingesta entera por un campo
    decorativo.
    """
    if value in (None, "", " "):
        return None
    texto = str(value).strip()
    return texto[:limite] if texto else None


# =========================================================================
# Ficha de la franquicia
# =========================================================================


def ingest_team_details(client: NBAClient | None = None) -> int:
    """Rellena estadio, entrenador y demás en `teams` (30 peticiones)."""
    client = client or NBAClient()

    filas = []
    for estatico in NBAClient.static_teams():
        team_id = estatico["id"]
        try:
            bloques = client.team_details(team_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TeamDetails de %s falló: %s", estatico["abbreviation"], exc)
            continue

        fondo = (bloques.get("TeamBackground") or [{}])[0]
        filas.append(
            {
                "team_id": team_id,
                "abbreviation": estatico["abbreviation"],
                "full_name": estatico["full_name"],
                "city": estatico.get("city"),
                "nickname": estatico.get("nickname"),
                "arena": _txt(fondo.get("ARENA"), 80),
                "arena_capacity": _int_or_none(fondo.get("ARENACAPACITY")),
                "owner": _txt(fondo.get("OWNER"), 120),
                "general_manager": _txt(fondo.get("GENERALMANAGER"), 80),
                "head_coach": _txt(fondo.get("HEADCOACH"), 80),
                "year_founded": _int_or_none(fondo.get("YEARFOUNDED")),
            }
        )

    with session_scope() as session:
        # Se listan las columnas a mano en vez de dejar que el UPSERT genérico
        # actualice todas: `arena_timezone`, `conference` y `division` no vienen
        # de este endpoint y un UPSERT completo las pondría a NULL.
        escritas = _upsert_teams(session, filas)

    logger.info("Fichas de equipo: %d actualizadas", escritas)
    return escritas


def _upsert_teams(session, filas: list[dict]) -> int:  # noqa: ANN001
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not filas:
        return 0
    actualizables = [c for c in filas[0] if c != "team_id"]
    stmt = pg_insert(Team).values(filas)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["team_id"],
            set_={c: stmt.excluded[c] for c in actualizables},
        )
    )
    return len(filas)


# =========================================================================
# Plantillas
# =========================================================================


def ingest_rosters(
    seasons: list[str], client: NBAClient | None = None
) -> dict[str, int]:
    """Plantillas de todos los equipos en las temporadas dadas."""
    client = client or NBAClient()
    equipos = NBAClient.static_teams()

    total = omitidos = 0
    for season in seasons:
        filas: list[dict] = []
        for equipo in equipos:
            try:
                bloques = client.team_roster(equipo["id"], season)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Plantilla de %s %s falló: %s", equipo["abbreviation"], season, exc
                )
                continue

            for jugador in bloques.get("CommonTeamRoster", []):
                player_id = _int_or_none(jugador.get("PLAYER_ID"))
                if player_id is None:
                    continue
                filas.append(
                    {
                        "season_id": season,
                        "team_id": equipo["id"],
                        "player_id": player_id,
                        "jersey_number": _txt(jugador.get("NUM"), 4),
                        "position": _txt(jugador.get("POSITION"), 20),
                        "age": _num_or_none(jugador.get("AGE")),
                        "how_acquired": _txt(jugador.get("HOW_ACQUIRED"), 120),
                    }
                )

        # Las plantillas incluyen jugadores que nunca llegaron a disputar un
        # partido (dos vías, contratos de 10 días que no debutaron), y esos no
        # están en `players`. Se descartan en vez de inventar filas de jugador:
        # una plantilla es un dato de contexto, no una fuente de jugadores.
        filas, descartados = _solo_jugadores_conocidos(filas)
        omitidos += descartados

        with session_scope() as session:
            total += upsert(
                session,
                TeamSeasonRoster,
                filas,
                keys=["season_id", "team_id", "player_id"],
            )
        logger.info("Plantillas %s: %d jugadores", season, len(filas))

    if omitidos:
        logger.info(
            "%d fichas de plantilla omitidas: jugadores sin ningún partido disputado",
            omitidos,
        )
    return {"filas": total, "omitidos": omitidos}


def _solo_jugadores_conocidos(filas: list[dict]) -> tuple[list[dict], int]:
    if not filas:
        return [], 0
    from sqlalchemy import select

    ids = {f["player_id"] for f in filas}
    with session_scope() as session:
        conocidos = set(
            session.scalars(select(Player.player_id).where(Player.player_id.in_(ids))).all()
        )
    validas = [f for f in filas if f["player_id"] in conocidos]
    return validas, len(filas) - len(validas)


# =========================================================================
# Clasificación
# =========================================================================


def ingest_standings(
    seasons: list[str], client: NBAClient | None = None
) -> int:
    """Clasificación oficial por temporada (1 petición cada una)."""
    client = client or NBAClient()

    total = 0
    for season in seasons:
        try:
            crudo = client.standings(season)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clasificación de %s falló: %s", season, exc)
            continue

        filas = [
            {
                "season_id": season,
                "team_id": r["TeamID"],
                "conference": _txt(r.get("Conference"), 10),
                "division": _txt(r.get("Division"), 20),
                "playoff_rank": _int_or_none(r.get("PlayoffRank")),
                "wins": _int_or_none(r.get("WINS")),
                "losses": _int_or_none(r.get("LOSSES")),
                "win_pct": _num_or_none(r.get("WinPCT")),
                "conference_record": _txt(r.get("ConferenceRecord"), 12),
                "division_record": _txt(r.get("DivisionRecord"), 12),
                "home_record": _txt(r.get("HOME"), 12),
                "road_record": _txt(r.get("ROAD"), 12),
                "last_10": _txt(r.get("L10"), 12),
                "current_streak": _int_or_none(r.get("CurrentStreak")),
                "games_back": _num_or_none(r.get("ConferenceGamesBack")),
                "points_pg": _num_or_none(r.get("PointsPG")),
                "opp_points_pg": _num_or_none(r.get("OppPointsPG")),
                "diff_points_pg": _num_or_none(r.get("DiffPointsPG")),
            }
            for r in crudo
            if r.get("TeamID")
        ]

        with session_scope() as session:
            total += upsert(
                session, TeamStanding, filas, keys=["season_id", "team_id"]
            )
        logger.info("Clasificación %s: %d equipos", season, len(filas))

    _backfill_conference()
    return total


def _backfill_conference() -> None:
    """Copia conferencia y división de la clasificación a `teams`.

    `TeamDetails` no devuelve ninguna de las dos, y el paquete estático tampoco.
    La clasificación sí, así que se propagan desde ahí: son propiedades del
    equipo, no de una temporada, y tenerlas en `teams` ahorra un join en cada
    consulta que agrupe por conferencia.

    Se toma la temporada más reciente porque las conferencias no cambian, pero
    los equipos sí cambian de división de vez en cuando.
    """
    from sqlalchemy import text as sql_text

    from nbastats.db.session import get_engine

    with get_engine().begin() as conn:
        resultado = conn.execute(sql_text("""
            UPDATE teams t
            SET conference = s.conference,
                division   = s.division
            FROM team_standings s
            WHERE s.team_id = t.team_id
              AND s.season_id = (SELECT MAX(season_id) FROM team_standings)
              AND s.conference IS NOT NULL
        """))
    logger.info("Conferencia y división propagadas a %d equipos", resultado.rowcount)


def ingest_all_team_data(seasons: list[str]) -> dict[str, int]:
    """Las tres piezas, en el orden en que dependen unas de otras."""
    client = NBAClient()
    detalles = ingest_team_details(client)
    plantillas = ingest_rosters(seasons, client)
    clasificacion = ingest_standings(seasons, client)

    with session_scope() as session:
        session.add(
            IngestLog(
                source="nba_api",
                endpoint="TeamDetails+CommonTeamRoster+LeagueStandingsV3",
                params={"seasons": seasons},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok",
                rows_written=detalles + plantillas["filas"] + clasificacion,
            )
        )

    return {
        "equipos": detalles,
        "plantillas": plantillas["filas"],
        "plantillas_omitidas": plantillas["omitidos"],
        "clasificacion": clasificacion,
    }
