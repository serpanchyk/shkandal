"""Allow unresolved LLM model names."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606250001"
down_revision: str | None = "202606230001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow pending and pre-response failed runs to have no resolved model."""

    op.alter_column("llm_runs", "model_name", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Restore the required model name after rejecting unresolved rows."""

    op.execute("UPDATE llm_runs SET model_name = 'unknown' WHERE model_name IS NULL")
    op.alter_column("llm_runs", "model_name", existing_type=sa.Text(), nullable=False)
