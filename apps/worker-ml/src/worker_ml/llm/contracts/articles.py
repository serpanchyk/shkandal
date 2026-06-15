"""Article Card LLM contracts."""

from __future__ import annotations

import re

from pydantic import Field, model_validator

from worker_ml.llm.contracts.types import (
    EntityType,
    EventDatePrecision,
    NoiseReason,
    StrictOutput,
)


class ProvisionalEntity(StrictOutput):
    """Article-level entity candidate before global identity resolution."""

    provisional_ref: str = Field(
        pattern=r"^entity_[a-z0-9_]+$",
        description="Унікальне посилання на попередню сутність у межах картки статті.",
    )
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

    provisional_ref: str = Field(
        pattern=r"^event_[a-z0-9_]+$",
        description="Унікальне посилання на попередню подію у межах картки статті.",
    )
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
