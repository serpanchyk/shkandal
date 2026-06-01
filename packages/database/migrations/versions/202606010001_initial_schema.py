"""Create initial Shkandal schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606010001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title_uk", sa.Text(), nullable=False),
        sa.Column("summary_uk", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("article_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.CheckConstraint("status in ('active', 'hidden', 'merged')", name="ck_cases_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("canonical_name_uk", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("description_uk", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "entity_type in ('person', 'organization', 'institution', 'company', "
            "'political_party', 'informal_group', 'unknown_actor', 'other')",
            name="ck_entities_entity_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title_uk", sa.Text(), nullable=False),
        sa.Column("description_uk", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_date_precision", sa.Text(), nullable=True),
        sa.Column("location_uk", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "event_date_precision in ('day', 'month', 'year', 'unknown')",
            name="ck_events_event_date_precision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "llm_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("prompt_name", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("raw_output", postgresql.JSONB(), nullable=True),
        sa.Column("repaired_output", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
            "'event_resolution')",
            name="ck_llm_runs_run_type",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'succeeded', 'failed', 'repaired')",
            name="ck_llm_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint(
            "source_type in ('media', 'institution', 'court', 'ngo', 'other')",
            name="ck_sources_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("lead", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_language", sa.Text(), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("remote_image_url", sa.Text(), nullable=True),
        sa.Column(
            "remote_image_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
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
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_url"),
    )
    op.create_table(
        "case_relations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_case_id", sa.UUID(), nullable=False),
        sa.Column("target_case_id", sa.UUID(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relation_type in ('parent_child', 'related', 'possible_duplicate')",
            name="ck_case_relations_relation_type",
        ),
        sa.CheckConstraint("source_case_id <> target_case_id", name="ck_case_relations_not_self"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.ForeignKeyConstraint(["source_case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_case_id",
            "target_case_id",
            "relation_type",
            name="uq_case_relations_source_target_type",
        ),
    )
    op.create_table(
        "case_view_counters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("view_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            "counter_date",
            name="uq_case_view_counters_case_id_counter_date",
        ),
    )
    op.create_table(
        "article_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column("title_uk", sa.Text(), nullable=False),
        sa.Column("summary_uk", sa.Text(), nullable=False),
        sa.Column("card_json", postgresql.JSONB(), nullable=False),
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
    op.create_table(
        "article_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column("mention_text", sa.Text(), nullable=True),
        sa.Column("role_uk", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id",
            "entity_id",
            name="uq_article_entities_article_id_entity_id",
        ),
    )
    op.create_table(
        "article_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "event_id", name="uq_article_events_article_id_event_id"),
    )
    op.create_table(
        "article_relevance",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("is_relevant", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("classifier_name", sa.Text(), nullable=False),
        sa.Column("classifier_version", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id"),
    )
    op.create_table(
        "case_articles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column("link_reason_uk", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "article_id", name="uq_case_articles_case_id_article_id"),
    )
    op.create_table(
        "case_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("first_article_id", sa.UUID(), nullable=True),
        sa.Column("mention_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["first_article_id"], ["articles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "entity_id", name="uq_case_entities_case_id_entity_id"),
    )
    op.create_table(
        "case_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("first_article_id", sa.UUID(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column(
            "supporting_article_count",
            sa.Integer(),
            server_default=sa.text("0"),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["first_article_id"], ["articles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "event_id", name="uq_case_events_case_id_event_id"),
    )
    op.create_table(
        "article_entity_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_entity_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column("relevance_reason_uk", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["article_entity_id"],
            ["article_entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_entity_id",
            "case_id",
            name="uq_article_entity_cases_article_entity_id_case_id",
        ),
    )
    op.create_table(
        "article_event_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_event_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("llm_run_id", sa.UUID(), nullable=True),
        sa.Column("relevance_reason_uk", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["article_event_id"],
            ["article_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_run_id"], ["llm_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_event_id",
            "case_id",
            name="uq_article_event_cases_article_event_id_case_id",
        ),
    )

    op.create_index("ix_cases_created_at", "cases", ["created_at"])
    op.create_index("ix_cases_article_count", "cases", ["article_count"])
    op.create_index("ix_cases_status_last_updated_at", "cases", ["status", "last_updated_at"])
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_aliases", "entities", ["aliases"], postgresql_using="gin")
    op.create_index("ix_events_event_date", "events", ["event_date"])
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index(
        "ix_jobs_status_priority_run_after_created_at",
        "jobs",
        ["status", "priority", "run_after", "created_at"],
    )
    op.create_index("ix_jobs_job_type_status", "jobs", ["job_type", "status"])
    op.create_index("ix_llm_runs_run_type_created_at", "llm_runs", ["run_type", "created_at"])
    op.create_index("ix_llm_runs_status_created_at", "llm_runs", ["status", "created_at"])
    op.create_index("ix_sources_source_type", "sources", ["source_type"])
    op.create_index("ix_sources_is_active", "sources", ["is_active"])
    op.create_index(
        "ix_articles_source_id_published_at",
        "articles",
        ["source_id", "published_at"],
    )
    op.create_index("ix_articles_published_at", "articles", ["published_at"])
    op.create_index("ix_articles_canonical_url", "articles", ["canonical_url"])
    op.create_index(
        "ix_case_relations_target_case_id_relation_type",
        "case_relations",
        ["target_case_id", "relation_type"],
    )
    op.create_index(
        "ix_case_view_counters_counter_date_view_count",
        "case_view_counters",
        ["counter_date", "view_count"],
    )
    op.create_index(
        "ix_article_entities_entity_id_article_id",
        "article_entities",
        ["entity_id", "article_id"],
    )
    op.create_index(
        "ix_article_events_event_id_article_id",
        "article_events",
        ["event_id", "article_id"],
    )
    op.create_index(
        "ix_article_relevance_is_relevant_decided_at",
        "article_relevance",
        ["is_relevant", "decided_at"],
    )
    op.create_index(
        "ix_case_articles_article_id_case_id",
        "case_articles",
        ["article_id", "case_id"],
    )
    op.create_index(
        "ix_case_articles_case_id_created_at",
        "case_articles",
        ["case_id", "created_at"],
    )
    op.create_index(
        "ix_case_entities_entity_id_case_id",
        "case_entities",
        ["entity_id", "case_id"],
    )
    op.create_index(
        "ix_case_events_case_id_event_date",
        "case_events",
        ["case_id", "event_date"],
    )
    op.create_index(
        "ix_case_events_event_id_case_id",
        "case_events",
        ["event_id", "case_id"],
    )
    op.create_index(
        "ix_article_entity_cases_case_id_article_entity_id",
        "article_entity_cases",
        ["case_id", "article_entity_id"],
    )
    op.create_index(
        "ix_article_event_cases_case_id_article_event_id",
        "article_event_cases",
        ["case_id", "article_event_id"],
    )


def downgrade() -> None:
    """Revert the migration."""

    op.drop_index(
        "ix_article_event_cases_case_id_article_event_id",
        table_name="article_event_cases",
    )
    op.drop_index(
        "ix_article_entity_cases_case_id_article_entity_id",
        table_name="article_entity_cases",
    )
    op.drop_index("ix_case_events_event_id_case_id", table_name="case_events")
    op.drop_index("ix_case_events_case_id_event_date", table_name="case_events")
    op.drop_index("ix_case_entities_entity_id_case_id", table_name="case_entities")
    op.drop_index("ix_case_articles_case_id_created_at", table_name="case_articles")
    op.drop_index("ix_case_articles_article_id_case_id", table_name="case_articles")
    op.drop_index(
        "ix_article_relevance_is_relevant_decided_at",
        table_name="article_relevance",
    )
    op.drop_index("ix_article_events_event_id_article_id", table_name="article_events")
    op.drop_index("ix_article_entities_entity_id_article_id", table_name="article_entities")
    op.drop_index(
        "ix_case_view_counters_counter_date_view_count",
        table_name="case_view_counters",
    )
    op.drop_index(
        "ix_case_relations_target_case_id_relation_type",
        table_name="case_relations",
    )
    op.drop_index("ix_articles_canonical_url", table_name="articles")
    op.drop_index("ix_articles_published_at", table_name="articles")
    op.drop_index("ix_articles_source_id_published_at", table_name="articles")
    op.drop_index("ix_sources_is_active", table_name="sources")
    op.drop_index("ix_sources_source_type", table_name="sources")
    op.drop_index("ix_llm_runs_status_created_at", table_name="llm_runs")
    op.drop_index("ix_llm_runs_run_type_created_at", table_name="llm_runs")
    op.drop_index("ix_jobs_job_type_status", table_name="jobs")
    op.drop_index("ix_jobs_status_priority_run_after_created_at", table_name="jobs")
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_index("ix_events_event_date", table_name="events")
    op.drop_index("ix_entities_aliases", table_name="entities")
    op.drop_index("ix_entities_entity_type", table_name="entities")
    op.drop_index("ix_cases_status_last_updated_at", table_name="cases")
    op.drop_index("ix_cases_article_count", table_name="cases")
    op.drop_index("ix_cases_created_at", table_name="cases")

    op.drop_table("article_event_cases")
    op.drop_table("article_entity_cases")
    op.drop_table("case_events")
    op.drop_table("case_entities")
    op.drop_table("case_articles")
    op.drop_table("article_relevance")
    op.drop_table("article_events")
    op.drop_table("article_entities")
    op.drop_table("article_cards")
    op.drop_table("case_view_counters")
    op.drop_table("case_relations")
    op.drop_table("articles")
    op.drop_table("sources")
    op.drop_table("llm_runs")
    op.drop_table("jobs")
    op.drop_table("events")
    op.drop_table("entities")
    op.drop_table("cases")
