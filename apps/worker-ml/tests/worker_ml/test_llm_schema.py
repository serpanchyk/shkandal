"""Tests for model-facing LLM schemas."""

from typing import Any

from worker_ml.llm.contracts import ArticleCardOutput, EntityResolutionOutput
from worker_ml.llm.schema import prompt_schema


def test_prompt_schema_contains_no_enum_or_const_constraints() -> None:
    schema = prompt_schema(EntityResolutionOutput)

    assert not _contains_key(schema, "enum")
    assert not _contains_key(schema, "const")


def test_prompt_schema_places_decision_basis_before_article_choice() -> None:
    properties = list(prompt_schema(ArticleCardOutput)["properties"])

    assert properties.index("case_decision_reason_uk") < properties.index("is_case_candidate")


def test_prompt_schema_places_resolution_reason_before_action() -> None:
    schema = prompt_schema(EntityResolutionOutput)
    decision_properties = list(schema["$defs"]["EntityResolutionDecision"]["properties"])

    assert decision_properties.index("reason_uk") < decision_properties.index("action")


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False
