"""Add automatic Case audit pipeline state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606150001"
down_revision: str | None = "202606140001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("last_interest_audited_revision", "last_duplicate_audited_revision"):
        op.add_column(
            "cases", sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False)
        )
    for name in ("last_interest_audited_at", "last_duplicate_audited_at"):
        op.add_column("cases", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("merged_into_case_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_cases_merged_into_case_id_cases",
        "cases",
        "cases",
        ["merged_into_case_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "case_public_interest_audits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("evidence_revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome in ('keep', 'hide', 'inconclusive', 'superseded')",
            name="ck_case_public_interest_audits_outcome",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_case_public_interest_audits_case_id_created_at",
        "case_public_interest_audits",
        ["case_id", "created_at"],
    )
    op.create_table(
        "case_duplicate_audits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_a_id", sa.UUID(), nullable=False),
        sa.Column("case_b_id", sa.UUID(), nullable=False),
        sa.Column("case_a_revision", sa.Integer(), nullable=False),
        sa.Column("case_b_revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("case_a_id < case_b_id", name="ck_case_duplicate_audits_canonical_pair"),
        sa.CheckConstraint(
            "outcome in ('merge', 'related', 'distinct', 'inconclusive', 'superseded')",
            name="ck_case_duplicate_audits_outcome",
        ),
        sa.ForeignKeyConstraint(["case_a_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_b_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_case_duplicate_audits_case_a_id_created_at",
        "case_duplicate_audits",
        ["case_a_id", "created_at"],
    )
    op.create_index(
        "ix_case_duplicate_audits_case_b_id_created_at",
        "case_duplicate_audits",
        ["case_b_id", "created_at"],
    )
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_coherence_audit', "
        "'case_public_interest_audit', 'case_duplicate_audit')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_coherence_audit')",
    )
    op.drop_table("case_duplicate_audits")
    op.drop_table("case_public_interest_audits")
    op.drop_constraint("fk_cases_merged_into_case_id_cases", "cases", type_="foreignkey")
    for name in (
        "merged_into_case_id",
        "last_duplicate_audited_at",
        "last_interest_audited_at",
        "last_duplicate_audited_revision",
        "last_interest_audited_revision",
    ):
        op.drop_column("cases", name)
