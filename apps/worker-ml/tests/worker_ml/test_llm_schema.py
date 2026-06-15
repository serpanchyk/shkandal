"""Tests for model-facing LLM schemas."""

from typing import Any

from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseCoherenceAuditOutput,
    CaseCopyUpdateOutput,
    CaseDuplicateAuditOutput,
    CasePublicInterestAuditOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
)
from worker_ml.llm.schema import prompt_schema, runtime_schema_json

LLM_OUTPUT_MODELS = (
    ArticleCardOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
    CaseCopyUpdateOutput,
    CaseCoherenceAuditOutput,
    CasePublicInterestAuditOutput,
    CaseDuplicateAuditOutput,
)


def test_prompt_schema_contains_no_enum_or_const_constraints() -> None:
    schema = prompt_schema(EntityResolutionOutput)

    assert not _contains_key(schema, "enum")
    assert not _contains_key(schema, "const")


def test_runtime_repair_schema_retains_categorical_constraints() -> None:
    schema_json = runtime_schema_json(CasePublicInterestAuditOutput)

    assert '"enum": ["keep", "hide", "inconclusive"]' in schema_json


def test_prompt_schema_places_decision_basis_before_article_choice() -> None:
    properties = list(prompt_schema(ArticleCardOutput)["properties"])

    assert properties.index("case_decision_reason_uk") < properties.index("is_case_candidate")


def test_prompt_schema_places_resolution_reason_before_action() -> None:
    schema = prompt_schema(EntityResolutionOutput)
    decision_properties = list(schema["$defs"]["EntityResolutionDecision"]["properties"])

    assert decision_properties.index("reason_uk") < decision_properties.index("action")


def test_case_resolution_schema_requires_outcome_and_reason_before_actions() -> None:
    schema = prompt_schema(CaseResolutionOutput)
    properties = list(schema["properties"])

    assert {"decision_reason_uk", "outcome"} <= set(schema["required"])
    assert properties.index("decision_reason_uk") < properties.index("outcome")
    assert properties.index("outcome") < properties.index("existing_case_links")


def test_prompt_schemas_describe_every_property() -> None:
    for model in LLM_OUTPUT_MODELS:
        missing_descriptions = _properties_without_descriptions(prompt_schema(model))

        assert not missing_descriptions, (
            f"{model.__name__} has properties without descriptions: "
            f"{', '.join(missing_descriptions)}"
        )


def _properties_without_descriptions(
    value: Any,
    path: str = "",
) -> list[str]:
    if not isinstance(value, dict):
        return []

    missing: list[str] = []
    for name, property_schema in value.get("properties", {}).items():
        property_path = f"{path}.{name}" if path else name
        if not property_schema.get("description"):
            missing.append(property_path)
    for name, definition in value.get("$defs", {}).items():
        missing.extend(_properties_without_descriptions(definition, name))
    return missing


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False
