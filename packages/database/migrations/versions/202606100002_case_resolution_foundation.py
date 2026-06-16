"""Add symmetric case relations and case-scoped jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606100002"
down_revision: str | None = "202606100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM case_relations WHERE relation_type = 'parent_child'
            ) THEN
                RAISE EXCEPTION
                    'cannot remove parent_child relations while rows still exist';
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_case_relations_target_case_id_relation_type", table_name="case_relations")
    op.drop_constraint("uq_case_relations_source_target_type", "case_relations", type_="unique")
    op.drop_constraint("ck_case_relations_not_self", "case_relations", type_="check")
    op.drop_constraint("ck_case_relations_relation_type", "case_relations", type_="check")
    op.alter_column("case_relations", "source_case_id", new_column_name="case_a_id")
    op.alter_column("case_relations", "target_case_id", new_column_name="case_b_id")
    op.execute(
        """
        UPDATE case_relations
        SET case_a_id = LEAST(case_a_id, case_b_id),
            case_b_id = GREATEST(case_a_id, case_b_id)
        """
    )
    op.create_check_constraint(
        "ck_case_relations_canonical_pair",
        "case_relations",
        "case_a_id < case_b_id",
    )
    op.create_check_constraint(
        "ck_case_relations_relation_type",
        "case_relations",
        "relation_type in ('related', 'possible_duplicate')",
    )
    op.create_unique_constraint(
        "uq_case_relations_pair_type",
        "case_relations",
        ["case_a_id", "case_b_id", "relation_type"],
    )
    op.create_index(
        "ix_case_relations_case_b_id_relation_type",
        "case_relations",
        ["case_b_id", "relation_type"],
    )

    op.drop_constraint("uq_jobs_job_type_article_id", "jobs", type_="unique")
    op.add_column("jobs", sa.Column("case_id", sa.UUID(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("requested_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "jobs",
        sa.Column("completed_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_jobs_case_id_cases",
        "jobs",
        "cases",
        ["case_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_jobs_exactly_one_subject",
        "jobs",
        "(article_id IS NOT NULL AND case_id IS NULL) OR "
        "(article_id IS NULL AND case_id IS NOT NULL)",
    )
    op.create_index(
        "uq_jobs_job_type_article_id",
        "jobs",
        ["job_type", "article_id"],
        unique=True,
        postgresql_where=sa.text("article_id IS NOT NULL"),
    )
    op.create_index(
        "uq_jobs_job_type_case_id",
        "jobs",
        ["job_type", "case_id"],
        unique=True,
        postgresql_where=sa.text("case_id IS NOT NULL"),
    )
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update')",
    )


def downgrade() -> None:
    """Revert the migration."""

    raise NotImplementedError("case resolution foundation migration is intentionally irreversible")
