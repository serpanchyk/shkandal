"""Remove persisted Case-to-Case relations."""

from collections.abc import Sequence

from alembic import op

revision: str = "202606230001"
down_revision: str | None = "202606170001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the obsolete relation table."""

    op.drop_table("case_relations")


def downgrade() -> None:
    """Reject reconstruction of discarded inferred relations."""

    raise NotImplementedError("removing persisted Case relations is intentionally irreversible")
