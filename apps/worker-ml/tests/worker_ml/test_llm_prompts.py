"""Tests for prompt registry behavior."""

from worker_ml.llm.prompts import PROMPTS, PromptRegistry


def test_prompt_registry_loads_all_registered_prompts() -> None:
    registry = PromptRegistry()

    for name, definition in PROMPTS.items():
        prompt = registry.chat_prompt(name)

        assert registry.load_text(name)
        assert definition.name == name
        assert set(definition.input_variables) == set(prompt.input_variables)


def test_case_coherence_audit_prompt_requires_story_reasons() -> None:
    text = PromptRegistry().load_text("case_coherence_audit")

    assert "кожна історія мусить мати власний `reason_uk`" in text
    assert "кожен вхідний `article_id` мусить належати щонайменше одній історії" in text
    assert "`previous_invalid_audit` і `coverage_validation_error`" in text
    assert "поверни `inconclusive`" in text
