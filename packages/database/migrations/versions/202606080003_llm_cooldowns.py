"""Add durable shared LLM cooldown state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606080003"
down_revision: str | None = "202606080002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.create_table(
        "llm_cooldowns",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resume_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scope"),
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_table("llm_cooldowns")
