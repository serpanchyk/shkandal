"""Track LLM cooldown classification and ambiguous observations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606100001"
down_revision: str | None = "202606080003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.add_column(
        "llm_cooldowns",
        sa.Column(
            "cooldown_kind",
            sa.Text(),
            server_default="provider_long",
            nullable=False,
        ),
    )
    op.add_column(
        "llm_cooldowns",
        sa.Column(
            "ambiguous_observation_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "llm_cooldowns",
        sa.Column("last_ambiguous_observed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_column("llm_cooldowns", "last_ambiguous_observed_at")
    op.drop_column("llm_cooldowns", "ambiguous_observation_count")
    op.drop_column("llm_cooldowns", "cooldown_kind")
