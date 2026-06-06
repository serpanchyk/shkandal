"""Add durable article fetch retry state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606060001"
down_revision: str | None = "202606050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.add_column(
        "articles",
        sa.Column(
            "fetch_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'succeeded'"),
        ),
    )
    op.add_column(
        "articles",
        sa.Column(
            "fetch_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column("articles", sa.Column("next_fetch_at", sa.DateTime(timezone=True)))
    op.add_column("articles", sa.Column("last_fetch_error", sa.Text()))
    op.create_check_constraint(
        "ck_articles_fetch_status",
        "articles",
        "fetch_status in ('succeeded', 'failed')",
    )
    op.create_index(
        "ix_articles_fetch_retry",
        "articles",
        ["fetch_status", "next_fetch_at"],
    )
    op.execute(
        """
        UPDATE articles
        SET fetch_status = 'failed',
            next_fetch_at = now(),
            last_fetch_error = coalesce(
                source_metadata ->> 'fetch_error',
                'missing_raw_html_and_extracted_text'
            )
        WHERE raw_html IS NULL
          AND extracted_text IS NULL
        """
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_index("ix_articles_fetch_retry", table_name="articles")
    op.drop_constraint("ck_articles_fetch_status", "articles", type_="check")
    op.drop_column("articles", "last_fetch_error")
    op.drop_column("articles", "next_fetch_at")
    op.drop_column("articles", "fetch_attempt_count")
    op.drop_column("articles", "fetch_status")
