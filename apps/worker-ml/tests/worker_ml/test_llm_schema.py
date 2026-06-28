"""Tests for model-facing LLM schemas."""

from typing import Any

from worker_ml.llm.contracts import (
    ArticleCardOutput,
    ArticleGateOutput,
    CaseCoherenceAuditOutput,
    CaseDuplicateAuditOutput,
    CaseLinkAuditOutput,
    CasePublicInterestAuditOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
    RefreshCaseOutput,
)
from worker_ml.llm.schema import prompt_schema, runtime_schema_json

LLM_OUTPUT_MODELS = (
    ArticleCardOutput,
    ArticleGateOutput,
    CaseResolutionOutput,
    CaseLinkAuditOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
    RefreshCaseOutput,
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
    properties = list(prompt_schema(ArticleGateOutput)["properties"])

    assert properties.index("case_diagnosis") < properties.index("case_decision_reason_uk")
    assert properties[-1] == "is_case_candidate"


def test_prompt_schema_places_resolution_reason_before_action() -> None:
    schema = prompt_schema(EntityResolutionOutput)
    decision_properties = list(schema["$defs"]["EntityResolutionDecision"]["properties"])

    assert decision_properties.index("diagnosis") < decision_properties.index("reason_uk")
    assert decision_properties[-1] == "action"


def test_case_resolution_schema_requires_outcome_and_reason_before_actions() -> None:
    schema = prompt_schema(CaseResolutionOutput)
    properties = list(schema["properties"])

    assert {"decision_reason_uk", "outcome"} <= set(schema["required"])
    assert properties.index("diagnosis") < properties.index("decision_reason_uk")
    assert properties[-1] == "outcome"


def test_schema_exposes_diagnosis_objects_and_terminal_choice_fields() -> None:
    schema = prompt_schema(CaseCoherenceAuditOutput)
    coherence_properties = list(schema["properties"])
    assert coherence_properties[-1] == "outcome"
    assert "diagnosis" in coherence_properties

    duplicate_properties = list(prompt_schema(CaseDuplicateAuditOutput)["properties"])
    assert duplicate_properties[-1] == "outcome"
    assert "diagnosis" in duplicate_properties

    link_properties = list(prompt_schema(CaseLinkAuditOutput)["properties"])
    assert link_properties[-1] == "outcome"
    assert "diagnosis" in link_properties

    interest_properties = list(prompt_schema(CasePublicInterestAuditOutput)["properties"])
    assert interest_properties[-1] == "outcome"
    assert "diagnosis" in interest_properties

    refresh_properties = list(prompt_schema(RefreshCaseOutput)["properties"])
    assert refresh_properties[-1] == "title_action"
    assert "title_diagnosis" in refresh_properties


def test_refresh_case_prompt_schema_does_not_cap_internal_rationale_lengths() -> None:
    schema = prompt_schema(RefreshCaseOutput)
    diagnosis_properties = schema["$defs"]["RefreshCaseTitleDiagnosis"]["properties"]

    replacement_reason = diagnosis_properties["replacement_needed_reason_uk"]["anyOf"][0]
    proposed_title_core = diagnosis_properties["proposed_title_core_uk"]["anyOf"][0]

    assert "maxLength" not in replacement_reason
    assert "maxLength" not in proposed_title_core
    assert "maxLength" not in schema["properties"]["title_reason_uk"]


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
