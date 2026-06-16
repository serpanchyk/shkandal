"""Add a queryable article-card case-candidate gate."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606080001"
down_revision: str | None = "202606060001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.add_column(
        "article_cards",
        sa.Column("is_case_candidate", sa.Boolean(), nullable=True),
    )
    op.execute(
        """
        UPDATE article_cards
        SET is_case_candidate = coalesce(
            (card_json ->> 'is_case_candidate')::boolean,
            false
        )
        """
    )
    op.alter_column("article_cards", "is_case_candidate", nullable=False)
    op.create_index(
        "ix_article_cards_is_case_candidate",
        "article_cards",
        ["is_case_candidate"],
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_index("ix_article_cards_is_case_candidate", table_name="article_cards")
    op.drop_column("article_cards", "is_case_candidate")
