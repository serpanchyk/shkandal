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


def test_public_interest_prompt_blacklists_routine_crime_topics() -> None:
    prompt = PromptRegistry().load_text("case_public_interest_audit")

    assert "усіх звичайних `ДТП`" in prompt
    assert "домашнє насильство" in prompt
    assert "жорстоке поводження з дітьми" in prompt
    assert (
        "не є\n`public_interest_anchor_uk`" in prompt
        or "не є `public_interest_anchor_uk`" in prompt
    )


def test_case_resolution_prompt_blocks_institutional_umbrellas() -> None:
    prompt = PromptRegistry().load_text("case_resolution")

    assert "ВАКС — це місце розгляду та інституція, а не ідентичність справи" in prompt
    assert "`case_coherence_test_uk`" in prompt
    assert "конкретне фактичне ядро" in prompt


def test_event_resolution_prompt_uses_current_date_check() -> None:
    prompt = PromptRegistry().load_text("event_resolution")

    assert "{current_date_kyiv}" in prompt
    assert "`future_date_warning_uk`" in prompt
    assert "`temporal_scope_check_uk`" in prompt
