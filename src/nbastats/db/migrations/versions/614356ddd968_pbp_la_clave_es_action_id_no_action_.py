"""pbp la clave es action_id no action_number

La clave primaria del play-by-play era (game_id, action_number) y estaba mal.
Los eventos LIGADOS comparten `action_number`: un tiro fallado y el tapón que lo
causó llegan con el mismo número y el mismo reloj, y solo `action_id` los
separa. Medido sobre un partido real: 577 eventos, 577 `action_id` distintos,
543 `action_number`.

Se recrea la tabla en vez de parchear la clave porque está vacía —el fallo se
detectó en la primera prueba de carga— y así el esquema queda igual que si
hubiera nacido bien.

Revision ID: 614356ddd968
Revises: 85c21923449f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "614356ddd968"
down_revision: str | Sequence[str] | None = "85c21923449f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("play_by_play")
    op.create_table(
        "play_by_play",
        sa.Column("game_id", sa.String(length=20), nullable=False),
        sa.Column("action_id", sa.SmallInteger(), nullable=False),
        sa.Column("action_number", sa.SmallInteger(), nullable=True),
        sa.Column("period", sa.SmallInteger(), nullable=False),
        sa.Column("clock_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("elapsed_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("player_id", sa.BigInteger(), nullable=True),
        sa.Column("action_type", sa.String(length=30), nullable=True),
        sa.Column("sub_type", sa.String(length=40), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("score_home", sa.SmallInteger(), nullable=True),
        sa.Column("score_away", sa.SmallInteger(), nullable=True),
        sa.Column("is_field_goal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("shot_result", sa.Boolean(), nullable=True),
        sa.Column("shot_value", sa.SmallInteger(), nullable=True),
        sa.Column("shot_distance", sa.SmallInteger(), nullable=True),
        sa.Column("x_legacy", sa.SmallInteger(), nullable=True),
        sa.Column("y_legacy", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("period >= 1", name="ck_pbp_period_positivo"),
        sa.ForeignKeyConstraint(["game_id"], ["games.game_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"]),
        sa.PrimaryKeyConstraint("game_id", "action_id"),
    )
    op.create_index(
        "ix_pbp_tiros",
        "play_by_play",
        ["player_id", "shot_result"],
        unique=False,
        postgresql_where=sa.text("is_field_goal"),
    )


def downgrade() -> None:
    op.drop_index("ix_pbp_tiros", table_name="play_by_play")
    op.drop_table("play_by_play")
