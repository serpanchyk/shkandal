"""Pydantic contracts for structured LLM outputs."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LlmRunType = Literal[
    "article_card",
    "case_resolution",
    "entity_resolution",
    "event_resolution",
    "case_copy_update",
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
CaseRelationType = Literal["related", "possible_duplicate"]
EventDatePrecision = Literal["day", "month", "year", "unknown"]
NoiseReason = Literal[
    "culture",
    "opinion",
    "statistics",
    "pr",
    "advertising",
    "generic_news",
    "ranking",
    "explainer",
    "lifestyle",
    "broad_analysis",
    "diplomacy",
    "policy_law",
    "routine_regulatory",
    "routine_crime",
]


class StrictOutput(BaseModel):
    """Base model for rejecting undeclared LLM fields."""

    model_config = ConfigDict(extra="forbid")


class ProvisionalEntity(StrictOutput):
    """Article-level entity candidate before global identity resolution."""

    name_uk: str = Field(
        min_length=1,
        description="Повна нормалізована українська назва сутності.",
    )
    entity_type: EntityType = Field(description="Тип центрального учасника статті.")
    aliases: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Скорочення та варіанти назви, явно вжиті у статті.",
    )
    description_uk: str = Field(
        min_length=1,
        description="Фактичний опис ролі сутності саме у цій статті.",
    )


class ProvisionalEvent(StrictOutput):
    """Article-level event candidate before global identity resolution."""

    title_uk: str = Field(
        min_length=1,
        description="Конкретний заголовок події у формі учасник і дія.",
    )
    description_uk: str = Field(
        min_length=1,
        description="Фактичний опис події з основного матеріалу, до шести речень.",
    )
    event_date: str | None = Field(
        default=None,
        description="Дата у форматі YYYY-MM-DD, YYYY-MM або YYYY відповідно до точності.",
    )
    event_date_precision: EventDatePrecision = Field(
        default="unknown",
        description="Найточніша відома або безпечно виведена точність дати.",
    )
    location_uk: str | None = Field(
        default=None,
        description="Місце події, лише якщо воно стосується цієї події.",
    )

    @model_validator(mode="after")
    def validate_event_date(self) -> ProvisionalEvent:
        """Require the event date shape to match its declared precision."""

        patterns = {
            "day": r"\d{4}-\d{2}-\d{2}",
            "month": r"\d{4}-\d{2}",
            "year": r"\d{4}",
        }
        if self.event_date_precision == "unknown":
            if self.event_date is not None:
                raise ValueError("unknown event date precision requires a null event date")
            return self
        if (
            self.event_date is None
            or re.fullmatch(patterns[self.event_date_precision], self.event_date) is None
        ):
            raise ValueError("event date must match its declared precision")
        return self


class ArticleCardOutput(StrictOutput):
    """Compact Ukrainian article card generated from one source article."""

    title_uk: str = Field(
        min_length=1,
        description="Очищений український заголовок основного матеріалу.",
    )
    summary_uk: str = Field(
        min_length=1,
        description="Нейтральний фактичний підсумок основного матеріалу у 1-2 реченнях.",
    )
    is_case_candidate: bool = Field(
        description="Чи описує стаття конкретну суспільно важливу справу або дію.",
    )
    noise_reason: NoiseReason | None = Field(
        default=None,
        description="Категорія шуму; обов'язкова лише для матеріалу, що не є справою.",
    )
    main_event_title_uk: str | None = Field(
        default=None,
        description="Головна конкретна дія справи; null для матеріалу, що не є справою.",
    )
    entities: list[ProvisionalEntity] = Field(
        default_factory=list,
        max_length=8,
        description="Лише центральні для основного матеріалу учасники справи.",
    )
    events: list[ProvisionalEvent] = Field(
        default_factory=list,
        max_length=3,
        description="Від однієї до трьох конкретних подій основного матеріалу.",
    )
    case_signature_terms: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Специфічні не загальні якорі для кластеризації тієї самої справи.",
    )

    @model_validator(mode="after")
    def validate_case_candidate_shape(self) -> ArticleCardOutput:
        """Keep non-case material out of downstream case signals."""

        if self.is_case_candidate:
            if self.noise_reason is not None:
                raise ValueError("case candidates cannot have a noise reason")
            if not self.main_event_title_uk:
                raise ValueError("case candidates require a main event title")
            if not self.events:
                raise ValueError("case candidates require at least one event")
            if not self.case_signature_terms:
                raise ValueError("case candidates require case signature terms")
            return self

        if self.noise_reason is None:
            raise ValueError("non-case cards require a noise reason")
        if self.main_event_title_uk is not None:
            raise ValueError("non-case cards cannot have a main event title")
        if self.entities or self.events or self.case_signature_terms:
            raise ValueError("non-case cards cannot contain case signals")
        return self


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

    new_case_ref: str = Field(pattern=r"^new_[a-z0-9_]+$")
    title_uk: str = Field(min_length=1)
    summary_uk: str = Field(min_length=1)
    link_reason_uk: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class CaseRelationDecision(StrictOutput):
    """Explicit relationship between resolved cases."""

    case_a_id: str | None = None
    case_a_new_ref: str | None = Field(default=None, pattern=r"^new_[a-z0-9_]+$")
    case_b_id: str | None = None
    case_b_new_ref: str | None = Field(default=None, pattern=r"^new_[a-z0-9_]+$")
    relation_type: CaseRelationType

    @model_validator(mode="after")
    def validate_endpoints(self) -> CaseRelationDecision:
        """Require exactly one identifier for each relation endpoint."""

        if (self.case_a_id is None) == (self.case_a_new_ref is None):
            raise ValueError("case_a requires exactly one existing id or new-case ref")
        if (self.case_b_id is None) == (self.case_b_new_ref is None):
            raise ValueError("case_b requires exactly one existing id or new-case ref")
        if (
            self.case_a_id is not None
            and self.case_b_id is not None
            and self.case_a_id == self.case_b_id
        ) or (
            self.case_a_new_ref is not None
            and self.case_b_new_ref is not None
            and self.case_a_new_ref == self.case_b_new_ref
        ):
            raise ValueError("case relation cannot reference the same case twice")
        return self


class CaseResolutionOutput(StrictOutput):
    """Article-to-case resolution output."""

    existing_case_links: list[CaseLinkDecision] = Field(default_factory=list)
    new_cases: list[NewCaseDecision] = Field(default_factory=list)
    case_relations: list[CaseRelationDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolution(self) -> CaseResolutionOutput:
        """Require a case and validate references to proposed new cases."""

        if not self.existing_case_links and not self.new_cases:
            raise ValueError("case resolution must link or create at least one case")
        existing_ids = [link.case_id for link in self.existing_case_links]
        if len(existing_ids) != len(set(existing_ids)):
            raise ValueError("existing case links must be unique")
        new_refs = [case.new_case_ref for case in self.new_cases]
        if len(new_refs) != len(set(new_refs)):
            raise ValueError("new case refs must be unique")
        known_refs = set(new_refs)
        for relation in self.case_relations:
            for ref in (relation.case_a_new_ref, relation.case_b_new_ref):
                if ref is not None and ref not in known_refs:
                    raise ValueError(f"unknown new case ref: {ref}")
        return self


class CaseCopyUpdateOutput(StrictOutput):
    """Updated reader-facing copy for one existing case."""

    title_action: Literal["keep", "replace"]
    replacement_title_uk: str | None = None
    title_reason_uk: str = Field(min_length=1)
    summary_uk: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_title_action(self) -> CaseCopyUpdateOutput:
        """Require replacement copy only for an explicit replacement."""

        if self.title_action == "replace" and not self.replacement_title_uk:
            raise ValueError("replacement title is required when title_action is replace")
        if self.title_action == "keep" and self.replacement_title_uk is not None:
            raise ValueError("replacement title must be null when title_action is keep")
        return self


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
