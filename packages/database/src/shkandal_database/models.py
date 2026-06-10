"""SQLAlchemy models for the Shkandal MVP data graph."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base metadata for all Shkandal database tables."""


json_object_default = text("'{}'::jsonb")
json_array_default = text("'[]'::jsonb")


def uuid_pk_column() -> Mapped[UUID]:
    """Create a UUID primary key column."""

    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)


def created_at_column() -> Mapped[datetime]:
    """Create a created-at timestamp column."""

    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


def updated_at_column() -> Mapped[datetime]:
    """Create an updated-at timestamp column."""

    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


class Source(Base):
    """Curated source metadata."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "source_type in ("
            "'media', 'institution', 'court', 'ngo', 'other', "
            "'government', 'parliament', 'law_enforcement'"
            ")",
            name="ck_sources_source_type",
        ),
        Index("ix_sources_source_type", "source_type"),
        Index("ix_sources_is_active", "is_active"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    articles: Mapped[list["Article"]] = relationship(back_populates="source")


class Article(Base):
    """Stored source article."""

    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("identity_url", name="uq_articles_identity_url"),
        Index("ix_articles_source_id_published_at", "source_id", "published_at"),
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_fetch_retry", "fetch_status", "next_fetch_at"),
        CheckConstraint(
            "fetch_status in ('succeeded', 'failed')",
            name="ck_articles_fetch_status",
        ),
    )

    id: Mapped[UUID] = uuid_pk_column()
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    identity_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    lead: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_language: Mapped[str | None] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    remote_image_url: Mapped[str | None] = mapped_column(Text)
    remote_image_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    fetch_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'succeeded'"),
    )
    fetch_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    next_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetch_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    source: Mapped[Source] = relationship(back_populates="articles")


class ArticleRelevance(Base):
    """Binary classifier decision for an article."""

    __tablename__ = "article_relevance"
    __table_args__ = (
        Index("ix_article_relevance_is_relevant_decided_at", "is_relevant", "decided_at"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    is_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    classifier_name: Mapped[str] = mapped_column(Text, nullable=False)
    classifier_version: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )


class LlmRun(Base):
    """LLM call metadata for debugging and reprocessing."""

    __tablename__ = "llm_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type in ('article_card', 'case_resolution', 'entity_resolution', "
            "'event_resolution')",
            name="ck_llm_runs_run_type",
        ),
        CheckConstraint(
            "status in ('pending', 'succeeded', 'failed', 'repaired')",
            name="ck_llm_runs_status",
        ),
        Index("ix_llm_runs_run_type_created_at", "run_type", "created_at"),
        Index("ix_llm_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    repaired_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class LlmCooldown(Base):
    """Shared pause state for LLM-backed jobs."""

    __tablename__ = "llm_cooldowns"

    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    resume_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    cooldown_kind: Mapped[str] = mapped_column(Text, nullable=False)
    ambiguous_observation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    last_ambiguous_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ArticleCard(Base):
    """Provisional structured article card."""

    __tablename__ = "article_cards"
    __table_args__ = (Index("ix_article_cards_is_case_candidate", "is_case_candidate"),)

    id: Mapped[UUID] = uuid_pk_column()
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    title_uk: Mapped[str] = mapped_column(Text, nullable=False)
    summary_uk: Mapped[str] = mapped_column(Text, nullable=False)
    is_case_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    card_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Case(Base):
    """Reader-facing dossier."""

    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint("status in ('active', 'hidden', 'merged')", name="ck_cases_status"),
        Index("ix_cases_status_last_updated_at", "status", "last_updated_at"),
        Index("ix_cases_created_at", "created_at"),
        Index("ix_cases_article_count", "article_count"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title_uk: Mapped[str] = mapped_column(Text, nullable=False)
    summary_uk: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class CaseArticle(Base):
    """Many-to-many article to case link."""

    __tablename__ = "case_articles"
    __table_args__ = (
        UniqueConstraint("case_id", "article_id", name="uq_case_articles_case_id_article_id"),
        Index("ix_case_articles_article_id_case_id", "article_id", "case_id"),
        Index("ix_case_articles_case_id_created_at", "case_id", "created_at"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    link_reason_uk: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = created_at_column()


class CaseRelation(Base):
    """Explicit relationship between cases."""

    __tablename__ = "case_relations"
    __table_args__ = (
        CheckConstraint("source_case_id <> target_case_id", name="ck_case_relations_not_self"),
        CheckConstraint(
            "relation_type in ('parent_child', 'related', 'possible_duplicate')",
            name="ck_case_relations_relation_type",
        ),
        UniqueConstraint(
            "source_case_id",
            "target_case_id",
            "relation_type",
            name="uq_case_relations_source_target_type",
        ),
        Index(
            "ix_case_relations_target_case_id_relation_type",
            "target_case_id",
            "relation_type",
        ),
    )

    id: Mapped[UUID] = uuid_pk_column()
    source_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    created_at: Mapped[datetime] = created_at_column()


class Entity(Base):
    """Global typed entity."""

    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type in ('person', 'organization', 'institution', 'company', "
            "'political_party', 'informal_group', 'unknown_actor', 'other')",
            name="ck_entities_entity_type",
        ),
        Index("ix_entities_entity_type", "entity_type"),
        Index("ix_entities_aliases", "aliases", postgresql_using="gin"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name_uk: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=json_array_default
    )
    description_uk: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ArticleEntity(Base):
    """Article-level entity mention/resolution."""

    __tablename__ = "article_entities"
    __table_args__ = (
        UniqueConstraint(
            "article_id", "entity_id", name="uq_article_entities_article_id_entity_id"
        ),
        Index("ix_article_entities_entity_id_article_id", "entity_id", "article_id"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    mention_text: Mapped[str | None] = mapped_column(Text)
    role_uk: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = created_at_column()


class ArticleEntityCase(Base):
    """Case-scoped relevance of an article-entity link."""

    __tablename__ = "article_entity_cases"
    __table_args__ = (
        UniqueConstraint(
            "article_entity_id",
            "case_id",
            name="uq_article_entity_cases_article_entity_id_case_id",
        ),
        Index(
            "ix_article_entity_cases_case_id_article_entity_id",
            "case_id",
            "article_entity_id",
        ),
    )

    id: Mapped[UUID] = uuid_pk_column()
    article_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    relevance_reason_uk: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class CaseEntity(Base):
    """Materialized public case/entity link."""

    __tablename__ = "case_entities"
    __table_args__ = (
        UniqueConstraint("case_id", "entity_id", name="uq_case_entities_case_id_entity_id"),
        Index("ix_case_entities_entity_id_case_id", "entity_id", "case_id"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    first_article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id"))
    mention_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Event(Base):
    """Global strict real-world occurrence."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "event_date_precision in ('day', 'month', 'year', 'unknown')",
            name="ck_events_event_date_precision",
        ),
        Index("ix_events_event_date", "event_date"),
        Index("ix_events_created_at", "created_at"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title_uk: Mapped[str] = mapped_column(Text, nullable=False)
    description_uk: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date | None] = mapped_column(Date)
    event_date_precision: Mapped[str | None] = mapped_column(Text)
    location_uk: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ArticleEvent(Base):
    """Article-level event resolution/provenance."""

    __tablename__ = "article_events"
    __table_args__ = (
        UniqueConstraint("article_id", "event_id", name="uq_article_events_article_id_event_id"),
        Index("ix_article_events_event_id_article_id", "event_id", "article_id"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = created_at_column()


class ArticleEventCase(Base):
    """Case-scoped relevance of an article-event link."""

    __tablename__ = "article_event_cases"
    __table_args__ = (
        UniqueConstraint(
            "article_event_id",
            "case_id",
            name="uq_article_event_cases_article_event_id_case_id",
        ),
        Index(
            "ix_article_event_cases_case_id_article_event_id",
            "case_id",
            "article_event_id",
        ),
    )

    id: Mapped[UUID] = uuid_pk_column()
    article_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    llm_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_runs.id"))
    relevance_reason_uk: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class CaseEvent(Base):
    """Materialized public case/event link."""

    __tablename__ = "case_events"
    __table_args__ = (
        UniqueConstraint("case_id", "event_id", name="uq_case_events_case_id_event_id"),
        Index("ix_case_events_case_id_event_date", "case_id", "event_date"),
        Index("ix_case_events_event_id_case_id", "event_id", "case_id"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    first_article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id"))
    event_date: Mapped[date | None] = mapped_column(Date)
    supporting_article_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Job(Base):
    """Generic Postgres-backed background job."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        UniqueConstraint("job_type", "article_id", name="uq_jobs_job_type_article_id"),
        Index(
            "ix_jobs_status_priority_run_after_created_at",
            "status",
            "priority",
            "run_after",
            "created_at",
        ),
        Index("ix_jobs_job_type_status", "job_type", "status"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=json_object_default,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("3"),
    )
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class CaseViewCounter(Base):
    """Anonymous aggregate case view counter."""

    __tablename__ = "case_view_counters"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "counter_date", name="uq_case_view_counters_case_id_counter_date"
        ),
        Index(
            "ix_case_view_counters_counter_date_view_count",
            "counter_date",
            "view_count",
        ),
    )

    id: Mapped[UUID] = uuid_pk_column()
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    counter_date: Mapped[date] = mapped_column(Date, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
