"""Biografías de jugadores: fecha de nacimiento, altura, peso, posición.

Sin `birthdate` no hay curvas de edad, y sin curvas de edad no se puede separar
"está en declive" de "tiene 34 años y le pasa lo que a todos". Es la diferencia
entre un dato interesante y uno accionable.

Por qué `nba_api` y no Kaggle: el plan original preveía sacar esto del CSV
`common_player_info.csv` del dataset de Kaggle (1 MB, una descarga, en vez de
~1.000 peticiones). Al comprobarlo, ese CSV solo cubría 628 de nuestros 1.030
jugadores — le faltaba el 39%, sobre todo novatos recientes. Como hacía falta
`nba_api` igualmente para el resto, usar una sola fuente sale más simple y
además elimina del proyecto la credencial de Kaggle y la atribución CC BY-SA.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import bindparam, select, update

from nbastats.db.models import IngestLog, Player
from nbastats.db.session import get_engine, session_scope
from nbastats.ingest.nba_client import NBAClient
from nbastats.ingest.transforms import (
    parse_birthdate,
    parse_height_to_cm,
    parse_weight_to_kg,
)

logger = logging.getLogger(__name__)


def _fetch_one(client: NBAClient, player_id: int) -> dict | None:
    from nba_api.stats.endpoints import commonplayerinfo

    rows = client._call(commonplayerinfo.CommonPlayerInfo, player_id=player_id)
    return rows[0] if rows else None


def _to_row(raw: dict[str, Any]) -> dict:
    return {
        "player_id": raw["PERSON_ID"],
        "birthdate": parse_birthdate(raw.get("BIRTHDATE")),
        "height_cm": parse_height_to_cm(raw.get("HEIGHT")),
        "weight_kg": parse_weight_to_kg(raw.get("WEIGHT")),
        "position": (raw.get("POSITION") or None),
        "country": (raw.get("COUNTRY") or None),
        "draft_year": _int_or_none(raw.get("DRAFT_YEAR")),
        "from_year": _int_or_none(raw.get("FROM_YEAR")),
        "to_year": _int_or_none(raw.get("TO_YEAR")),
        # --- Ficha ---
        "jersey_number": (str(raw["JERSEY"]).strip() or None) if raw.get("JERSEY") else None,
        "roster_status": (raw.get("ROSTERSTATUS") or None),
        "season_experience": _int_or_none(raw.get("SEASON_EXP")),
        "current_team_id": _team_or_none(raw.get("TEAM_ID")),
        "draft_round": _int_or_none(raw.get("DRAFT_ROUND")),
        "draft_number": _int_or_none(raw.get("DRAFT_NUMBER")),
        "school": (raw.get("SCHOOL") or None),
    }


def _team_or_none(value: Any) -> int | None:
    """TEAM_ID a clave ajena válida.

    La API devuelve `0` para agentes libres y retirados, no NULL. Insertarlo
    tal cual violaría la clave ajena contra `teams`, así que se traduce a None:
    "sin equipo" es exactamente lo que significa.
    """
    team_id = _int_or_none(value)
    return team_id or None


def _int_or_none(value: Any) -> int | None:
    """'2020' -> 2020; 'Undrafted' -> None."""
    if value in (None, "", "Undrafted"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ingest_player_bios(
    *, only_missing: bool = True, client: NBAClient | None = None
) -> dict[str, int]:
    """Descarga la biografía de los jugadores que ya están en la base.

    Args:
        only_missing: si True, solo pide los que no tienen `birthdate`. Hace que
            reejecutarlo sea barato y permite reanudar si se interrumpe.
    """
    client = client or NBAClient()

    with session_scope() as session:
        stmt = select(Player.player_id)
        if only_missing:
            # El criterio es "le falta ALGO", no solo la fecha de nacimiento:
            # los jugadores cargados antes de añadir los campos de ficha tienen
            # birthdate pero no roster_status, y hay que volver a pedirlos.
            stmt = stmt.where(
                Player.birthdate.is_(None) | Player.roster_status.is_(None)
            )
        pendientes = sorted(session.scalars(stmt).all())

    if not pendientes:
        logger.info("Todas las biografías están al día.")
        return {"pedidos": 0, "actualizados": 0, "fallidos": 0}

    logger.info(
        "Descargando %d biografías (~%.0f min)", len(pendientes), len(pendientes) * 0.75 / 60
    )

    actualizados = fallidos = 0
    lote: list[dict] = []

    for i, player_id in enumerate(pendientes, 1):
        try:
            raw = _fetch_one(client, player_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Biografía de %s falló: %s", player_id, exc)
            fallidos += 1
            continue

        if raw:
            lote.append(_to_row(raw))

        # Se vuelca cada 50 para que una interrupción no tire todo el trabajo:
        # con `only_missing=True` el siguiente intento retoma donde se quedó.
        if len(lote) >= 50 or i == len(pendientes):
            actualizados += _flush(lote)
            lote = []
            logger.info("  %d/%d", i, len(pendientes))

    with session_scope() as session:
        session.add(
            IngestLog(
                source="nba_api",
                endpoint="CommonPlayerInfo",
                params={"solicitados": len(pendientes)},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok" if not fallidos else "partial",
                rows_written=actualizados,
            )
        )

    logger.info("Biografías: %d actualizadas, %d fallidas", actualizados, fallidos)
    return {"pedidos": len(pendientes), "actualizados": actualizados, "fallidos": fallidos}


BIO_COLUMNS = (
    "birthdate", "height_cm", "weight_kg", "position",
    "country", "draft_year", "from_year", "to_year",
    "jersey_number", "roster_status", "season_experience",
    "current_team_id", "draft_round", "draft_number", "school",
)


def _flush(lote: list[dict]) -> int:
    """Escribe un lote actualizando SOLO las columnas de biografía.

    Es un UPDATE y no un UPSERT a propósito. Un UPSERT necesitaría aportar
    `full_name`, que es NOT NULL y aquí no se conoce: solo funcionaría mientras
    el jugador ya existiera, y fallaría de forma confusa el día que no. Estos
    jugadores salen de un SELECT sobre la propia tabla, así que el UPDATE es
    tanto más correcto como más claro. `full_name` lo mantiene la ingesta de
    box scores.
    """
    if not lote:
        return 0

    stmt = (
        update(Player)
        .where(Player.player_id == bindparam("b_player_id"))
        .values({c: bindparam(c) for c in BIO_COLUMNS})
    )
    params = [
        {**{c: fila.get(c) for c in BIO_COLUMNS}, "b_player_id": fila["player_id"]}
        for fila in lote
    ]

    # Conexión Core, no sesión ORM. Un UPDATE masivo con WHERE propio hace que
    # la sesión ORM intente sincronizar los objetos que tiene en memoria y falle
    # con "bulk synchronize of persistent objects not supported". Aquí no hay
    # ningún objeto ORM en juego —solo filas— así que la sesión no aportaba nada
    # y sí estorbaba.
    with get_engine().begin() as conn:
        conn.execute(stmt, params)
    return len(lote)
