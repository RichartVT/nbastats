"""Resumen por partido: marcador por cuarto, pabellón, asistencia y árbitros.

Es la primera ingesta del proyecto que pide **una petición por partido**. Hasta
ahora todo era masivo —`PlayerGameLogs` devuelve una temporada entera en un
segundo, y la carga histórica completa tardó 156— así que conviene decir en voz
alta lo que esto cambia: son ~6.600 peticiones y ~1,5 horas, y no hay atajo.
No existe endpoint masivo para el desglose por periodo.

A cambio, una sola pasada cierra cuatro huecos que estaban documentados por
separado en `CAPABILITIES.md` y en la BITÁCORA:

1. **Marcador por cuarto**, que no existía a ninguna granularidad.
2. **`games.attendance` y `games.arena_name`**: columnas que llevaban desde el
   esquema inicial existiendo y valiendo siempre NULL.
3. **`games.ot_periods` real.** Hasta ahora se INFERÍA dividiendo los minutos
   del equipo entre 5 (`round((MIN - 48) / 5)`). Funcionaba, pero era una
   heurística sobre un dato que la fuente da directamente — justo lo que el
   proyecto aprendió a no hacer con el bug de "Quarterfinal".
4. **Árbitros**, que no estaban.

REANUDABLE POR CONSTRUCCIÓN. Con `only_missing=True` se piden solo los partidos
que aún no tienen marcador por periodo. No hay tabla de checkpoint: la propia
tabla de destino es el registro de lo hecho, igual que en `bio.py`. Una pasada
interrumpida a las dos horas se retoma donde se quedó.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import bindparam, select, update

from nbastats.db.models import Game, GameOfficial, GamePeriodScore, IngestLog
from nbastats.db.session import get_engine, session_scope
from nbastats.ingest.bulk import upsert
from nbastats.ingest.nba_client import NBAClient

logger = logging.getLogger(__name__)

# Cada cuántos partidos se vuelca a la base. Con 6.600 partidos por delante,
# perder 25 por una interrupción es irrelevante; hacer una transacción por
# partido multiplicaría por 25 el trabajo del motor sin ganar nada.
LOTE = 25


def _periodos(game_id: str, equipo: dict) -> list[dict]:
    """Filas de marcador por periodo de UN equipo.

    `is_overtime` sale de `periodType` y no de `period > 4`: es la fuente quien
    lo dice, y una regla nuestra dejaría de valer el día que la NBA cambie el
    formato de la prórroga o el número de cuartos.
    """
    team_id = equipo.get("teamId")
    if not team_id:
        return []

    filas = []
    for p in equipo.get("periods") or []:
        periodo, puntos = p.get("period"), p.get("score")
        if periodo is None or puntos is None:
            continue
        filas.append(
            {
                "game_id": game_id,
                "team_id": team_id,
                "period": int(periodo),
                "points": int(puntos),
                "is_overtime": str(p.get("periodType", "")).upper() == "OVERTIME",
            }
        )
    return filas


def _arbitros(game_id: str, resumen: dict) -> list[dict]:
    filas = []
    for o in resumen.get("officials") or []:
        official_id = o.get("personId")
        if not official_id:
            continue
        filas.append(
            {
                "game_id": game_id,
                "official_id": int(official_id),
                "name": (o.get("name") or "").strip()[:60],
                # Llega con relleno a la derecha: '26  '.
                "jersey_number": (str(o.get("jerseyNum") or "").strip() or None),
            }
        )
    return filas


def _cabecera(game_id: str, resumen: dict, periodos: list[dict]) -> dict | None:
    """Campos de `games` que este endpoint rellena.

    Los periodos de prórroga se CUENTAN, no se calculan: son los periodos
    marcados como prórroga en el marcador, divididos entre los dos equipos.
    """
    arena = resumen.get("arena") or {}
    prorrogas = len({p["period"] for p in periodos if p["is_overtime"]})

    return {
        "b_game_id": game_id,
        "attendance": _entero(resumen.get("attendance")),
        "arena_name": (arena.get("arenaName") or None),
        "ot_periods": prorrogas,
    }


def _entero(valor: Any) -> int | None:
    """La asistencia llega como 0 en partidos a puerta cerrada y en los que no
    la publican. Cero espectadores y "no lo sabemos" no son lo mismo, y una
    media de asistencia que cuente los ceros estaría mal, así que el 0 se
    guarda como NULL."""
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return None
    return n or None


CAMPOS_CABECERA = ("attendance", "arena_name", "ot_periods")


def _volcar(periodos: list[dict], arbitros: list[dict], cabeceras: list[dict]) -> int:
    """Escribe un lote. Devuelve cuántas filas de periodo se han escrito."""
    if not periodos:
        return 0

    with session_scope() as session:
        upsert(session, GamePeriodScore, periodos, keys=["game_id", "team_id", "period"])
        if arbitros:
            upsert(session, GameOfficial, arbitros, keys=["game_id", "official_id"])

    # UPDATE y no UPSERT sobre `games`, por el mismo motivo que en `bio.py`: un
    # upsert exigiría aportar las columnas NOT NULL del partido (temporada,
    # equipos, fecha) que aquí no se conocen ni hacen falta.
    if cabeceras:
        stmt = (
            update(Game)
            .where(Game.game_id == bindparam("b_game_id"))
            .values({c: bindparam(c) for c in CAMPOS_CABECERA})
        )
        with get_engine().begin() as conn:
            conn.execute(stmt, cabeceras)

    return len(periodos)


def ingest_game_summaries(
    seasons: list[str] | None = None,
    *,
    only_missing: bool = True,
    limit: int | None = None,
    client: NBAClient | None = None,
) -> dict:
    """Descarga el resumen de cada partido y guarda periodos, árbitros y ficha.

    `limit` existe para poder probar la pasada con 20 partidos antes de soltar
    las dos horas: es la diferencia entre descubrir un fallo de mapeo al minuto
    o a la hora y media.
    """
    client = client or NBAClient()

    with session_scope() as session:
        stmt = select(Game.game_id)
        if seasons:
            stmt = stmt.where(Game.season_id.in_(seasons))
        if only_missing:
            stmt = stmt.where(
                ~select(GamePeriodScore.game_id)
                .where(GamePeriodScore.game_id == Game.game_id)
                .exists()
            )
        pendientes = sorted(session.scalars(stmt).all())

    if limit:
        pendientes = pendientes[:limit]

    if not pendientes:
        logger.info("Todos los resúmenes de partido están al día.")
        return {"pedidos": 0, "periodos": 0, "fallidos": 0}

    logger.info(
        "Descargando %d resúmenes de partido (~%.0f min)",
        len(pendientes),
        len(pendientes) * (client.delay + 0.3) / 60,
    )

    escritos = fallidos = 0
    periodos: list[dict] = []
    arbitros: list[dict] = []
    cabeceras: list[dict] = []

    for i, game_id in enumerate(pendientes, 1):
        try:
            resumen = client.game_summary(game_id)
        except Exception as exc:  # noqa: BLE001 — un partido no tumba la pasada
            logger.warning("Resumen de %s falló: %s", game_id, exc)
            fallidos += 1
            continue

        del_partido = _periodos(game_id, resumen.get("homeTeam") or {}) + _periodos(
            game_id, resumen.get("awayTeam") or {}
        )
        if not del_partido:
            logger.warning("El resumen de %s no trae marcador por periodo", game_id)
            fallidos += 1
            continue

        periodos += del_partido
        arbitros += _arbitros(game_id, resumen)
        cabeceras.append(_cabecera(game_id, resumen, del_partido))

        if len(cabeceras) >= LOTE or i == len(pendientes):
            escritos += _volcar(periodos, arbitros, cabeceras)
            periodos, arbitros, cabeceras = [], [], []
            logger.info("  %d/%d", i, len(pendientes))

    with session_scope() as session:
        session.add(
            IngestLog(
                source="nba_api",
                endpoint="BoxScoreSummaryV3",
                params={"solicitados": len(pendientes), "seasons": seasons},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok" if not fallidos else "partial",
                rows_written=escritos,
            )
        )

    logger.info(
        "Resúmenes: %d partidos, %d filas de periodo, %d fallidos",
        len(pendientes) - fallidos,
        escritos,
        fallidos,
    )
    return {"pedidos": len(pendientes), "periodos": escritos, "fallidos": fallidos}
