"""Entity and Event resolution LLM contracts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from worker_ml.llm.contracts.types import EntityType, EventDatePrecision, StrictOutput

ROLE_ALIAS_PATTERNS = (
    r"\b(колишн(?:ій|я|є|і)|підозрюван(?:ий|а|е|і)|обвинувачен(?:ий|а|е|і)|"
    r"фігурант|переможець|посадовець|бухгалтер|водій|підприємець|правоохоронець)\b",
    r"\b(у справі|тендеру|який|яка|яке|які)\b",
)
CASE_ROLE_DESCRIPTION_PATTERNS = (
    r"\b(який|яка|яке|які)\s+(викрив|викрила|продовжив|продовжила|фігурує)\b",
    r"\bде\s+(затримали|повідомили|провели|викрили)\b",
)


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
            "not_stable_actor",
            "not_material_to_case",
            "background_or_related_material",
            "location_only",
            "role_without_name",
            "unsupported_by_context",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_action(self) -> EntityResolutionDecision:
        """Require action-specific identity fields and relevant Case assignments."""

        if any(
            re.search(pattern, alias, re.IGNORECASE)
            for alias in self.aliases
            for pattern in ROLE_ALIAS_PATTERNS
        ):
            raise ValueError("aliases cannot be role descriptions")
        if self.description_uk is not None and any(
            re.search(pattern, self.description_uk, re.IGNORECASE)
            for pattern in CASE_ROLE_DESCRIPTION_PATTERNS
        ):
            raise ValueError("description_uk cannot describe a case-specific role")
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
