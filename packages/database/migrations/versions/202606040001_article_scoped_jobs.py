"""Make jobs article-scoped."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606040001"
down_revision: str | None = "202606020001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.add_column("jobs", sa.Column("article_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_article_id_articles",
        "jobs",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("jobs", "article_id", nullable=False)
    op.create_unique_constraint(
        "uq_jobs_job_type_article_id",
        "jobs",
        ["job_type", "article_id"],
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_constraint("uq_jobs_job_type_article_id", "jobs", type_="unique")
    op.drop_constraint("fk_jobs_article_id_articles", "jobs", type_="foreignkey")
    op.drop_column("jobs", "article_id")
