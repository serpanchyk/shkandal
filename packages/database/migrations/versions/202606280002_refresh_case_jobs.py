"""Rename Case copy updates to Case refreshes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606280002"
down_revision: str | None = "202606280001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RUN_TYPE_VALUES = (
    "'article_gate', 'article_card', 'case_resolution', 'entity_resolution', "
    "'event_resolution', 'refresh_case', 'case_link_audit', 'case_coherence_audit', "
    "'case_public_interest_audit', 'case_duplicate_audit'"
)
DOWN_RUN_TYPE_VALUES = (
    "'article_gate', 'article_card', 'case_resolution', 'entity_resolution', "
    "'event_resolution', 'case_copy_update', 'case_link_audit', 'case_coherence_audit', "
    "'case_public_interest_audit', 'case_duplicate_audit'"
)


def upgrade() -> None:
    """Persist the Case Refresh name and track refreshed evidence counts."""

    op.add_column(
        "cases",
        sa.Column(
            "last_refreshed_article_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE cases
        SET last_refreshed_article_count = article_count
        WHERE summary_uk IS NOT NULL AND length(trim(summary_uk)) > 0
        """
    )
    op.execute("UPDATE jobs SET job_type = 'refresh_case' WHERE job_type = 'update_case_copy'")
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.execute("UPDATE llm_runs SET run_type = 'refresh_case' WHERE run_type = 'case_copy_update'")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        f"run_type in ({RUN_TYPE_VALUES})",
    )


def downgrade() -> None:
    """Restore the previous Case copy update naming."""

    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.execute("UPDATE llm_runs SET run_type = 'case_copy_update' WHERE run_type = 'refresh_case'")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        f"run_type in ({DOWN_RUN_TYPE_VALUES})",
    )
    op.execute("UPDATE jobs SET job_type = 'update_case_copy' WHERE job_type = 'refresh_case'")
    op.drop_column("cases", "last_refreshed_article_count")
