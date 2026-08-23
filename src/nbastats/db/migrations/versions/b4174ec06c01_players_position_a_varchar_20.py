"""players.position a varchar(20)

La NBA no usa códigos cortos ("PG", "SF") sino palabras completas con guion:
"Center-Forward" son 14 caracteres y reventaba el VARCHAR(10) original.

NOTA: el autogenerate original incluía además un `op.drop_index` sobre
`ix_players_name_unaccent`. Se ha eliminado a mano. Ese índice lo crea la
migración `1ccc5986f032` con SQL crudo, así que no existe en los modelos y
autogenerate lo interpreta como sobrante. Se ha añadido un filtro
`include_object` en `env.py` para que no vuelva a proponerlo.

Revision ID: b4174ec06c01
Revises: 1ccc5986f032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4174ec06c01"
down_revision: str | Sequence[str] | None = "1ccc5986f032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "players", "position",
        existing_type=sa.VARCHAR(length=10),
        type_=sa.String(length=20),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "players", "position",
        existing_type=sa.String(length=20),
        type_=sa.VARCHAR(length=10),
        existing_nullable=True,
    )
