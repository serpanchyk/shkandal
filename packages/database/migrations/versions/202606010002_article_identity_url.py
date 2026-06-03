"""Use identity URL for articles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606010002"
down_revision: str | None = "202606010001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.drop_index("ix_articles_canonical_url", table_name="articles")
    op.drop_constraint("articles_normalized_url_key", "articles", type_="unique")
    op.alter_column("articles", "normalized_url", new_column_name="identity_url")
    op.create_unique_constraint("uq_articles_identity_url", "articles", ["identity_url"])
    op.drop_column("articles", "canonical_url")


def downgrade() -> None:
    """Revert the migration."""

    op.add_column("articles", sa.Column("canonical_url", sa.Text(), nullable=True))
    op.execute("UPDATE articles SET canonical_url = url")
    op.alter_column("articles", "canonical_url", nullable=False)
    op.drop_constraint("uq_articles_identity_url", "articles", type_="unique")
    op.alter_column("articles", "identity_url", new_column_name="normalized_url")
    op.create_unique_constraint("articles_normalized_url_key", "articles", ["normalized_url"])
    op.create_index("ix_articles_canonical_url", "articles", ["canonical_url"])
