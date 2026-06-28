"""Add article gate decision timestamp defaults."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606280003"
down_revision: str | None = "202606280002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make article gate decision timestamps match model metadata."""

    op.alter_column(
        "article_gate_decisions",
        "created_at",
        server_default=sa.text("now()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "article_gate_decisions",
        "updated_at",
        server_default=sa.text("now()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Remove article gate decision timestamp defaults."""

    op.alter_column(
        "article_gate_decisions",
        "updated_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "article_gate_decisions",
        "created_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
