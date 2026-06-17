"""Add indexes for multi-field public Case search."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606170001"
down_revision: str | None = "202606160001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.create_index(
        "ix_cases_active_summary_uk_trgm",
        "cases",
        ["summary_uk"],
        postgresql_using="gin",
        postgresql_ops={"summary_uk": "gin_trgm_ops"},
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_entities_canonical_name_uk_trgm",
        "entities",
        ["canonical_name_uk"],
        postgresql_using="gin",
        postgresql_ops={"canonical_name_uk": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_entities_description_uk_trgm",
        "entities",
        ["description_uk"],
        postgresql_using="gin",
        postgresql_ops={"description_uk": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_events_title_uk_trgm",
        "events",
        ["title_uk"],
        postgresql_using="gin",
        postgresql_ops={"title_uk": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_events_description_uk_trgm",
        "events",
        ["description_uk"],
        postgresql_using="gin",
        postgresql_ops={"description_uk": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_events_location_uk_trgm",
        "events",
        ["location_uk"],
        postgresql_using="gin",
        postgresql_ops={"location_uk": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_index("ix_events_location_uk_trgm", table_name="events")
    op.drop_index("ix_events_description_uk_trgm", table_name="events")
    op.drop_index("ix_events_title_uk_trgm", table_name="events")
    op.drop_index("ix_entities_description_uk_trgm", table_name="entities")
    op.drop_index("ix_entities_canonical_name_uk_trgm", table_name="entities")
    op.drop_index("ix_cases_active_summary_uk_trgm", table_name="cases")
