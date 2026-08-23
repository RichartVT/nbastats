"""extension unaccent para buscar nombres acentuados

Sin esto, buscar "Jokic" no encuentra a "Nikola Jokić", ni "Doncic" a "Dončić",
ni "Sengun" a "Şengün". La NBA tiene decenas de jugadores con diacríticos y
nadie los teclea al buscar.

`unaccent` viene en contrib de PostgreSQL, así que no hay que instalar nada
aparte: la imagen oficial ya lo trae.

El índice funcional sobre `unaccent(full_name)` se declara IMMUTABLE mediante
una función envoltorio propia. `unaccent()` es STABLE y no VOLATILE porque
depende del diccionario cargado, y Postgres no admite funciones no inmutables
en un índice. Envolverla es el patrón estándar y es seguro mientras no se
cambie el diccionario en caliente.

Revision ID: 1ccc5986f032
Revises: 5b89eed404bd
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1ccc5986f032"
down_revision: str | Sequence[str] | None = "5b89eed404bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.execute("""
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent', $1) $$
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_players_name_unaccent
        ON players (lower(immutable_unaccent(full_name)) text_pattern_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_players_name_unaccent")
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
    # La extensión no se elimina: puede haber otros objetos que dependan de ella.
