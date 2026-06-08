"""Remove the duplicated case-candidate gate from article-card JSON."""

from collections.abc import Sequence

from alembic import op

revision: str = "202606080002"
down_revision: str | None = "202606080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute(
        """
        UPDATE article_cards
        SET card_json = card_json - 'is_case_candidate'
        WHERE card_json ? 'is_case_candidate'
        """
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        """
        UPDATE article_cards
        SET card_json = card_json || jsonb_build_object(
            'is_case_candidate',
            is_case_candidate
        )
        """
    )
