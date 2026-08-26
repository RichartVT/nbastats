"""Play-by-play: cada evento de cada partido.

La ingesta más grande del proyecto: ~525 eventos por partido, ~3,5 M filas,
6.602 peticiones, ~3 horas. Una por partido, sin atajo — no existe endpoint
masivo para esto, a diferencia de los cuartos.

POR QUÉ DELETE + INSERT Y NO EL `upsert()` DE SIEMPRE. El upsert genérico hace
`ON CONFLICT DO UPDATE`, que es lo correcto cuando el conjunto de filas de una
entidad nunca encoge — el caso de `player_game_stats`, donde los jugadores de un
partido son los que son. Aquí no: cuando la NBA reedita un partido, el
play-by-play corregido puede tener 470 acciones donde antes había 475, y las 5
sobrantes **sobrevivirían** al upsert como jugadas fantasma. Se borra el partido
entero y se reinserta, en una transacción.

REANUDABLE. Con `only_missing=True` se piden solo los partidos sin eventos: la
propia tabla de destino es el registro de lo hecho, igual que en `bio.py` y en
`summaries.py`. Una pasada interrumpida a las dos horas se retoma donde estaba.
Se recorre de MÁS RECIENTE a más antiguo a propósito: si se corta a medias, lo
cargado son los partidos que alguien va a querer mirar.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from sqlalchemy import delete, select, text

from nbastats.db.models import Game, IngestLog, PlayByPlay, Player
from nbastats.db.session import session_scope
from nbastats.ingest.nba_client import NBAClient

logger = logging.getLogger(__name__)

# Duración de un periodo en segundos: 12 min los cuartos, 5 las prórrogas.
SEGUNDOS_CUARTO = 720
SEGUNDOS_PRORROGA = 300
CUARTOS_REGLAMENTARIOS = 4

# "PT10M24.00S" — formato ISO-8601 de duración que usa la V3.
_RELOJ = re.compile(r"PT(\d+)M([\d.]+)S")


def parse_clock(valor: str | None) -> int | None:
    """Reloj ISO-8601 a segundos RESTANTES del periodo.

    >>> parse_clock("PT10M24.00S")
    624
    >>> parse_clock("PT00M00.00S")
    0
    >>> parse_clock(None) is None
    True
    """
    if not valor:
        return None
    m = _RELOJ.match(str(valor).strip())
    if not m:
        return None
    return int(int(m.group(1)) * 60 + float(m.group(2)))


def elapsed_seconds(period: int, clock: int | None) -> int | None:
    """Segundos transcurridos desde el salto inicial.

    Las prórrogas duran 300 s, no 720. Un cálculo que asuma 720 desplaza todo
    lo que venga después, y el 6,5 % de los partidos tiene al menos una.

    >>> elapsed_seconds(1, 720)
    0
    >>> elapsed_seconds(2, 0)
    1440
    >>> elapsed_seconds(5, 300)
    2880
    """
    if clock is None or period < 1:
        return None
    if period <= CUARTOS_REGLAMENTARIOS:
        inicio = (period - 1) * SEGUNDOS_CUARTO
        duracion = SEGUNDOS_CUARTO
    else:
        inicio = CUARTOS_REGLAMENTARIOS * SEGUNDOS_CUARTO
        inicio += (period - CUARTOS_REGLAMENTARIOS - 1) * SEGUNDOS_PRORROGA
        duracion = SEGUNDOS_PRORROGA
    return inicio + (duracion - clock)


def _id_o_none(valor: Any) -> int | None:
    """La fuente usa 0 para "de nadie" en los eventos de equipo, finales de
    periodo y saltos. Insertarlo violaría la clave ajena; NULL es lo que
    significa."""
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return None
    return n or None


def _jugador(valor: Any, conocidos: frozenset[int]) -> int | None:
    pid = _id_o_none(valor)
    if pid is None or (conocidos and pid not in conocidos):
        return None
    return pid


def _resultado_tiro(valor: Any) -> bool | None:
    """'Made' -> True, 'Missed' -> False, vacío -> None (no era un tiro)."""
    texto = str(valor or "").strip().lower()
    if texto == "made":
        return True
    if texto == "missed":
        return False
    return None


def _entero(valor: Any) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _fila(game_id: str, ev: dict, jugadores: frozenset[int] = frozenset()) -> dict | None:
    action_id = _entero(ev.get("actionId"))
    period = _entero(ev.get("period"))
    if action_id is None or period is None or period < 1:
        return None

    reloj = parse_clock(ev.get("clock"))
    return {
        "game_id": game_id,
        "action_id": action_id,
        "action_number": _entero(ev.get("actionNumber")),
        "period": period,
        "clock_seconds": reloj,
        "elapsed_seconds": elapsed_seconds(period, reloj),
        "team_id": _id_o_none(ev.get("teamId")),
        # `personId` NO siempre es un jugador: en los tiempos muertos lleva el
        # id del EQUIPO, y en las técnicas el del ÁRBITRO (se vieron 320, 544 y
        # 739 en un solo partido). Insertarlos violaría la clave ajena, así que
        # solo se acepta lo que esté en `players`; el resto va a NULL y su
        # identidad sigue viva en `description`.
        "player_id": _jugador(ev.get("personId"), jugadores),
        "action_type": (str(ev.get("actionType") or "").strip() or None),
        "sub_type": (str(ev.get("subType") or "").strip() or None),
        "description": (str(ev.get("description") or "").strip() or None),
        "score_home": _entero(ev.get("scoreHome")),
        "score_away": _entero(ev.get("scoreAway")),
        "is_field_goal": bool(ev.get("isFieldGoal")),
        "shot_result": _resultado_tiro(ev.get("shotResult")),
        "shot_value": _entero(ev.get("shotValue")),
        "shot_distance": _entero(ev.get("shotDistance")),
        "x_legacy": _entero(ev.get("xLegacy")),
        "y_legacy": _entero(ev.get("yLegacy")),
    }


def _guardar(game_id: str, filas: list[dict]) -> int:
    """Reemplaza los eventos del partido, en una transacción."""
    if not filas:
        return 0
    with session_scope() as session:
        session.execute(delete(PlayByPlay).where(PlayByPlay.game_id == game_id))
        session.execute(PlayByPlay.__table__.insert(), filas)
    return len(filas)


def ingest_play_by_play(
    seasons: list[str] | None = None,
    *,
    only_missing: bool = True,
    limit: int | None = None,
    client: NBAClient | None = None,
) -> dict:
    """Descarga el play-by-play de los partidos que falten."""
    client = client or NBAClient()

    with session_scope() as session:
        # Censo de jugadores conocidos, una vez por pasada y no una por partido.
        jugadores = frozenset(session.scalars(select(Player.player_id)).all())

        stmt = select(Game.game_id).order_by(Game.game_date_local.desc(), Game.game_id.desc())
        if seasons:
            stmt = stmt.where(Game.season_id.in_(seasons))
        if only_missing:
            stmt = stmt.where(
                ~select(PlayByPlay.game_id)
                .where(PlayByPlay.game_id == Game.game_id)
                .exists()
            )
        pendientes = list(session.scalars(stmt).all())

    if limit:
        pendientes = pendientes[:limit]

    if not pendientes:
        logger.info("El play-by-play está al día.")
        return {"pedidos": 0, "eventos": 0, "fallidos": 0}

    logger.info(
        "Descargando play-by-play de %d partidos (~%.1f h)",
        len(pendientes),
        len(pendientes) * (client.delay + 0.9) / 3600,
    )

    eventos = fallidos = 0
    for i, game_id in enumerate(pendientes, 1):
        try:
            crudos = client.play_by_play(game_id)
        except Exception as exc:  # noqa: BLE001 — un partido no tumba la pasada
            logger.warning("Play-by-play de %s falló: %s", game_id, exc)
            fallidos += 1
            continue

        filas = [f for ev in crudos if (f := _fila(game_id, ev, jugadores))]
        if not filas:
            logger.warning("La NBA no tiene play-by-play del partido %s", game_id)
            fallidos += 1
            continue

        eventos += _guardar(game_id, filas)
        if i % 50 == 0 or i == len(pendientes):
            logger.info("  %d/%d · %d eventos", i, len(pendientes), eventos)

    with session_scope() as session:
        session.add(
            IngestLog(
                source="nba_api",
                endpoint="PlayByPlayV3",
                params={"solicitados": len(pendientes), "seasons": seasons},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok" if not fallidos else "partial",
                rows_written=eventos,
            )
        )

    logger.info("Play-by-play: %d eventos, %d fallidos", eventos, fallidos)
    return {"pedidos": len(pendientes), "eventos": eventos, "fallidos": fallidos}


def verificar_marcador() -> dict:
    """El marcador MÁXIMO del partido debe coincidir con el resultado final.

    Es el criterio de aceptación: si no cuadra, el play-by-play llegó truncado
    y los análisis que se apoyen en él estarán mal sin dar ningún error.

    Se toma el MÁXIMO y no el último evento, que era la primera versión de esta
    comprobación y daba 4 falsos descuadres de 6.602. El motivo es que los
    eventos posteriores a la última canasta —la revisión instantánea y el fin
    de periodo— arrastran el marcador ANTERIOR:

        479  Hield 24' 3PT   122-112   <- el bueno
        480  Instant Replay  119-112   <- revierte
        481  End of Period   119-112

    El marcador nunca decrece dentro de un partido, así que el máximo es el
    final. Con el último evento, un partido correcto parecía roto.
    """
    sql = text("""
        WITH maximo AS (
            SELECT game_id, MAX(score_home) AS score_home, MAX(score_away) AS score_away
            FROM play_by_play
            WHERE score_home IS NOT NULL
            GROUP BY game_id
        )
        SELECT count(*) AS comprobados,
               count(*) FILTER (
                   WHERE u.score_home = g.home_pts AND u.score_away = g.away_pts
               ) AS cuadran
        FROM maximo u JOIN games g USING (game_id)
    """)
    with session_scope() as session:
        fila = session.execute(sql).mappings().one()
    return dict(fila)
