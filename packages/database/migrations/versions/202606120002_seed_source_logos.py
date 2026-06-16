"""Seed curated Source logo asset paths."""

from collections.abc import Sequence

from alembic import op

revision: str = "202606120002"
down_revision: str | None = "202606120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute(
        """
        UPDATE sources
        SET logo_path = CASE slug
            WHEN 'pravda' THEN '/sources/pravda.svg'
            WHEN 'hromadske' THEN '/sources/hromadske.svg'
            WHEN 'radiosvoboda' THEN '/sources/radiosvoboda.svg'
            WHEN 'suspilne' THEN '/sources/suspilne.svg'
            WHEN 'bihus' THEN '/sources/bihus.svg'
        END
        WHERE slug IN ('pravda', 'hromadske', 'radiosvoboda', 'suspilne', 'bihus')
        """
    )


def downgrade() -> None:
    """Revert seeded logo paths."""

    op.execute(
        """
        UPDATE sources
        SET logo_path = NULL
        WHERE slug IN ('pravda', 'hromadske', 'radiosvoboda', 'suspilne', 'bihus')
        """
    )
