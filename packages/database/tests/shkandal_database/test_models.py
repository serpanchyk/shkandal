"""Tests for database model metadata."""

from shkandal_database.models import Article, ArticleCard, Base, Case, Entity, Job, LlmRun, Source
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

EXPECTED_TABLES = {
    "sources",
    "articles",
    "article_relevance",
    "llm_runs",
    "article_cards",
    "cases",
    "case_articles",
    "case_relations",
    "entities",
    "article_entities",
    "article_entity_cases",
    "case_entities",
    "events",
    "article_events",
    "article_event_cases",
    "case_events",
    "jobs",
    "case_view_counters",
}


def constraint_names(table_name: str, constraint_type: type) -> set[str]:
    table = Base.metadata.tables[table_name]
    names: set[str] = set()
    for constraint in table.constraints:
        if isinstance(constraint, constraint_type) and constraint.name is not None:
            names.add(str(constraint.name))
    return names


def index_names(table_name: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {index.name for index in table.indexes if index.name is not None}


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_key_constraints_are_registered() -> None:
    assert "uq_articles_identity_url" in constraint_names("articles", UniqueConstraint)
    assert "uq_case_articles_case_id_article_id" in constraint_names(
        "case_articles",
        UniqueConstraint,
    )
    assert "ck_case_relations_not_self" in constraint_names("case_relations", CheckConstraint)
    assert "ck_entities_entity_type" in constraint_names("entities", CheckConstraint)
    assert "ck_jobs_status" in constraint_names("jobs", CheckConstraint)
    assert "uq_jobs_job_type_article_id" in constraint_names("jobs", UniqueConstraint)


def test_key_indexes_are_registered() -> None:
    assert "ix_articles_source_id_published_at" in index_names("articles")
    assert "ix_article_cards_is_case_candidate" in index_names("article_cards")
    assert "ix_cases_status_last_updated_at" in index_names("cases")
    assert "ix_entities_aliases" in index_names("entities")
    assert "ix_case_events_case_id_event_date" in index_names("case_events")


def test_foreign_keys_are_registered() -> None:
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        for constraint in Base.metadata.tables["articles"].constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        for constraint in Base.metadata.tables["case_articles"].constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        for constraint in Base.metadata.tables["article_event_cases"].constraints
    )


def test_metadata_columns_use_safe_python_names() -> None:
    assert Source.metadata_.property.columns[0].name == "metadata"
    assert Case.metadata_.property.columns[0].name == "metadata"
    assert Entity.metadata_.property.columns[0].name == "metadata"
    assert LlmRun.metadata_.property.columns[0].name == "metadata"
    assert isinstance(Source.metadata_.property.columns[0].type, JSONB)
    assert isinstance(LlmRun.metadata_.property.columns[0].type, JSONB)


def test_no_direct_entity_event_table_exists() -> None:
    assert "entity_events" not in Base.metadata.tables
    assert "entity_event" not in Base.metadata.tables


def test_article_uses_identity_url_only() -> None:
    assert Article.identity_url.property.columns[0].name == "identity_url"
    assert "canonical_url" not in Base.metadata.tables["articles"].columns
    assert "normalized_url" not in Base.metadata.tables["articles"].columns


def test_jobs_are_article_scoped() -> None:
    assert Job.article_id.property.columns[0].nullable is False
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        for constraint in Base.metadata.tables["jobs"].constraints
    )


def test_article_card_case_candidate_is_queryable() -> None:
    assert ArticleCard.is_case_candidate.property.columns[0].nullable is False
