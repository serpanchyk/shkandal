"""Expand supported source types."""

from collections.abc import Sequence

from alembic import op

revision: str = "202606020001"
down_revision: str | None = "202606010002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.drop_constraint("ck_sources_source_type", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_source_type",
        "sources",
        "source_type in ("
        "'media', 'institution', 'court', 'ngo', 'other', "
        "'government', 'parliament', 'law_enforcement'"
        ")",
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_constraint("ck_sources_source_type", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_source_type",
        "sources",
        "source_type in ('media', 'institution', 'court', 'ngo', 'other')",
    )
