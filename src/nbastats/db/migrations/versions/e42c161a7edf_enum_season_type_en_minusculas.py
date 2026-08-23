"""enum season_type en minusculas

SQLAlchemy guarda por defecto los NOMBRES de los miembros del enum ('REGULAR'),
no sus valores ('regular'). Eso obligaba a escribir el SQL a mano en mayúsculas
mientras la API serializaba en minúsculas — dos vocabularios para lo mismo.

Se renombran las etiquetas del tipo en lugar de recrearlo: RENAME VALUE conserva
los datos existentes, así que la migración sirve igual con la base vacía que
llena.

Revision ID: e42c161a7edf
Revises: 8077332637e1
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e42c161a7edf"
down_revision: str | Sequence[str] | None = "8077332637e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABELS = [
    ("REGULAR", "regular"),
    ("PLAYIN", "playin"),
    ("PLAYOFFS", "playoffs"),
    ("PRESEASON", "preseason"),
]


def upgrade() -> None:
    for old, new in _LABELS:
        op.execute(f"ALTER TYPE season_type RENAME VALUE '{old}' TO '{new}'")


def downgrade() -> None:
    for old, new in _LABELS:
        op.execute(f"ALTER TYPE season_type RENAME VALUE '{new}' TO '{old}'")
