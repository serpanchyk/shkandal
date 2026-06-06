"""Pydantic contracts for structured LLM outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LlmRunType = Literal[
    "article_card",
    "case_resolution",
    "entity_resolution",
    "event_resolution",
]
EntityType = Literal[
    "person",
    "organization",
    "institution",
    "company",
    "political_party",
    "informal_group",
    "unknown_actor",
    "other",
]
CaseRelationType = Literal["parent_child", "related", "possible_duplicate"]
EventDatePrecision = Literal["day", "month", "year", "unknown"]


class StrictOutput(BaseModel):
    """Base model for rejecting undeclared LLM fields."""

    model_config = ConfigDict(extra="forbid")


class ProvisionalEntity(StrictOutput):
    """Article-level entity candidate before global identity resolution."""

    name_uk: str = Field(min_length=1)
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    description_uk: str | None = None
    evidence_text: str | None = None


class ProvisionalEvent(StrictOutput):
    """Article-level event candidate before global identity resolution."""

    title_uk: str = Field(min_length=1)
    description_uk: str = Field(min_length=1)
    event_date: str | None = None
    event_date_precision: EventDatePrecision = "unknown"
    location_uk: str | None = None
    evidence_text: str | None = None


class ArticleCardOutput(StrictOutput):
    """Compact Ukrainian article card generated from one source article."""

    title_uk: str = Field(min_length=1)
    summary_uk: str = Field(min_length=1)
    entities: list[ProvisionalEntity] = Field(default_factory=list)
    events: list[ProvisionalEvent] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    source_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class CaseCandidate(StrictOutput):
    """Candidate case retrieved before case resolution."""

    case_id: str
    title_uk: str
    summary_uk: str | None = None


class CaseLinkDecision(StrictOutput):
    """Decision to link the article to an existing case."""

    case_id: str
    link_reason_uk: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class NewCaseDecision(StrictOutput):
    """Decision to create a new reader-facing case."""

    title_uk: str = Field(min_length=1)
    summary_uk: str = Field(min_length=1)
    link_reason_uk: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class CaseRelationDecision(StrictOutput):
    """Explicit relationship between resolved cases."""

    source_case_ref: str
    target_case_ref: str
    relation_type: CaseRelationType


class CaseResolutionOutput(StrictOutput):
    """Article-to-case resolution output."""

    existing_case_links: list[CaseLinkDecision] = Field(default_factory=list)
    new_cases: list[NewCaseDecision] = Field(default_factory=list)
    case_relations: list[CaseRelationDecision] = Field(default_factory=list)


class EntityCaseAssignment(StrictOutput):
    """Case-scoped relevance of a resolved entity."""

    case_id: str
    relevance_reason_uk: str = Field(min_length=1)


class EntityResolutionDecision(StrictOutput):
    """Decision for one provisional entity."""

    provisional_name_uk: str = Field(min_length=1)
    existing_entity_id: str | None = None
    new_canonical_name_uk: str | None = None
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    description_uk: str | None = None
    mention_text: str | None = None
    confidence: float = Field(ge=0, le=1)
    case_assignments: list[EntityCaseAssignment] = Field(default_factory=list)


class EntityResolutionOutput(StrictOutput):
    """Entity resolution output for one article card and linked cases."""

    entities: list[EntityResolutionDecision] = Field(default_factory=list)


class EventCaseAssignment(StrictOutput):
    """Case-scoped relevance of a resolved event."""

    case_id: str
    relevance_reason_uk: str = Field(min_length=1)


class EventResolutionDecision(StrictOutput):
    """Decision for one provisional event."""

    provisional_title_uk: str = Field(min_length=1)
    existing_event_id: str | None = None
    new_title_uk: str | None = None
    description_uk: str | None = None
    event_date: str | None = None
    event_date_precision: EventDatePrecision = "unknown"
    location_uk: str | None = None
    evidence_text: str | None = None
    confidence: float = Field(ge=0, le=1)
    case_assignments: list[EventCaseAssignment] = Field(default_factory=list)


class EventResolutionOutput(StrictOutput):
    """Event resolution output for one article card and linked cases."""

    events: list[EventResolutionDecision] = Field(default_factory=list)
