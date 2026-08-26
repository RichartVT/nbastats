"""Quién salió de inicio, y quién no jugó y por qué.

LO QUE LA CARGA MASIVA NO PODÍA DAR. `PlayerGameLogs` devuelve una temporada
entera en una petición, pero **no dice quién fue titular** ni trae a los que no
jugaron. `BoxScoreTraditionalV3` sí, a cambio de una petición por partido: ~6.600
para las cinco temporadas, algo más de una hora. No hay atajo masivo; se
comprobó, que es la lección que este proyecto ya aprendió tres veces.

DOS TRAMPAS, LAS DOS DOCUMENTADAS ANTES DE PAGAR LA DESCARGA:

1. **La titularidad no es un campo.** No existe `starter`: lo que hay es
   `position`, rellena solo para los cinco titulares y vacía para el resto.

2. **Esto AÑADE filas, y eso rompe cosas en silencio.** La fuente anterior solo
   traía a quien apareció; ésta trae también a los lesionados y a los descartes
   técnicos. Son filas legítimas —un DNP es un hecho— pero **no son
   apariciones**, y cualquier `COUNT(*)` que las cuente miente. Por eso se
   guardan con `seconds_played = 0` y `dnp_reason` informado, y la capa de tasas
   las filtra.

NO SE USA `upsert()` AQUÍ, y es deliberado. El upsert genérico pone a NULL toda
columna que no venga en la fila, así que actualizar `started` y `dnp_reason` con
él borraría el box score entero de las 140.932 filas ya cargadas. Se hace un
UPDATE dirigido para lo que existe y un INSERT para lo que no.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select, text

from nbastats.db.models import Game, Player, PlayerGameStats
from nbastats.db.session import session_scope
from nbastats.ingest.nba_client import NBAClient

logger = logging.getLogger(__name__)


def _minutos_a_segundos(valor: str | None) -> int:
    """'28:55' -> 1735. Vacío o ausente -> 0."""
    if not valor or ":" not in str(valor):
        return 0
    m, _, sg = str(valor).partition(":")
    try:
        return int(float(m)) * 60 + int(float(sg))
    except ValueError:
        return 0


def _filas(game_id: str, caja: dict, conocidos: frozenset[int]) -> list[dict]:
    """Una fila por jugador listado, jugara o no."""
    salida: list[dict] = []
    for lado in ("homeTeam", "awayTeam"):
        equipo = caja.get(lado) or {}
        team_id = equipo.get("teamId")
        if not team_id:
            continue
        for j in equipo.get("players") or []:
            pid = j.get("personId")
            if not pid or int(pid) not in conocidos:
                continue
            comentario = (j.get("comment") or "").strip()
            salida.append(
                {
                    "game_id": game_id,
                    "player_id": int(pid),
                    "team_id": int(team_id),
                    # La posición solo viene para los titulares: ES el indicador.
                    "started": bool((j.get("position") or "").strip()),
                    "dnp_reason": comentario or None,
                    "seconds_played": _minutos_a_segundos(
                        (j.get("statistics") or {}).get("minutes")
                    ),
                }
            )
    return salida


def _guardar(filas: Sequence[dict]) -> dict:
    """UPDATE dirigido para lo que ya existe, INSERT para lo que no."""
    if not filas:
        return {"actualizadas": 0, "nuevas": 0}

    with session_scope() as s:
        # Solo estas dos columnas. Cualquier otra cosa borraría el box score.
        actualizadas = s.execute(
            text("""
                UPDATE player_game_stats t
                SET started = v.started, dnp_reason = v.dnp_reason
                FROM (
                    SELECT UNNEST(CAST(:gids AS varchar[]))  AS game_id,
                           UNNEST(CAST(:pids AS bigint[]))   AS player_id,
                           UNNEST(CAST(:sts AS boolean[]))   AS started,
                           UNNEST(CAST(:dnps AS text[]))     AS dnp_reason
                ) v
                WHERE t.game_id = v.game_id AND t.player_id = v.player_id
            """),
            {
                "gids": [f["game_id"] for f in filas],
                "pids": [f["player_id"] for f in filas],
                "sts": [f["started"] for f in filas],
                "dnps": [f["dnp_reason"] for f in filas],
            },
        ).rowcount

        # Los que no jugaron no tenían fila: son nuevos.
        nuevas = s.execute(
            text("""
                INSERT INTO player_game_stats
                    (game_id, player_id, team_id, seconds_played, started, dnp_reason)
                SELECT v.game_id, v.player_id, v.team_id, v.seconds_played,
                       v.started, v.dnp_reason
                FROM (
                    SELECT UNNEST(CAST(:gids AS varchar[]))  AS game_id,
                           UNNEST(CAST(:pids AS bigint[]))   AS player_id,
                           UNNEST(CAST(:tids AS bigint[]))   AS team_id,
                           UNNEST(CAST(:secs AS integer[]))  AS seconds_played,
                           UNNEST(CAST(:sts AS boolean[]))   AS started,
                           UNNEST(CAST(:dnps AS text[]))     AS dnp_reason
                ) v
                ON CONFLICT (game_id, player_id) DO NOTHING
            """),
            {
                "gids": [f["game_id"] for f in filas],
                "pids": [f["player_id"] for f in filas],
                "tids": [f["team_id"] for f in filas],
                "secs": [f["seconds_played"] for f in filas],
                "sts": [f["started"] for f in filas],
                "dnps": [f["dnp_reason"] for f in filas],
            },
        ).rowcount

    return {"actualizadas": actualizadas, "nuevas": nuevas}


def ingest_starters(
    seasons: list[str] | None = None,
    *,
    only_missing: bool = True,
    limit: int | None = None,
    client: NBAClient | None = None,
) -> dict:
    """Descarga titularidad y motivos de DNP de los partidos que falten.

    REANUDABLE POR CONSTRUCCIÓN, igual que el play-by-play: con `only_missing`
    se piden solo los partidos en los que ninguna fila tiene `started`
    informado, así que una descarga interrumpida se retoma donde se quedó.
    """
    client = client or NBAClient()

    with session_scope() as session:
        conocidos = frozenset(session.scalars(select(Player.player_id)).all())

        stmt = select(Game.game_id).order_by(
            Game.game_date_local.desc(), Game.game_id.desc()
        )
        if seasons:
            stmt = stmt.where(Game.season_id.in_(seasons))
        if only_missing:
            stmt = stmt.where(
                ~select(PlayerGameStats.game_id)
                .where(
                    PlayerGameStats.game_id == Game.game_id,
                    PlayerGameStats.started.is_not(None),
                )
                .exists()
            )
        pendientes = list(session.scalars(stmt).all())

    if limit:
        pendientes = pendientes[:limit]
    if not pendientes:
        logger.info("La titularidad está al día.")
        return {"pedidos": 0, "actualizadas": 0, "nuevas": 0, "fallidos": 0}

    logger.info("Titularidad: %d partidos por pedir", len(pendientes))
    total = {"pedidos": 0, "actualizadas": 0, "nuevas": 0, "fallidos": 0}

    for i, gid in enumerate(pendientes, start=1):
        try:
            caja = client.box_score_traditional(gid)
        except Exception:  # noqa: BLE001 — un partido roto no aborta la pasada
            logger.warning("Sin box score tradicional para %s", gid)
            total["fallidos"] += 1
            continue

        filas = _filas(gid, caja, conocidos)
        if not filas:
            total["fallidos"] += 1
            continue

        res = _guardar(filas)
        total["pedidos"] += 1
        total["actualizadas"] += res["actualizadas"]
        total["nuevas"] += res["nuevas"]

        if i % 250 == 0:
            logger.info(
                "  %d/%d partidos · %d filas nuevas",
                i, len(pendientes), total["nuevas"],
            )

    return total
