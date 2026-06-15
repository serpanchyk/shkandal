"""Tests for prompt registry behavior."""

import re

from worker_ml.llm.prompts import PROMPTS, PromptRegistry


def test_prompt_registry_loads_all_registered_prompts() -> None:
    registry = PromptRegistry()

    for name, definition in PROMPTS.items():
        prompt = registry.chat_prompt(name)

        assert registry.load_text(name)
        assert definition.name == name
        assert set(definition.input_variables) == set(prompt.input_variables)


def test_key_prompts_require_pre_decision_diagnostics() -> None:
    registry = PromptRegistry()

    for name in (
        "article_card",
        "case_resolution",
        "case_coherence_audit",
        "case_duplicate_audit",
        "case_public_interest_audit",
        "entity_resolution",
        "event_resolution",
        "case_copy_update",
    ):
        prompt = registry.load_text(name)
        assert "Перед вибором" in prompt
        assert "Поле `is_case_candidate` має бути останнім" in prompt or "останнім полем" in prompt


def test_prompts_no_longer_use_old_reason_then_choose_pattern() -> None:
    registry = PromptRegistry()
    legacy_pattern = re.compile(r"спочатку.+reason_uk.+потім.+обери", re.IGNORECASE | re.DOTALL)

    for name in (
        "article_card",
        "case_coherence_audit",
        "case_duplicate_audit",
        "case_public_interest_audit",
        "entity_resolution",
        "event_resolution",
    ):
        assert legacy_pattern.search(registry.load_text(name)) is None
