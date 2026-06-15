"""Case resolution, copy, and audit LLM contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from worker_ml.llm.contracts.types import CaseRelationType, StrictOutput


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
