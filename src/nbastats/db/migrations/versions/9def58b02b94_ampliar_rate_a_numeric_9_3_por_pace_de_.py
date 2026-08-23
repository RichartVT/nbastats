"""ampliar Rate a numeric(9,3) por pace de jugador

El `pace` a nivel de JUGADOR es una extrapolación a 48 minutos. Con estancias de
segundos se dispara: se observó 14.400 en un jugador con 0,5 minutos y 1
posesión, lo que reventaba el `numeric(7,3)` original. Es un valor real de la
fuente, no un error de escala, así que se ensancha la columna en vez de
alterarlo. `CAPABILITIES.md` avisa de que no es interpretable con pocos minutos.

PATRÓN PARA MIGRACIONES QUE TOCAN TIPOS DE COLUMNA:
Postgres rechaza `ALTER COLUMN TYPE` si una vista materializada depende de la
columna. Como las vistas son artefactos derivados —no fuente de verdad— la
migración las suelta y NO las recrea; se reconstruyen después con
`nbastats.db.maintenance.rebuild_views()`, que siempre parte de la definición
vigente en `db/sql/views.sql`. Embeber aquí una copia del SQL de las vistas
crearía una segunda fuente de verdad que se desincronizaría.

El comando `nbastats setup` encadena las dos cosas en el orden correcto.

Revision ID: 9def58b02b94
Revises: e42c161a7edf
Create Date: 2026-08-23 00:24:15.182955
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9def58b02b94"
down_revision: str | Sequence[str] | None = "e42c161a7edf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (tabla, columna) de todo lo tipado como `Rate` en models.py
_RATE_COLUMNS = [
    ("player_game_advanced", "off_rating"),
    ("player_game_advanced", "def_rating"),
    ("player_game_advanced", "net_rating"),
    ("player_game_advanced", "pace"),
    ("team_game_stats", "possessions"),
    ("team_game_stats", "pace"),
    ("team_game_stats", "off_rating"),
    ("team_game_stats", "def_rating"),
    ("team_game_stats", "net_rating"),
]

# En orden inverso de dependencia.
_VIEWS = [
    "mv_league_season_baselines",
    "mv_player_season",
    "mv_player_game_rates",
]


def _drop_views() -> None:
    for view in _VIEWS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE")


def _retype(precision: int, existing: int) -> None:
    for table, column in _RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.NUMERIC(precision=existing, scale=3),
            type_=sa.Numeric(precision=precision, scale=3),
            existing_nullable=True,
        )


def upgrade() -> None:
    _drop_views()
    _retype(precision=9, existing=7)


def downgrade() -> None:
    _drop_views()
    _retype(precision=7, existing=9)
