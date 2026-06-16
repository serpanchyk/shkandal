"""Add case link audit LLM run type."""

from collections.abc import Sequence

from alembic import op

revision: str = "202606160001"
down_revision: str | None = "202606150001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_link_audit', "
        "'case_coherence_audit', 'case_public_interest_audit', 'case_duplicate_audit')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_coherence_audit', "
        "'case_public_interest_audit', 'case_duplicate_audit')",
    )
