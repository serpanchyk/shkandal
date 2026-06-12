"""Allow jobs with a Case subject and no Article subject."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606120003"
down_revision: str | None = "202606120002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make the Article subject nullable for Case-scoped jobs."""

    op.alter_column(
        "jobs",
        "article_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    """Keep Case-scoped jobs intact rather than deleting them."""

    raise NotImplementedError("case-scoped job nullability migration is irreversible")
