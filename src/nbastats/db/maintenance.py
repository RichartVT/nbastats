"""Pasos posteriores a la carga: columnas derivadas y vistas materializadas.

Se ejecutan siempre en este orden, y siempre después de ingerir:

    1. compute_derived_columns()  — rest_days, back-to-back
    2. rebuild_views()            — recrea las vistas (tras cambios de esquema)
       o refresh_views()          — las repuebla (uso diario)

El orden importa: las vistas leen `rest_days`, así que refrescarlas antes de
calcularlo dejaría esa columna a NULL en toda la capa analítica.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from nbastats.db.session import get_engine

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent / "sql"

# En orden de dependencia: cada una lee de la anterior.
MATERIALIZED_VIEWS = (
    "mv_player_game_rates",
    "mv_player_season",
    "mv_league_season_baselines",
    "mv_team_game_rates",
)


def _read_sql(name: str) -> str:
    path = SQL_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"No existe el fichero SQL: {path}")
    return path.read_text(encoding="utf-8")


def compute_derived_columns() -> int:
    """Calcula rest_days e is_back_to_back sobre team_game_stats.

    Se recalcula entero en lugar de incrementalmente: son ~13.000 filas, tarda
    milisegundos, y hacerlo completo lo vuelve idempotente y a prueba de
    partidos que llegan desordenados o corregidos.
    """
    with get_engine().begin() as conn:
        result = conn.execute(text(_read_sql("derive.sql")))
        updated = result.rowcount or 0
    logger.info("Columnas derivadas actualizadas en %d filas", updated)
    return updated


def rebuild_views() -> None:
    """Recrea las vistas materializadas desde cero (DROP + CREATE).

    Es lo que hay que usar tras cambiar el esquema o la definición de una
    vista. Para el uso diario basta con `refresh_views`, que es mucho más
    rápido.
    """
    with get_engine().begin() as conn:
        conn.execute(text(_read_sql("views.sql")))
    logger.info("Vistas materializadas recreadas: %s", ", ".join(MATERIALIZED_VIEWS))


def refresh_views(*, concurrently: bool = True) -> None:
    """Repuebla las vistas con los datos actuales.

    `CONCURRENTLY` permite que la API siga sirviendo lecturas durante el
    refresco, a cambio de tardar más. Requiere que la vista ya esté poblada y
    tenga índice único — si no lo está, cae al refresco bloqueante, que es lo
    correcto la primera vez.
    """
    engine = get_engine()
    for view in MATERIALIZED_VIEWS:
        modo = "CONCURRENTLY " if concurrently else ""
        try:
            with engine.begin() as conn:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW {modo}{view}"))
        except Exception:
            if not concurrently:
                raise
            logger.warning(
                "Refresco concurrente de %s no disponible (¿primera carga?); "
                "se refresca de forma bloqueante",
                view,
            )
            with engine.begin() as conn:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
        logger.info("Vista refrescada: %s", view)


def rebuild_all() -> None:
    """Secuencia completa post-carga, en el orden correcto."""
    compute_derived_columns()
    rebuild_views()
