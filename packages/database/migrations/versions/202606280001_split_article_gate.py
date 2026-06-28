"""Split article gate decisions from article cards."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606280001"
down_revision: str | None = "202606250001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable article gate decisions and keep cards for accepted gates."""

    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_gate', 'article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_link_audit', 'case_coherence_audit', "
        "'case_public_interest_audit', 'case_duplicate_audit')",
    )

    op.create_table(
        "article_gate_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("llm_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_case_candidate", sa.Boolean(), nullable=False),
        sa.Column("noise_reason", sa.Text(), nullable=True),
        sa.Column("case_diagnosis", postgresql.JSONB(), nullable=False),
        sa.Column("case_decision_reason_uk", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id"),
    )
    op.create_index(
        "ix_article_gate_decisions_is_case_candidate_created_at",
        "article_gate_decisions",
        ["is_case_candidate", "created_at"],
    )

    op.execute(
        """
        INSERT INTO article_gate_decisions (
            id,
            article_id,
            llm_run_id,
            is_case_candidate,
            noise_reason,
            case_diagnosis,
            case_decision_reason_uk,
            metadata,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            article_id,
            llm_run_id,
            is_case_candidate,
            card_json->>'noise_reason',
            COALESCE(card_json->'case_diagnosis', '{}'::jsonb),
            card_json->>'case_decision_reason_uk',
            jsonb_build_object('migrated_from_article_card', true),
            created_at,
            updated_at
        FROM article_cards
        """
    )

    op.execute("DELETE FROM article_cards WHERE is_case_candidate IS false")
    op.execute(
        """
        UPDATE article_cards
        SET card_json = card_json
            - 'case_diagnosis'
            - 'noise_reason'
            - 'case_decision_reason_uk'
        """
    )
    op.drop_index("ix_article_cards_is_case_candidate", table_name="article_cards")
    op.drop_column("article_cards", "is_case_candidate")


def downgrade() -> None:
    """Restore the former combined article-card gate shape best-effort."""

    op.add_column(
        "article_cards",
        sa.Column("is_case_candidate", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE article_cards SET is_case_candidate = true")
    op.alter_column("article_cards", "is_case_candidate", nullable=False)
    op.create_index(
        "ix_article_cards_is_case_candidate",
        "article_cards",
        ["is_case_candidate"],
    )
    op.execute(
        """
        UPDATE article_cards AS card
        SET card_json = card.card_json
            || jsonb_build_object(
                'case_diagnosis', gate.case_diagnosis,
                'noise_reason', gate.noise_reason,
                'case_decision_reason_uk', gate.case_decision_reason_uk
            )
        FROM article_gate_decisions AS gate
        WHERE gate.article_id = card.article_id
        """
    )
    op.drop_index(
        "ix_article_gate_decisions_is_case_candidate_created_at",
        table_name="article_gate_decisions",
    )
    op.drop_table("article_gate_decisions")

    op.drop_constraint("ck_llm_runs_run_type", "llm_runs", type_="check")
    op.create_check_constraint(
        "ck_llm_runs_run_type",
        "llm_runs",
        "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
        "'event_resolution', 'case_copy_update', 'case_link_audit', 'case_coherence_audit', "
        "'case_public_interest_audit', 'case_duplicate_audit')",
    )
