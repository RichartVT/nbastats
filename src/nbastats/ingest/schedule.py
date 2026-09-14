"""Ingesta del calendario: los partidos anunciados de una temporada.

UNA PETICIÓN POR TEMPORADA. `ScheduleLeagueV2` devuelve el calendario entero
—las 160 jornadas, los 1.200 y pico partidos— de golpe, así que mantenerlo al
día es la ingesta más barata del proyecto y puede correr en cada pasada diaria
sin pensárselo.

QUÉ APORTA QUE NO TENGA YA `games`. El calendario contesta a "¿cuándo juega mi
equipo?", que es una pregunta sobre el futuro y por tanto no puede salir de una
tabla de hechos. En octubre, la ficha de un equipo no tiene un solo partido
jugado que enseñar: lo único que hay es esto.

QUÉ NO SE GUARDA:

- **La pretemporada.** No interesa para la aplicación, y es lo coherente con
  `derive.sql`, que ya la excluye del descanso, del récord previo y del índice
  de ausencias.
- **El fin de semana del All-Star.** No lo juegan franquicias sino equipos
  montados para la ocasión, con ids que no existen en `teams`.
- Los retransmisores y los líderes de anotación, que el payload trae y aquí
  sobran: lo primero caduca y lo segundo ya está en el box score.

REANUDABLE Y CORRECTOR. El upsert va por `game_id`, así que relanzarlo recoge
los aplazamientos, los cambios de pabellón y —en diciembre— los cruces de la
NBA Cup, que se publican con los dos equipos por determinar.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from nbastats.db.models import IngestLog, ScheduledGame, SeasonType
from nbastats.db.session import session_scope
from nbastats.ingest.bulk import ensure_season, upsert
from nbastats.ingest.nba_client import ARENA_TIMEZONES, NBAClient
from nbastats.ingest.transforms import local_game_date, parse_game_id

logger = logging.getLogger(__name__)


def _parse_utc(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


# La fuente marca "hora todavía sin fijar" con un año cero en `gameTimeEst`,
# no con un nulo. Es el caso de los cruces de la NBA Cup: el día está decidido
# y la hora no. Su `gameDateTimeUTC` sale entonces como medianoche del Este,
# que parece una hora de salto inicial y no lo es.
_HORA_SIN_FIJAR = "0001-01-01"


def _hora_fijada(juego: dict[str, Any]) -> bool:
    return not str(juego.get("gameTimeEst") or "").startswith(_HORA_SIN_FIJAR)


def _fecha_est(raw: str | None) -> dt.date | None:
    """La fecha que la NBA asigna al partido, en hora del Este.

    Es el respaldo para los partidos que aún no tienen local asignado: sin
    equipo no hay zona horaria del estadio con la que derivar la fecha local.
    """
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _equipo_o_none(bloque: dict[str, Any] | None) -> int | None:
    """El id de equipo, o None si está por determinar.

    La fuente manda `teamId: 0` para los cruces de la NBA Cup que todavía no
    tienen contendientes. Cero no es un equipo, es un hueco: guardarlo tal cual
    violaría la clave ajena contra `teams`. Mismo criterio que `_team_or_none`
    en `bio.py`.
    """
    return (bloque or {}).get("teamId") or None


def _txt(value: Any, limite: int) -> str | None:
    if value in (None, "", " "):
        return None
    texto = str(value).strip()
    return texto[:limite] if texto else None


# Tercer dígito del game_id: el fin de semana del All-Star. Incluye el partido
# de las estrellas, el Rising Stars y sus semifinales.
_TIPO_ALL_STAR = "3"


def _es_all_star(game_id: str) -> bool:
    """¿Es del fin de semana del All-Star?

    NO ENTRA EN EL CALENDARIO, y el motivo es más duro que una preferencia: lo
    juegan equipos inventados para la ocasión —"Team Chuck", los sub-21 del
    Rising Stars— con ids propios que no existen en `teams`. Guardarlos
    violaría la clave ajena y tiraría la ingesta de la temporada entera; en
    2025-26 son 7 ids y 7 partidos.

    Tampoco tendría sentido enseñarlos: no son partidos de ninguna franquicia,
    así que no aparecerían en el calendario de nadie.
    """
    return str(game_id)[2:3] == _TIPO_ALL_STAR


def _tipo_de_temporada(game_id: str) -> SeasonType | None:
    """El tipo de partido, o None si no es una fase de la temporada.

    `parse_game_id` levanta `ValueError` para la final de la NBA Cup (tipo
    '6'), porque no cuenta como partido de temporada para los análisis. En el
    CALENDARIO sí va —se juega, entre dos equipos reales, y la gente lo
    busca—, así que aquí el error se traduce a "sin fase" en vez de tirar la
    ingesta entera por un partido de los 1.207.
    """
    try:
        return parse_game_id(game_id)[1]
    except ValueError:
        return None


def parse_schedule(payload: dict) -> list[dict]:
    """Convierte el bloque `leagueSchedule` en filas de `scheduled_games`.

    Separado de la escritura para poder probarlo contra un payload recortado
    sin tocar la red ni la base.
    """
    # La temporada sale del propio payload y no de `parse_game_id`: el id de la
    # final de la Cup también la codifica, pero leerla de la cabecera es una
    # fuente menos por la que equivocarse.
    season_id = (payload.get("seasonYear") or "").strip()
    if not season_id:
        raise ValueError("el calendario llegó sin `seasonYear`")

    filas: list[dict] = []
    for jornada in payload.get("gameDates") or []:
        for juego in jornada.get("games") or []:
            game_id = str(juego.get("gameId") or "").strip()
            if not game_id:
                continue

            if _es_all_star(game_id):
                continue

            season_type = _tipo_de_temporada(game_id)
            # La pretemporada se descarta AQUÍ, al entrar, y no en la consulta:
            # filtrarla en la vista la deja volver por cualquier consulta nueva
            # que se escriba después.
            if season_type is SeasonType.PRESEASON:
                continue

            home_id = _equipo_o_none(juego.get("homeTeam"))
            tipoff = (
                _parse_utc(juego.get("gameDateTimeUTC"))
                if _hora_fijada(juego)
                else None
            )
            respaldo = _fecha_est(juego.get("gameDateEst"))
            # Sin ninguna de las dos no hay partido que colocar en un
            # calendario. No ha pasado, pero un hueco de la fuente no debe
            # tirar las otras 1.206 filas.
            if tipoff is None and respaldo is None:
                logger.warning("Partido %s sin fecha en el calendario", game_id)
                continue

            fecha = local_game_date(
                tipoff,
                ARENA_TIMEZONES.get(home_id) if home_id else None,
                fallback=respaldo,
            )

            filas.append(
                {
                    "game_id": game_id,
                    "season_id": season_id,
                    "season_type": season_type,
                    "game_date_local": fecha,
                    "tipoff_utc": tipoff,
                    "home_team_id": home_id,
                    "away_team_id": _equipo_o_none(juego.get("awayTeam")),
                    "arena_name": _txt(juego.get("arenaName"), 100),
                    "arena_city": _txt(juego.get("arenaCity"), 60),
                    # Señal directa de la fuente. En este endpoint viene
                    # poblada, así que no hace falta la heurística de `enrich`.
                    "is_neutral_site": bool(juego.get("isNeutral")),
                    "game_label": _txt(juego.get("gameLabel"), 60),
                    "game_sublabel": _txt(juego.get("gameSubLabel"), 40),
                    "week_number": juego.get("weekNumber"),
                    "game_status": juego.get("gameStatus"),
                    "postponed_status": _txt(juego.get("postponedStatus"), 4),
                }
            )

    return filas


def ingest_schedule(
    seasons: list[str], client: NBAClient | None = None
) -> dict[str, int]:
    """Calendario de las temporadas dadas. Una petición cada una."""
    client = client or NBAClient()

    total = fallidos = 0
    for season in seasons:
        try:
            payload = client.league_schedule(season)
            filas = parse_schedule(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Calendario de %s falló: %s", season, exc)
            fallidos += 1
            continue

        if not filas:
            logger.info("Calendario %s: la NBA todavía no lo ha publicado", season)
            continue

        with session_scope() as session:
            # El calendario puede llegar ANTES que el primer partido, así que
            # es la primera ingesta que ve esa temporada y le toca crear su
            # fila en `seasons` — si no, la clave ajena la rechaza.
            ensure_season(session, season)
            total += upsert(session, ScheduledGame, filas, keys=["game_id"])

        sin_rival = sum(1 for f in filas if f["home_team_id"] is None)
        logger.info(
            "Calendario %s: %d partidos%s",
            season,
            len(filas),
            f", {sin_rival} con rival por determinar" if sin_rival else "",
        )

    with session_scope() as session:
        session.add(
            IngestLog(
                source="nba_api",
                endpoint="ScheduleLeagueV2",
                params={"seasons": seasons},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok" if not fallidos else "partial",
                rows_written=total,
            )
        )

    return {"partidos": total, "fallidos": fallidos}
