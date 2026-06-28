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


class ArticleCaseDiagnosis(StrictOutput):
    """Short factual checks before deciding whether an article is a Case candidate."""

    ukraine_nexus_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий факт про прямий і суттєвий зв'язок основної історії з Україною.",
    )
    concrete_story_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке конкретне фактичне ядро відстежуваної історії.",
    )
    public_accountability_anchor_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий якір публічної підзвітності, якщо він прямо є в матеріалі.",
    )
    continuation_potential_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий факт про можливість майбутнього розвитку або наступних етапів.",
    )
    noise_signals_uk: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Короткі сигнали шуму або тематичної розмитості.",
    )


class ArticleGateOutput(StrictOutput):
    """Second-layer LLM relevance gate decision for one source article."""

    case_diagnosis: ArticleCaseDiagnosis = Field(
        description="Коротка структурована діагностика перед рішенням, чи є матеріал справою.",
    )
    noise_reason: NoiseReason | None = Field(
        default=None,
        description="Категорія шуму; обов'язкова лише для матеріалу, що не є справою.",
    )
    case_decision_reason_uk: str | None = Field(
        default=None,
        max_length=320,
        description="Короткий висновок із діагностики про те, чи є матеріал справою.",
    )
    is_case_candidate: bool = Field(
        description="Чи описує стаття конкретну суспільно важливу справу або дію.",
    )

    @model_validator(mode="after")
    def validate_gate_decision_shape(self) -> ArticleGateOutput:
        """Require gate diagnostics to support the final decision."""

        if self.is_case_candidate:
            if self.noise_reason is not None:
                raise ValueError("case candidates cannot have a noise reason")
            if self.case_diagnosis.ukraine_nexus_uk is None:
                raise ValueError("case candidates require a Ukraine nexus diagnosis")
            if self.case_diagnosis.concrete_story_core_uk is None:
                raise ValueError("case candidates require a concrete story core diagnosis")
            if (
                self.case_diagnosis.public_accountability_anchor_uk is None
                and self.case_diagnosis.continuation_potential_uk is None
            ):
                raise ValueError(
                    "case candidates require a public accountability anchor or clear continuation"
                )
            return self

        if self.noise_reason is None:
            raise ValueError("rejected gate decisions require a noise reason")
        return self


class ArticleCardOutput(StrictOutput):
    """Compact Ukrainian article card generated for an accepted gate decision."""

    title_uk: str = Field(
        min_length=1,
        description="Очищений український заголовок основного матеріалу.",
    )
    summary_uk: str = Field(
        min_length=1,
        description="Нейтральний фактичний підсумок основного матеріалу у 1-2 реченнях.",
    )
    main_event_title_uk: str = Field(
        min_length=1,
        description="Головна конкретна дія справи.",
    )
    entities: list[ProvisionalEntity] = Field(
        default_factory=list,
        max_length=8,
        description="Лише центральні для основного матеріалу учасники справи.",
    )
    events: list[ProvisionalEvent] = Field(
        min_length=1,
        max_length=3,
        description="Від однієї до трьох конкретних подій основного матеріалу.",
    )
    case_signature_terms: list[str] = Field(
        min_length=1,
        max_length=8,
        description="Специфічні не загальні якорі для кластеризації тієї самої справи.",
    )

    @model_validator(mode="after")
    def validate_card_shape(self) -> ArticleCardOutput:
        """Keep provisional references unique within one card."""

        entity_refs = [entity.provisional_ref for entity in self.entities]
        event_refs = [event.provisional_ref for event in self.events]
        if len(entity_refs) != len(set(entity_refs)):
            raise ValueError("provisional entity refs must be unique")
        if len(event_refs) != len(set(event_refs)):
            raise ValueError("provisional event refs must be unique")
        return self
