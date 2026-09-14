"""Ingesta de datos de equipo: ficha, plantillas y clasificación.

Tres piezas, todas baratas:

- **Ficha** (`TeamDetails`): 30 peticiones. Estadio, capacidad, propietario,
  director general, entrenador y año de fundación.
- **Plantillas** (`CommonTeamRoster`): 30 × temporada. Se guardan todas las
  temporadas, no solo la actual: sin eso, mirar a los Nuggets de 2022-23
  mostraría la plantilla de 2025-26, que es justo lo contrario de lo que sirve
  para analizar una temporada pasada.
  Una plantilla, además, **siembra** al jugador que todavía no está en la
  base: es la única fuente que conoce a un fichaje antes de su primer partido.
- **Clasificación** (`LeagueStandingsV3`): 1 petición por temporada, con
  `PlayoffRank` ya resuelto y los desempates oficiales aplicados. No se guarda
  la de una temporada que aún no ha empezado.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from nbastats.db.models import IngestLog, Player, Team, TeamSeasonRoster, TeamStanding
from nbastats.db.session import session_scope
from nbastats.ingest.bulk import ensure_players, upsert
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

    total = nuevos = retiradas = 0
    for season in seasons:
        filas: list[dict] = []
        nombres: dict[int, str] = {}
        # Quién está HOY en cada equipo, solo de los equipos que contestaron y
        # contestaron con gente. Es lo que autoriza a borrar: de un equipo que
        # falló no se sabe nada, y no saber nada no es lo mismo que "ya no hay
        # nadie".
        vigentes: dict[int, set[int]] = {}
        for equipo in equipos:
            try:
                bloques = client.team_roster(equipo["id"], season)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Plantilla de %s %s falló: %s", equipo["abbreviation"], season, exc
                )
                continue

            del_equipo = _ids_de_plantilla(bloques)
            if del_equipo:
                vigentes[equipo["id"]] = del_equipo
            else:
                # Un equipo sin un solo jugador es un hueco de la fuente, no una
                # plantilla que se ha quedado vacía. Se deja como está.
                logger.warning(
                    "Plantilla de %s %s llegó vacía: no se limpia",
                    equipo["abbreviation"], season,
                )

            for jugador in bloques.get("CommonTeamRoster", []):
                player_id = _int_or_none(jugador.get("PLAYER_ID"))
                if player_id is None:
                    continue
                # El nombre no es columna de `team_season_rosters`: viaja
                # aparte para poder sembrar al jugador que aún no existe.
                nombres[player_id] = (jugador.get("PLAYER") or "").strip()
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

        with session_scope() as session:
            # LA PLANTILLA SIEMBRA AL JUGADOR. Antes se descartaba la ficha de
            # quien no estuviera ya en `players`, con el argumento de que una
            # plantilla es contexto y no una fuente de jugadores. Eso vale
            # mirando hacia atrás y falla mirando hacia delante: en una
            # temporada que aún no ha empezado, los fichajes que más importan
            # —los novatos del draft y los que llegan de otras ligas— no han
            # jugado un solo partido NBA, así que descartarlos deja la
            # plantilla nueva sin la mitad interesante.
            #
            # Se crea la fila mínima (id y nombre) con el mismo helper que usa
            # la carga de box scores; `ingest-bios` la completa después, porque
            # selecciona justo por `birthdate IS NULL`.
            #
            # No ensucia la aplicación: el listado de jugadores se construye
            # sobre `mv_player_season`, así que quien no ha jugado no aparece
            # en las búsquedas — solo en la plantilla de su equipo, que es
            # exactamente donde se le espera.
            nuevos += _cuantos_no_existian(session, set(nombres))
            ensure_players(
                session,
                [
                    {"PLAYER_ID": pid, "PLAYER_NAME": nombre}
                    for pid, nombre in nombres.items()
                    if nombre
                ],
            )
            total += upsert(
                session,
                TeamSeasonRoster,
                filas,
                keys=["season_id", "team_id", "player_id"],
            )
            retiradas += _limpiar_plantillas(session, season, vigentes)

        logger.info(
            "Plantillas %s: %d jugadores%s",
            season,
            len(filas),
            f", {retiradas} ficha{'s' if retiradas != 1 else ''} retirada"
            f"{'s' if retiradas != 1 else ''}" if retiradas else "",
        )

        _derivar_equipo_actual(season, exhaustivo=len(vigentes) == len(equipos))

    return {"filas": total, "jugadores_nuevos": nuevos, "retiradas": retiradas}


def _ids_de_plantilla(bloques: dict) -> set[int]:
    """Los `player_id` de una respuesta de `CommonTeamRoster`."""
    ids = set()
    for jugador in bloques.get("CommonTeamRoster", []):
        pid = _int_or_none(jugador.get("PLAYER_ID"))
        if pid is not None:
            ids.add(pid)
    return ids


def _limpiar_plantillas(
    session,  # noqa: ANN001
    season: str,
    vigentes: dict[int, set[int]],
) -> int:
    """Borra las fichas de quien ya no está en el equipo.

    UNA PLANTILLA ES UNA FOTO, NO UN HISTORIAL, y así la publica la fuente:
    `CommonTeamRoster` devuelve a Dončić en 2024-25 solo en los Lakers, aunque
    empezara esa temporada en Dallas y jugara 22 partidos con ellos.

    Sin esto, el upsert solo sabe añadir: en cuanto alguien cambiara de equipo
    con la actualización diaria en marcha, se quedaría en las plantillas de los
    dos a la vez. No se había notado porque las cinco temporadas cargadas se
    trajeron de una sola vez, ya con los traspasos resueltos.

    Quién pasó por dónde se responde con los box scores, que guardan el equipo
    partido a partido y no necesitan nada de esto.

    `vigentes` trae SOLO los equipos que contestaron con jugadores. Es la
    diferencia entre "ya no está en el equipo" y "hoy no sabemos quién está",
    que sin este filtro se convertirían en la misma cosa: un fallo de red
    vaciaría la plantilla entera de ese equipo.
    """
    from sqlalchemy import delete

    borradas = 0
    for team_id, ids in vigentes.items():
        res = session.execute(
            delete(TeamSeasonRoster).where(
                TeamSeasonRoster.season_id == season,
                TeamSeasonRoster.team_id == team_id,
                TeamSeasonRoster.player_id.notin_(ids),
            )
        )
        borradas += res.rowcount or 0
    return borradas


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

        if not _ya_se_jugo(filas):
            # UNA CLASIFICACIÓN SIN UN SOLO PARTIDO NO ES UNA CLASIFICACIÓN.
            # La NBA publica los 30 equipos a 0-0 en cuanto existe la
            # temporada, meses antes de que empiece. Guardarlos tendría un
            # efecto desproporcionado: las consultas resuelven la temporada por
            # defecto con `MAX(season_id) FROM team_standings`, así que la
            # portada y la ficha de cada equipo pasarían a enseñar un 0-0 en
            # vez del récord de la última temporada jugada.
            #
            # El criterio es el dato y no una fecha escrita a mano: en cuanto
            # se juegue el primer partido, la clasificación entra sola.
            logger.info("Clasificación %s: todavía no se ha jugado nada", season)
            continue

        with session_scope() as session:
            total += upsert(
                session, TeamStanding, filas, keys=["season_id", "team_id"]
            )
        logger.info("Clasificación %s: %d equipos", season, len(filas))

    _backfill_conference()
    return total


def _derivar_equipo_actual(season: str, *, exhaustivo: bool) -> None:
    """Propaga a `players` en qué equipo está cada uno, desde la plantilla.

    LA PLANTILLA ES LA FUENTE, Y SALE GRATIS. `current_team_id` y
    `roster_status` los trae `CommonPlayerInfo`, que solo se pide de los
    jugadores a los que les falta la ficha: a uno ya cargado no se le vuelve a
    preguntar nunca, así que ambos campos se congelaban el día de su primera
    carga. Se veía en los datos —DeRozan figurando en Sacramento estando en
    Denver, Klay Thompson con equipo pero marcado como agente libre— y rompía
    el filtro por equipo y los tres filtros de estado del listado de jugadores.

    Volver a pedir la ficha de los ~590 jugadores en plantilla costaría siete
    minutos diarios para averiguar algo que la plantilla que acabamos de
    descargar ya dice. Mismo patrón que `_backfill_conference()`: un dato que
    otra tabla conoce mejor, propagado con un UPDATE.

    Args:
        season: de qué temporada se lee la plantilla.
        exhaustivo: si los 30 equipos contestaron. Solo entonces se puede
            afirmar que quien no aparece en ninguna plantilla se ha quedado sin
            equipo; con la mitad de la liga sin responder, esa misma frase
            marcaría como agentes libres a cientos de jugadores que sí lo
            tienen.
    """
    from sqlalchemy import text as sql_text

    from nbastats.db.session import get_engine

    with get_engine().begin() as conn:
        # SOLO DESDE LA TEMPORADA MÁS RECIENTE. Sin esta comprobación, un
        # `ingest-teams --seasons 2022-23` para rellenar histórico reescribiría
        # el equipo actual de media liga con el de hace cuatro años.
        ultima = conn.execute(
            sql_text("SELECT MAX(season_id) FROM team_season_rosters")
        ).scalar()
        if season != ultima:
            logger.info(
                "Equipo actual: %s no es la temporada vigente (%s), no se deriva",
                season, ultima,
            )
            return

        en_plantilla = conn.execute(
            sql_text("""
                UPDATE players p
                SET current_team_id = r.team_id,
                    roster_status   = 'Active'
                FROM team_season_rosters r
                WHERE r.player_id = p.player_id
                  AND r.season_id = :season
                  AND (p.current_team_id IS DISTINCT FROM r.team_id
                       OR p.roster_status IS DISTINCT FROM 'Active')
            """),
            {"season": season},
        ).rowcount

        sin_equipo = 0
        if exhaustivo:
            sin_equipo = conn.execute(
                sql_text("""
                    UPDATE players p
                    SET current_team_id = NULL,
                        roster_status   = 'Inactive'
                    WHERE NOT EXISTS (
                            SELECT 1 FROM team_season_rosters r
                            WHERE r.player_id = p.player_id
                              AND r.season_id = :season)
                      AND (p.current_team_id IS NOT NULL
                           OR p.roster_status IS DISTINCT FROM 'Inactive')
                """),
                {"season": season},
            ).rowcount

    if en_plantilla or sin_equipo:
        logger.info(
            "Equipo actual desde la plantilla %s: %d fichados, %d sin equipo",
            season, en_plantilla, sin_equipo,
        )
    if not exhaustivo:
        logger.warning(
            "No contestaron los 30 equipos: nadie se marca como sin equipo"
        )


def _cuantos_no_existian(session, ids: set[int]) -> int:  # noqa: ANN001
    """Cuántos de estos jugadores no estaban todavía en la base.

    Se cuenta ANTES de sembrarlos porque es el número que interesa informar:
    cuántas fichas nuevas quedan pendientes de biografía. El upsert devuelve
    cuántas filas tocó, que son todas.
    """
    if not ids:
        return 0
    from sqlalchemy import select

    conocidos = set(
        session.scalars(select(Player.player_id).where(Player.player_id.in_(ids))).all()
    )
    return len(ids - conocidos)


def _ya_se_jugo(filas: list[dict]) -> bool:
    """¿Ha jugado alguien algún partido en esta temporada?"""
    return any((f.get("wins") or 0) + (f.get("losses") or 0) > 0 for f in filas)


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
        "jugadores_nuevos": plantillas["jugadores_nuevos"],
        "fichas_retiradas": plantillas["retiradas"],
        "clasificacion": clasificacion,
    }
