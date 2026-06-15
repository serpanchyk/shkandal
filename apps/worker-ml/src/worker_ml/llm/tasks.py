"""Registry of structured LLM task behavior."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseCoherenceAuditOutput,
    CaseCopyUpdateOutput,
    CaseDuplicateAuditOutput,
    CasePublicInterestAuditOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
    LlmRunType,
)
from worker_ml.llm.normalization import NormalizationResult, normalize_llm_output


@dataclass(frozen=True)
class LlmTaskDefinition:
    """Contract and normalization rules for one structured LLM task."""

    output_model: type[BaseModel]
    allow_top_level_array: bool = False

    def normalize(
        self,
        *,
        run_type: LlmRunType,
        output: Any,
        variables: Mapping[str, Any],
    ) -> NormalizationResult:
        """Normalize provider output according to this task's rules."""

        return normalize_llm_output(run_type=run_type, output=output, variables=variables)


LLM_TASKS: dict[LlmRunType, LlmTaskDefinition] = {
    "article_card": LlmTaskDefinition(ArticleCardOutput),
    "case_resolution": LlmTaskDefinition(CaseResolutionOutput),
    "entity_resolution": LlmTaskDefinition(EntityResolutionOutput, allow_top_level_array=True),
    "event_resolution": LlmTaskDefinition(EventResolutionOutput, allow_top_level_array=True),
    "case_copy_update": LlmTaskDefinition(CaseCopyUpdateOutput),
    "case_coherence_audit": LlmTaskDefinition(CaseCoherenceAuditOutput),
    "case_public_interest_audit": LlmTaskDefinition(CasePublicInterestAuditOutput),
    "case_duplicate_audit": LlmTaskDefinition(CaseDuplicateAuditOutput),
}
