"""Enriquecido de `games` con datos que los game logs no traen.

`PlayerGameLogs` y `TeamGameLogs` dan los box scores pero no la hora de salto
inicial ni marcan las sedes neutrales. `ScoreboardV3` sí, a costa de una
petición por FECHA (no por partido): ~900 fechas para 5 temporadas, unos 10
minutos una sola vez.

Aporta tres cosas:

1. **`tipoff_utc`** — habilita preguntas sobre horario ("¿rinde peor en partidos
   nocturnos?"), de la misma familia que los splits por día de la semana.

2. **`is_neutral_site` fiable** — la detección de `bulk.py` (los dos equipos
   marcados con `@` en MATCHUP) solo funciona desde 2024-25. Aquí se combinan
   todas las señales disponibles.

3. **`game_label` / `game_sublabel`** — el tipo real del partido tal cual lo
   publica la NBA: 'Emirates NBA Cup' + 'East Group C', 'NBA Paris Game'. Sin
   esto no se puede distinguir un partido de la NBA Cup de uno cualquiera de
   temporada regular, porque a efectos de clasificación **son lo mismo**.

LÍMITE CONOCIDO: en 2022-23 la API no expone ninguna señal de sede neutral —
ni `isNeutral`, ni `gameLabel`, ni MATCHUP. Los partidos internacionales de esa
temporada (hubo uno en Ciudad de México y otro en París) quedan sin marcar. Se
documenta en vez de codificarlos a mano: marcar partidos de memoria, sin que el
dato lo respalde, es peor que un hueco conocido.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from sqlalchemy import select, update

from nbastats.db.models import Game
from nbastats.db.session import session_scope
from nbastats.ingest.nba_client import NBAClient

logger = logging.getLogger(__name__)

# Los partidos internacionales llevan el nombre de la ciudad en `gameLabel`
# ("NBA Paris Game", "NBA Mexico City Game"). El patrón busca la ciudad y no la
# palabra "NBA", que aparece en etiquetas de partidos normales.
_CIUDADES_NEUTRALES = re.compile(
    r"\b(paris|mexico\s*city|london|berlin|abu\s*dhabi|tokyo|macau|"
    r"shanghai|beijing|vancouver|montreal|seattle)\b",
    re.IGNORECASE,
)

# Las eliminatorias de la NBA Cup se juegan en Las Vegas SOLO a partir de
# semifinales: los cuartos se disputan en la pista del mejor clasificado y por
# tanto NO son sede neutral.
#
# Los `\b` no son decorativos. Sin ellos, "final" casa dentro de
# "Quarterfinal" y los 4 cuartos de cada temporada se marcaban como neutrales
# — contradiciendo al propio `isNeutral=False` que devuelve la API para ellos.
# Una heurística que pisa un dato directo de la fuente es peor que no tenerla.
_RONDA_EN_LAS_VEGAS = re.compile(r"\b(semifinal|championship)\b", re.IGNORECASE)


def is_neutral_site(game: dict) -> bool:
    """Decide si un partido del scoreboard se jugó en sede neutral."""
    # Señal directa. Solo poblada desde 2024-25.
    if game.get("isNeutral"):
        return True

    if _CIUDADES_NEUTRALES.search(game.get("gameLabel") or ""):
        return True

    return game.get("gameSubtype") == "in-season-knockout" and bool(
        _RONDA_EN_LAS_VEGAS.search(game.get("gameSubLabel") or "")
    )


def _parse_utc(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def enrich_games(
    *, only_missing: bool = True, client: NBAClient | None = None
) -> dict[str, int]:
    """Rellena `tipoff_utc` y refina `is_neutral_site` en todos los partidos.

    Args:
        only_missing: si True, solo consulta fechas con algún partido sin
            `tipoff_utc`. Hace que reejecutarlo sea barato.
    """
    client = client or NBAClient()

    with session_scope() as session:
        stmt = select(Game.game_date_local).distinct()
        if only_missing:
            stmt = stmt.where(Game.tipoff_utc.is_(None))
            # Nota: este filtro NO detecta partidos a los que solo les falta la
            # etiqueta, porque `game_label` es NULL de forma legítima en la
            # inmensa mayoría (un partido normal no lleva etiqueta). Para
            # rellenar etiquetas en datos ya cargados hay que usar
            # `only_missing=False`.
        fechas = sorted(session.scalars(stmt).all())

    if not fechas:
        logger.info("Nada que enriquecer.")
        return {"fechas": 0, "partidos": 0, "neutrales": 0, "sin_encontrar": 0}

    logger.info("Enriqueciendo %d fechas (~%.0f min)", len(fechas), len(fechas) * 0.75 / 60)

    total = neutrales = sin_encontrar = 0

    for i, fecha in enumerate(fechas, 1):
        try:
            juegos = client.scoreboard(fecha.isoformat())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scoreboard %s falló: %s", fecha, exc)
            continue

        actualizaciones = []
        for g in juegos:
            actualizaciones.append(
                {
                    "gid": g["gameId"],
                    "tipoff_utc": _parse_utc(g.get("gameTimeUTC")),
                    "is_neutral_site": is_neutral_site(g),
                    "game_label": (g.get("gameLabel") or "").strip() or None,
                    "game_sublabel": (g.get("gameSubLabel") or "").strip() or None,
                }
            )

        with session_scope() as session:
            for u in actualizaciones:
                # Solo se ASCIENDE a neutral, nunca se degrada: bulk.py ya
                # detectó algunos por MATCHUP y esa señal es igual de válida.
                res = session.execute(
                    update(Game)
                    .where(Game.game_id == u["gid"])
                    .values(
                        tipoff_utc=u["tipoff_utc"],
                        is_neutral_site=Game.is_neutral_site | u["is_neutral_site"],
                        game_label=u["game_label"],
                        game_sublabel=u["game_sublabel"],
                    )
                )
                if res.rowcount:
                    total += 1
                    if u["is_neutral_site"]:
                        neutrales += 1
                else:
                    sin_encontrar += 1

        if i % 100 == 0:
            logger.info("  %d/%d fechas, %d partidos actualizados", i, len(fechas), total)

    logger.info(
        "Enriquecido: %d fechas, %d partidos, %d neutrales, %d no encontrados",
        len(fechas), total, neutrales, sin_encontrar,
    )
    return {
        "fechas": len(fechas),
        "partidos": total,
        "neutrales": neutrales,
        "sin_encontrar": sin_encontrar,
    }
