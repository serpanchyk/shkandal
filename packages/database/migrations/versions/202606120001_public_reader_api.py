"""Add public-reader search and Source logo metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606120001"
down_revision: str | None = "202606100003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column("sources", sa.Column("logo_path", sa.Text(), nullable=True))
    op.create_index(
        "ix_cases_active_title_uk_trgm",
        "cases",
        ["title_uk"],
        postgresql_using="gin",
        postgresql_ops={"title_uk": "gin_trgm_ops"},
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_case_articles_case_id_article_id",
        "case_articles",
        ["case_id", "article_id"],
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_index("ix_case_articles_case_id_article_id", table_name="case_articles")
    op.drop_index("ix_cases_active_title_uk_trgm", table_name="cases")
    op.drop_column("sources", "logo_path")
