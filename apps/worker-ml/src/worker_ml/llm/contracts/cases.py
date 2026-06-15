"""Case resolution, copy, and audit LLM contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from worker_ml.llm.contracts.types import CaseRelationType, StrictOutput


class CaseCandidate(StrictOutput):
    """Candidate case retrieved before case resolution."""

    case_id: str = Field(description="Ідентифікатор наявної справи.")
    title_uk: str = Field(description="Поточний український заголовок справи.")
    summary_uk: str | None = Field(
        default=None,
        description="Поточний український підсумок справи, якщо він доступний.",
    )


class CaseLinkDecision(StrictOutput):
    """Decision to link the article to an existing case."""

    case_id: str = Field(description="Ідентифікатор наявної справи для прив'язки статті.")
    link_reason_uk: str = Field(
        min_length=1,
        description="Фактична підстава прив'язки статті до наявної справи.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Впевненість у правильності прив'язки від 0 до 1.",
    )


class NewCaseDecision(StrictOutput):
    """Decision to create a new reader-facing case."""

    new_case_ref: str = Field(
        pattern=r"^new_[a-z0-9_]+$",
        description="Унікальне тимчасове посилання на запропоновану нову справу.",
    )
    title_uk: str = Field(min_length=1, description="Український заголовок нової справи.")
    summary_uk: str = Field(
        min_length=1,
        description="Нейтральний український підсумок нової справи.",
    )
    link_reason_uk: str = Field(
        min_length=1,
        description="Фактична підстава включення статті до нової справи.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Впевненість у правильності створення справи від 0 до 1.",
    )


class CaseRelationDecision(StrictOutput):
    """Explicit relationship between resolved cases."""

    case_a_id: str | None = Field(
        default=None,
        description="Ідентифікатор першої наявної справи; взаємовиключний із case_a_new_ref.",
    )
    case_a_new_ref: str | None = Field(
        default=None,
        pattern=r"^new_[a-z0-9_]+$",
        description="Посилання на першу нову справу; взаємовиключне із case_a_id.",
    )
    case_b_id: str | None = Field(
        default=None,
        description="Ідентифікатор другої наявної справи; взаємовиключний із case_b_new_ref.",
    )
    case_b_new_ref: str | None = Field(
        default=None,
        pattern=r"^new_[a-z0-9_]+$",
        description="Посилання на другу нову справу; взаємовиключне із case_b_id.",
    )
    relation_type: CaseRelationType = Field(description="Тип зв'язку між двома справами.")

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

    decision_reason_uk: str = Field(
        min_length=1,
        description="Фактичне обґрунтування підсумкового рішення щодо статті.",
    )
    outcome: Literal["resolved", "rejected"] = Field(
        description="Підсумок: статтю розподілено до справ або відхилено.",
    )
    existing_case_links: list[CaseLinkDecision] = Field(
        default_factory=list,
        description="Прив'язки статті до наявних справ.",
    )
    new_cases: list[NewCaseDecision] = Field(
        default_factory=list,
        description="Нові справи, які потрібно створити для статті.",
    )
    case_relations: list[CaseRelationDecision] = Field(
        default_factory=list,
        description="Явні зв'язки між справами, визначені під час розподілу.",
    )

    @model_validator(mode="after")
    def validate_resolution(self) -> CaseResolutionOutput:
        """Validate outcome shape and references to proposed new cases."""

        if self.outcome == "resolved" and not self.existing_case_links and not self.new_cases:
            raise ValueError("resolved case resolution must link or create at least one case")
        if self.outcome == "rejected" and (
            self.existing_case_links or self.new_cases or self.case_relations
        ):
            raise ValueError("rejected case resolution cannot contain case actions")
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

    title_reason_uk: str = Field(
        min_length=1,
        description="Фактична підстава зберегти або замінити поточний заголовок справи.",
    )
    title_action: Literal["keep", "replace"] = Field(
        description="Дія щодо поточного заголовка справи.",
    )
    replacement_title_uk: str | None = Field(
        default=None,
        description="Новий український заголовок; заповнюється лише для дії replace.",
    )
    summary_uk: str = Field(
        min_length=1,
        description="Оновлений нейтральний український підсумок справи.",
    )

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

    story_ref: str = Field(
        pattern=r"^(original|story_[a-z0-9_]+)$",
        description="Унікальне посилання на цілісну історію в межах аудиту.",
    )
    title_uk: str = Field(min_length=1, description="Український заголовок історії.")
    summary_uk: str = Field(
        min_length=1,
        description="Нейтральний український підсумок історії.",
    )
    article_ids: list[str] = Field(
        min_length=1,
        description="Ідентифікатори статей, що належать до цієї історії.",
    )
    reason_uk: str = Field(
        min_length=1,
        description="Фактична підстава об'єднання статей у цю історію.",
    )


class CaseCoherenceAuditOutput(StrictOutput):
    """Decision from a recurring Case coherence audit."""

    reason_uk: str = Field(
        min_length=1,
        description="Фактичне обґрунтування підсумку аудиту цілісності справи.",
    )
    outcome: Literal["coherent", "split", "inconclusive"] = Field(
        description="Підсумок аудиту цілісності справи.",
    )
    stories: list[CaseAuditStory] = Field(
        default_factory=list,
        description="Цілісні історії, визначені для вирішального підсумку аудиту.",
    )

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
