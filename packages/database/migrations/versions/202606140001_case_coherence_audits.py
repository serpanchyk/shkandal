"""Add recurring Case coherence audit state and history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606140001"
down_revision: str | None = "202606130001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add audit revisions, history, and the new LLM run type."""

    op.add_column(
        "cases",
        sa.Column("evidence_revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "cases",
        sa.Column(
            "last_audited_revision",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "cases",
        sa.Column("last_audited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_coherence_audit')",
    )
    op.create_table(
        "case_coherence_audits",
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
            "outcome in ('coherent', 'split', 'inconclusive', 'superseded')",
            name="ck_case_coherence_audits_outcome",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_case_coherence_audits_case_id_created_at",
        "case_coherence_audits",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    """Remove Case coherence audit state."""

    op.drop_index(
        "ix_case_coherence_audits_case_id_created_at",
        table_name="case_coherence_audits",
    )
    op.drop_table("case_coherence_audits")
    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update')",
    )
    op.drop_column("cases", "last_audited_at")
    op.drop_column("cases", "last_audited_revision")
    op.drop_column("cases", "evidence_revision")
