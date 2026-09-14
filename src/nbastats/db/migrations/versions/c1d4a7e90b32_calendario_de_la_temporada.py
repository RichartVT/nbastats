"""calendario de la temporada

Revision ID: c1d4a7e90b32
Revises: 2612b461266d
Create Date: 2026-09-13 18:40:00.000000

Tabla `scheduled_games`: los partidos ANUNCIADOS, aparte de `games`, que son
los jugados. El porqué de la separación está en el docstring del modelo.

Escrita a mano y no autogenerada por un detalle que el autogenerate hace mal:
el tipo `season_type` ya existe en la base desde la migración inicial, así que
la columna se declara con `create_type=False`. Sin eso, la migración intenta
crear un enum que ya está y falla.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c1d4a7e90b32"
down_revision: Union[str, Sequence[str], None] = "2612b461266d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    season_type = postgresql.ENUM(
        "regular", "playin", "playoffs", "preseason",
        name="season_type",
        create_type=False,
    )

    op.create_table(
        "scheduled_games",
        sa.Column("game_id", sa.String(length=20), nullable=False),
        sa.Column("season_id", sa.String(length=7), nullable=False),
        # Nullable: la final de la NBA Cup y el All-Star van en el calendario y
        # no son una fase de la temporada.
        sa.Column("season_type", season_type, nullable=True),
        sa.Column("game_date_local", sa.Date(), nullable=False),
        sa.Column("tipoff_utc", sa.DateTime(timezone=True), nullable=True),
        # Nullables: los cruces de la NBA Cup se publican con los dos equipos
        # por determinar y se rellenan en diciembre.
        sa.Column("home_team_id", sa.BigInteger(), nullable=True),
        sa.Column("away_team_id", sa.BigInteger(), nullable=True),
        sa.Column("arena_name", sa.String(length=100), nullable=True),
        sa.Column("arena_city", sa.String(length=60), nullable=True),
        sa.Column(
            "is_neutral_site",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("game_label", sa.String(length=60), nullable=True),
        sa.Column("game_sublabel", sa.String(length=40), nullable=True),
        sa.Column("week_number", sa.SmallInteger(), nullable=True),
        sa.Column("game_status", sa.SmallInteger(), nullable=True),
        sa.Column("postponed_status", sa.String(length=4), nullable=True),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.team_id"]),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.team_id"]),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.season_id"]),
        sa.PrimaryKeyConstraint("game_id"),
    )
    op.create_index(
        "ix_sched_away", "scheduled_games", ["away_team_id", "game_date_local"]
    )
    op.create_index(
        "ix_sched_home", "scheduled_games", ["home_team_id", "game_date_local"]
    )
    op.create_index(
        "ix_sched_season_date", "scheduled_games", ["season_id", "game_date_local"]
    )
    op.create_index(
        op.f("ix_scheduled_games_season_id"), "scheduled_games", ["season_id"]
    )
    op.create_index(
        op.f("ix_scheduled_games_season_type"), "scheduled_games", ["season_type"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_scheduled_games_season_type"), table_name="scheduled_games")
    op.drop_index(op.f("ix_scheduled_games_season_id"), table_name="scheduled_games")
    op.drop_index("ix_sched_season_date", table_name="scheduled_games")
    op.drop_index("ix_sched_home", table_name="scheduled_games")
    op.drop_index("ix_sched_away", table_name="scheduled_games")
    op.drop_table("scheduled_games")
    # El tipo `season_type` NO se borra: es de la migración inicial y lo usan
    # `games` y otras tablas.
