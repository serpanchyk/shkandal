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
    "case_coherence_audit",
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
    "foreign_no_ukraine_nexus",
]


class StrictOutput(BaseModel):
    """Base model for rejecting undeclared LLM fields."""

    model_config = ConfigDict(extra="forbid")


class ProvisionalEntity(StrictOutput):
    """Article-level entity candidate before global identity resolution."""

    provisional_ref: str = Field(pattern=r"^entity_[a-z0-9_]+$")
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

    provisional_ref: str = Field(pattern=r"^event_[a-z0-9_]+$")
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
    case_decision_reason_uk: str | None = Field(
        default=None,
        description="Коротка фактична підстава для рішення, чи є матеріал справою.",
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
            entity_refs = [entity.provisional_ref for entity in self.entities]
            event_refs = [event.provisional_ref for event in self.events]
            if len(entity_refs) != len(set(entity_refs)):
                raise ValueError("provisional entity refs must be unique")
            if len(event_refs) != len(set(event_refs)):
                raise ValueError("provisional event refs must be unique")
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

    title_reason_uk: str = Field(min_length=1)
    title_action: Literal["keep", "replace"]
    replacement_title_uk: str | None = None
    summary_uk: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_title_action(self) -> CaseCopyUpdateOutput:
        """Require replacement copy only for an explicit replacement."""

        if self.title_action == "replace" and not self.replacement_title_uk:
            raise ValueError("replacement title is required when title_action is replace")
        if self.title_action == "keep" and self.replacement_title_uk is not None:
            raise ValueError("replacement title must be null when title_action is keep")
        return self


class CaseAuditStory(StrictOutput):
    """One coherent durable story produced by a Case audit."""

    story_ref: str = Field(pattern=r"^(original|story_[a-z0-9_]+)$")
    title_uk: str = Field(min_length=1)
    summary_uk: str = Field(min_length=1)
    article_ids: list[str] = Field(min_length=1)
    reason_uk: str = Field(min_length=1)


class CaseCoherenceAuditOutput(StrictOutput):
    """Decision from a recurring Case coherence audit."""

    reason_uk: str = Field(min_length=1)
    outcome: Literal["coherent", "split", "inconclusive"]
    stories: list[CaseAuditStory] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> CaseCoherenceAuditOutput:
        """Require one original story for decisive outcomes."""

        if self.outcome == "inconclusive":
            if self.stories:
                raise ValueError("inconclusive audit cannot contain stories")
            return self
        refs = [story.story_ref for story in self.stories]
        if refs.count("original") != 1:
            raise ValueError("decisive audit requires exactly one original story")
        if len(refs) != len(set(refs)):
            raise ValueError("audit story refs must be unique")
        if self.outcome == "coherent" and len(self.stories) != 1:
            raise ValueError("coherent audit requires only the original story")
        if self.outcome == "split" and len(self.stories) < 2:
            raise ValueError("split audit requires at least two stories")
        for story in self.stories:
            if len(story.article_ids) != len(set(story.article_ids)):
                raise ValueError("story article ids must be unique")
        return self


class EntityCaseAssignment(StrictOutput):
    """Case-scoped relevance of a resolved entity."""

    case_id: str
    relevance_reason_uk: str = Field(min_length=1)


class EntityResolutionDecision(StrictOutput):
    """Decision for one provisional entity."""

    provisional_ref: str = Field(pattern=r"^entity_[a-z0-9_]+$")
    reason_uk: str = Field(min_length=1)
    action: Literal[
        "link_existing",
        "create_new",
        "reject",
        "rename_existing",
        "retype_existing",
    ]
    existing_entity_id: str | None = None
    new_canonical_name_uk: str | None = None
    entity_type: EntityType | None = None
    aliases: list[str] = Field(default_factory=list)
    description_uk: str | None = None
    confidence: float = Field(ge=0, le=1)
    case_assignments: list[EntityCaseAssignment] = Field(default_factory=list)
    rejection_reason: (
        Literal[
            "not_an_entity",
            "not_directly_mentioned",
            "not_case_relevant",
            "insufficient_identity",
            "duplicate_extraction",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_action(self) -> EntityResolutionDecision:
        """Require action-specific identity fields and relevant Case assignments."""

        existing_actions = {"link_existing", "rename_existing", "retype_existing"}
        if self.action in existing_actions and self.existing_entity_id is None:
            raise ValueError(f"{self.action} requires existing_entity_id")
        if self.action == "create_new" and self.existing_entity_id is not None:
            raise ValueError("create_new cannot reference an existing entity")
        if self.action == "create_new" and (
            self.new_canonical_name_uk is None or self.entity_type is None
        ):
            raise ValueError("create_new requires canonical name and entity type")
        if self.action == "rename_existing" and self.new_canonical_name_uk is None:
            raise ValueError("rename_existing requires new_canonical_name_uk")
        if self.action != "rename_existing" and self.action != "create_new":
            if self.new_canonical_name_uk is not None:
                raise ValueError(f"{self.action} cannot change canonical name")
        if self.action == "retype_existing" and self.entity_type is None:
            raise ValueError("retype_existing requires entity_type")
        if self.action == "reject":
            if self.rejection_reason is None:
                raise ValueError("reject requires rejection_reason")
            if self.existing_entity_id is not None or self.new_canonical_name_uk is not None:
                raise ValueError("reject cannot reference an identity")
            if self.case_assignments:
                raise ValueError("reject cannot have Case assignments")
            return self
        if self.rejection_reason is not None:
            raise ValueError("accepted entity cannot have rejection_reason")
        if not self.case_assignments:
            raise ValueError("accepted entity requires at least one Case assignment")
        return self


class EntityResolutionOutput(StrictOutput):
    """Entity resolution output for one article card and linked cases."""

    entities: list[EntityResolutionDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> EntityResolutionOutput:
        """Require one decision per unique provisional reference."""

        refs = [entity.provisional_ref for entity in self.entities]
        if len(refs) != len(set(refs)):
            raise ValueError("entity decisions must have unique provisional refs")
        return self


class EventCaseAssignment(StrictOutput):
    """Case-scoped relevance of a resolved event."""

    case_id: str
    relevance_reason_uk: str = Field(min_length=1)


class EventResolutionDecision(StrictOutput):
    """Decision for one provisional event."""

    provisional_ref: str = Field(pattern=r"^event_[a-z0-9_]+$")
    reason_uk: str = Field(min_length=1)
    action: Literal["link_existing", "create_new", "reject"]
    existing_event_id: str | None = None
    new_title_uk: str | None = None
    description_uk: str | None = None
    event_date: str | None = None
    event_date_precision: EventDatePrecision = "unknown"
    location_uk: str | None = None
    confidence: float = Field(ge=0, le=1)
    case_assignments: list[EventCaseAssignment] = Field(default_factory=list)
    rejection_reason: (
        Literal[
            "not_an_event",
            "not_case_relevant",
            "insufficient_identity",
            "conflicting_identity_anchors",
            "duplicate_extraction",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_action(self) -> EventResolutionDecision:
        """Require action-specific identity fields and relevant Case assignments."""

        if self.action == "link_existing" and self.existing_event_id is None:
            raise ValueError("link_existing requires existing_event_id")
        if self.action == "create_new" and self.existing_event_id is not None:
            raise ValueError("create_new cannot reference an existing event")
        if self.action == "create_new" and self.new_title_uk is None:
            raise ValueError("create_new requires new_title_uk")
        if self.action == "link_existing" and self.new_title_uk is not None:
            raise ValueError("link_existing cannot replace the Event title")
        if self.action == "reject":
            if self.rejection_reason is None:
                raise ValueError("reject requires rejection_reason")
            if self.existing_event_id is not None or self.new_title_uk is not None:
                raise ValueError("reject cannot reference an identity")
            if self.case_assignments:
                raise ValueError("reject cannot have Case assignments")
            return self
        if self.rejection_reason is not None:
            raise ValueError("accepted event cannot have rejection_reason")
        if not self.case_assignments:
            raise ValueError("accepted event requires at least one Case assignment")
        patterns = {
            "day": r"\d{4}-\d{2}-\d{2}",
            "month": r"\d{4}-\d{2}",
            "year": r"\d{4}",
        }
        if self.event_date_precision == "unknown":
            if self.event_date is not None:
                raise ValueError("unknown event date precision requires a null event date")
        elif (
            self.event_date is None
            or re.fullmatch(patterns[self.event_date_precision], self.event_date) is None
        ):
            raise ValueError("event date must match its declared precision")
        return self


class EventResolutionOutput(StrictOutput):
    """Event resolution output for one article card and linked cases."""

    events: list[EventResolutionDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> EventResolutionOutput:
        """Require one decision per unique provisional reference."""

        refs = [event.provisional_ref for event in self.events]
        if len(refs) != len(set(refs)):
            raise ValueError("event decisions must have unique provisional refs")
        return self
