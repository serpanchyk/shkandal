"""Case resolution, copy, and audit LLM contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from worker_ml.llm.contracts.types import CaseRelationType, StrictOutput

_SPECULATIVE_DURABILITY_MARKERS = (
    "можлив",
    "ймовір",
    "може ",
    "можуть",
    "можна очікувати",
    "очікується",
    "потенцій",
)


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


class CaseResolutionDiagnosis(StrictOutput):
    """Short factual checks before resolving an article into Cases."""

    article_story_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке фактичне ядро історії в основному матеріалі статті.",
    )
    specific_case_core_uk: str | None = Field(
        max_length=240,
        description=(
            "Найвужче конкретне ядро справи, яке може тримати прив'язку або нову справу; "
            "null, якщо такого ядра немає."
        ),
    )
    only_broad_overlap_uk: str | None = Field(
        max_length=240,
        description=(
            "Короткий факт, якщо збіг із candidate є лише темою, актором, установою, "
            "процедурою або категорією; інакше null."
        ),
    )
    merge_blockers_uk: list[str] = Field(
        max_length=8,
        description=(
            "Факти, які заважають прив'язати статтю до наявної справи: інші фігуранти, "
            "провадження, епізоди, закупівлі, рішення або процеси."
        ),
    )
    separate_story_cores_uk: list[str] = Field(
        max_length=8,
        description=(
            "Короткі ядра окремих історій у статті, якщо матеріал підтримує кілька справ."
        ),
    )
    case_coherence_test_uk: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "Коротка відповідь, чи можна описати обрану справу одним конкретним реченням "
            "без тематичних або інституційних парасольок."
        ),
    )
    matching_existing_case_ids: list[str] = Field(
        default_factory=list,
        description="Ідентифікатори наявних справ, що збігаються саме з цим ядром.",
    )
    new_case_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке ядро нової найвужчої справи, якщо її треба створити.",
    )
    rejection_signals_uk: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Короткі фактичні сигнали, чому статтю слід відхилити як справу.",
    )
    broad_theme_warning_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Попередження, якщо збіг є лише тематичним або інституційним.",
    )


class CaseResolutionOutput(StrictOutput):
    """Article-to-case resolution output."""

    diagnosis: CaseResolutionDiagnosis = Field(
        description="Коротка структурована діагностика перед підсумковим рішенням щодо статті.",
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
    decision_reason_uk: str = Field(
        min_length=1,
        max_length=320,
        description="Короткий висновок із діагностики щодо розподілу статті по справах.",
    )
    outcome: Literal["resolved", "rejected"] = Field(
        description="Підсумок: статтю розподілено до справ або відхилено.",
    )

    @model_validator(mode="after")
    def validate_resolution(self) -> CaseResolutionOutput:
        """Validate outcome shape and references to proposed new cases."""

        if self.diagnosis.broad_theme_warning_uk is not None and (
            self.diagnosis.article_story_core_uk is None
        ):
            if self.outcome != "rejected":
                raise ValueError("broad thematic warnings without story core must be rejected")
        if self.outcome == "resolved" and not self.existing_case_links and not self.new_cases:
            raise ValueError("resolved case resolution must link or create at least one case")
        if self.outcome == "resolved" and self.diagnosis.article_story_core_uk is None:
            raise ValueError("resolved case resolution requires a concrete article story core")
        if self.outcome == "resolved" and self.diagnosis.specific_case_core_uk is None:
            raise ValueError("resolved case resolution requires a specific case core")
        if self.outcome == "resolved" and not (
            self.diagnosis.matching_existing_case_ids or self.diagnosis.new_case_core_uk
        ):
            raise ValueError("resolved case resolution requires matching or new-case diagnosis")
        if (
            self.existing_case_links
            and self.diagnosis.only_broad_overlap_uk is not None
            and not self.diagnosis.matching_existing_case_ids
        ):
            raise ValueError("existing case links cannot rely only on broad overlap")
        if self.outcome == "rejected" and (
            self.existing_case_links or self.new_cases or self.case_relations
        ):
            raise ValueError("rejected case resolution cannot contain case actions")
        if self.outcome == "rejected" and not (
            self.diagnosis.rejection_signals_uk or self.diagnosis.article_story_core_uk is None
        ):
            raise ValueError("rejected case resolution requires rejection signals or no story core")
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


class CaseLinkAuditDiagnosis(StrictOutput):
    """Short factual checks before rechecking one article-to-case link."""

    article_story_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке фактичне ядро історії в поточній статті.",
    )
    case_story_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке фактичне ядро наявної справи за її картками статей.",
    )
    shared_specific_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Конкретне спільне ядро, якщо стаття справді належить до цієї справи.",
    )
    only_broad_overlap_uk: str | None = Field(
        default=None,
        max_length=240,
        description=(
            "Короткий факт, якщо збіг є лише темою, актором, установою, процедурою або жанром."
        ),
    )
    disconnect_signals_uk: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Короткі факти, чому статтю слід не прив'язувати до цієї справи.",
    )
    coherence_test_uk: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "Коротка відповідь, чи можна описати статтю та справу одним конкретним реченням."
        ),
    )


class CaseLinkAuditOutput(StrictOutput):
    """Decision to keep or drop one provisional article-to-case link."""

    diagnosis: CaseLinkAuditDiagnosis = Field(
        description="Коротка структурована діагностика перед рішенням щодо прив'язки."
    )
    reason_uk: str = Field(
        min_length=1,
        max_length=320,
        description="Коротке фактичне обґрунтування рішення щодо прив'язки.",
    )
    outcome: Literal["connect", "drop", "inconclusive"] = Field(
        description="Підсумок повторної перевірки прив'язки статті до наявної справи.",
    )

    @model_validator(mode="after")
    def validate_outcome(self) -> CaseLinkAuditOutput:
        """Require concrete shared story evidence for positive link decisions."""

        if self.outcome == "connect":
            if self.diagnosis.article_story_core_uk is None:
                raise ValueError("connect link audit requires an article story core")
            if self.diagnosis.case_story_core_uk is None:
                raise ValueError("connect link audit requires a case story core")
            if self.diagnosis.shared_specific_core_uk is None:
                raise ValueError("connect link audit requires a shared specific core")
            if self.diagnosis.only_broad_overlap_uk is not None:
                raise ValueError("connect link audit cannot rely only on broad overlap")
            if self.diagnosis.disconnect_signals_uk:
                raise ValueError("connect link audit cannot contain disconnect signals")
        if self.outcome == "drop" and not (
            self.diagnosis.only_broad_overlap_uk is not None
            or self.diagnosis.disconnect_signals_uk
            or self.diagnosis.shared_specific_core_uk is None
        ):
            raise ValueError("drop link audit requires a factual reason to disconnect")
        return self


class CaseCopyTitleDiagnosis(StrictOutput):
    """Short factual checks before deciding whether to replace a Case title."""

    current_title_specific_enough: bool = Field(
        description="Чи поточна назва достатньо конкретно й стабільно описує справу."
    )
    replacement_needed_reason_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий факт, чому поточну назву потрібно замінити, якщо це потрібно.",
    )
    proposed_title_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке ядро стабільної замінної назви, якщо її пропонують.",
    )


class CaseCopyUpdateOutput(StrictOutput):
    """Updated reader-facing copy for one existing case."""

    title_diagnosis: CaseCopyTitleDiagnosis = Field(
        description="Коротка структурована діагностика перед рішенням щодо заголовка справи.",
    )
    replacement_title_uk: str | None = Field(
        default=None,
        description="Новий український заголовок; заповнюється лише для дії replace.",
    )
    summary_uk: str = Field(
        min_length=1,
        description="Оновлений нейтральний український підсумок справи.",
    )
    title_reason_uk: str = Field(
        min_length=1,
        max_length=320,
        description="Фактична підстава зберегти або замінити поточний заголовок справи.",
    )
    title_action: Literal["keep", "replace"] = Field(
        description="Дія щодо поточного заголовка справи.",
    )

    @model_validator(mode="after")
    def validate_title_action(self) -> CaseCopyUpdateOutput:
        """Require replacement copy only for an explicit replacement."""

        if self.title_action == "replace" and not self.replacement_title_uk:
            raise ValueError("replacement title is required when title_action is replace")
        if (
            self.title_action == "replace"
            and self.title_diagnosis.replacement_needed_reason_uk is None
        ):
            raise ValueError("replace requires a replacement-needed diagnosis reason")
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


class CaseAuditDetachedArticle(StrictOutput):
    """An Article that belongs to none of the audited Case stories."""

    article_id: str = Field(description="Ідентифікатор статті для від'єднання.")
    reason_uk: str = Field(min_length=1, description="Фактична підстава від'єднання.")


class CaseCoherenceDiagnosis(StrictOutput):
    """Short factual checks before deciding Case coherence."""

    shared_specific_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Одне конкретне фактичне ядро, спільне для всіх статей, якщо воно існує.",
    )
    shared_only_broad_theme_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий факт, якщо статті збігаються лише широкою темою або інституцією.",
    )
    merge_blockers_uk: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Короткі факти, що заважають вважати всі статті однією історією.",
    )
    split_story_cores_uk: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Короткі ядра окремих історій, якщо справу треба розділити.",
    )
    detached_article_signals_uk: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Короткі сигнали, чому окремі статті можуть не належати жодній історії.",
    )
    coherence_test_uk: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "Коротка відповідь на тест, чи всі статті можна описати одним конкретним реченням."
        ),
    )


class CaseCoherenceAuditOutput(StrictOutput):
    """Decision from a recurring Case coherence audit."""

    diagnosis: CaseCoherenceDiagnosis = Field(
        description="Коротка структурована діагностика перед підсумком аудиту цілісності справи.",
    )
    stories: list[CaseAuditStory] = Field(
        default_factory=list,
        description="Цілісні історії, визначені для вирішального підсумку аудиту.",
    )
    detached_articles: list[CaseAuditDetachedArticle] = Field(
        default_factory=list,
        description="Статті, що не належать до жодної визначеної історії.",
    )
    reason_uk: str = Field(
        min_length=1,
        max_length=320,
        description="Фактичне обґрунтування підсумку аудиту цілісності справи.",
    )
    outcome: Literal["coherent", "split", "inconclusive"] = Field(
        description="Підсумок аудиту цілісності справи.",
    )

    @model_validator(mode="after")
    def validate_outcome(self) -> CaseCoherenceAuditOutput:
        """Require one original story for decisive outcomes."""

        if self.outcome == "inconclusive":
            if self.stories or self.detached_articles:
                raise ValueError("inconclusive audit cannot contain decisions")
            return self
        refs = [story.story_ref for story in self.stories]
        if refs.count("original") != 1:
            raise ValueError("decisive audit requires exactly one original story")
        if len(refs) != len(set(refs)):
            raise ValueError("audit story refs must be unique")
        if self.outcome == "coherent":
            if self.diagnosis.shared_specific_core_uk is None:
                raise ValueError("coherent audit requires a shared specific core")
            if self.diagnosis.shared_only_broad_theme_uk is not None:
                raise ValueError("coherent audit cannot rely on only a broad theme")
            if self.diagnosis.merge_blockers_uk:
                raise ValueError("coherent audit cannot contain merge blockers")
            if len(self.stories) != 1:
                raise ValueError("coherent audit requires only the original story")
        if self.outcome == "split":
            if len(self.diagnosis.split_story_cores_uk) < 2:
                raise ValueError("split audit requires at least two split story cores")
            if len(self.stories) < 2:
                raise ValueError("split audit requires at least two stories")
        for story in self.stories:
            if len(story.article_ids) != len(set(story.article_ids)):
                raise ValueError("story article ids must be unique")
        detached_ids = [article.article_id for article in self.detached_articles]
        if len(detached_ids) != len(set(detached_ids)):
            raise ValueError("detached article ids must be unique")
        assigned_ids = {article_id for story in self.stories for article_id in story.article_ids}
        if assigned_ids & set(detached_ids):
            raise ValueError("audit cannot both assign and detach an article")
        return self


class CasePublicInterestDiagnosis(StrictOutput):
    """Short factual checks before deciding whether a Case stays public."""

    concrete_story_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке конкретне ядро історії, якщо воно підтверджене контекстом.",
    )
    public_interest_anchor_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий якір суспільної важливості або підзвітності.",
    )
    durability_signal_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий факт про тривалий розвиток або майбутні етапи справи.",
    )
    hide_signals_uk: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Короткі сигнали, що справа є шумом або звичайною хронікою.",
    )


class CasePublicInterestAuditOutput(StrictOutput):
    """Decision whether one Case remains a durable public-interest story."""

    diagnosis: CasePublicInterestDiagnosis = Field(
        description="Коротка структурована діагностика перед рішенням про видимість справи.",
    )
    reason_uk: str = Field(
        min_length=1,
        max_length=320,
        description="Фактична підстава рішення.",
    )
    outcome: Literal["keep", "hide", "inconclusive"] = Field(
        description="Підсумок перевірки суспільної важливості."
    )

    @model_validator(mode="after")
    def validate_outcome(self) -> CasePublicInterestAuditOutput:
        """Require explicit evidence for keep or hide outcomes."""

        if self.outcome == "keep":
            if self.diagnosis.concrete_story_core_uk is None:
                raise ValueError("keep requires a concrete story core")
            if self.diagnosis.public_interest_anchor_uk is None:
                raise ValueError("keep requires a public-interest anchor")
            if self.diagnosis.durability_signal_uk is None:
                raise ValueError("keep requires a durability signal")
            if self.diagnosis.hide_signals_uk:
                raise ValueError("keep cannot include hide signals")
            durability = self.diagnosis.durability_signal_uk.casefold()
            if any(marker in durability for marker in _SPECULATIVE_DURABILITY_MARKERS):
                raise ValueError(
                    "keep requires an observed durability signal, not a speculative one"
                )
        if self.outcome == "hide" and not self.diagnosis.hide_signals_uk:
            raise ValueError("hide requires at least one hide signal")
        return self


class CaseDuplicateDiagnosis(StrictOutput):
    """Short factual checks before deciding whether two Cases duplicate each other."""

    case_a_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке конкретне ядро справи A.",
    )
    case_b_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Коротке конкретне ядро справи B.",
    )
    shared_specific_core_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Одне спільне конкретне ядро, якщо обидві справи описують ту саму історію.",
    )
    relation_anchor_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий сильний якір корисного зв'язку між різними справами.",
    )
    only_broad_overlap_uk: str | None = Field(
        default=None,
        max_length=240,
        description="Короткий факт, якщо збіг є лише широким або інституційним.",
    )
    merge_blockers_uk: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Короткі факти, що заважають merge двох справ.",
    )


class CaseDuplicateAuditOutput(StrictOutput):
    """Decision for one possible duplicate Case pair."""

    diagnosis: CaseDuplicateDiagnosis = Field(
        description="Коротка структурована діагностика перед рішенням щодо пари справ.",
    )
    reason_uk: str = Field(
        min_length=1,
        max_length=320,
        description="Фактична підстава рішення щодо пари.",
    )
    outcome: Literal["merge", "related", "distinct", "inconclusive"] = Field(
        description="Підсумок перевірки можливої тотожності справ."
    )

    @model_validator(mode="after")
    def validate_outcome(self) -> CaseDuplicateAuditOutput:
        """Require diagnosis support for merge or related outcomes."""

        if self.outcome == "merge":
            if self.diagnosis.shared_specific_core_uk is None:
                raise ValueError("merge requires a shared specific core")
            if self.diagnosis.merge_blockers_uk:
                raise ValueError("merge cannot contain merge blockers")
        if self.outcome == "related" and self.diagnosis.relation_anchor_uk is None:
            raise ValueError("related requires a relation anchor")
        if self.outcome == "distinct" and self.diagnosis.only_broad_overlap_uk is None:
            raise ValueError("distinct requires a broad-overlap diagnosis")
        return self
