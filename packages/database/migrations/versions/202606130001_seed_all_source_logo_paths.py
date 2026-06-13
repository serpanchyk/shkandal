"""Seed PNG logo asset paths for all curated Sources."""

from collections.abc import Sequence

from alembic import op

revision: str = "202606130001"
down_revision: str | None = "202606120003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Point every existing Source at its frontend-owned PNG asset path."""

    op.execute("UPDATE sources SET logo_path = '/sources/' || slug || '.png'")


def downgrade() -> None:
    """Restore the previous five SVG paths and clear the other paths."""

    op.execute("UPDATE sources SET logo_path = NULL")
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
