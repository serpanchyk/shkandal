"""Tests for prompt registry behavior."""

from worker_ml.llm.prompts import PROMPTS, PromptRegistry


def test_prompt_registry_loads_all_registered_prompts() -> None:
    registry = PromptRegistry()

    for name, definition in PROMPTS.items():
        prompt = registry.chat_prompt(name)

        assert registry.load_text(name)
        assert definition.name == name
        assert set(definition.input_variables) == set(prompt.input_variables)


def test_article_card_prompt_rejects_routine_crime_without_narrowing_public_tracks() -> None:
    text = PromptRegistry().load_text("article_card")

    assert "рутинна кримінальна та інцидентна хроніка не є справами Shkandal" in text
    assert "Процесуальна дія на кшталт підозри" in text
    assert "`main_event_title_uk = null`, `events = []`, `entities = []`" in text
    assert "формальний етап вступу до ЄС" in text
    assert "Ukraine Facility" in text
    assert "Неназваних загальних учасників можна згадувати в описі події" in text
    assert "Не використовуй самі по собі загальні процедурні" in text
    assert "`У Києві водій вкусив поліцейського` — не справа" in text


def test_case_coherence_audit_prompt_requires_story_reasons() -> None:
    text = PromptRegistry().load_text("case_coherence_audit")

    assert "кожна історія мусить мати власний `reason_uk`" in text
    assert "кожен вхідний `article_id` мусить належати щонайменше одній історії" in text
    assert "`previous_invalid_audit` і `coverage_validation_error`" in text
    assert "поверни `inconclusive`" in text


def test_case_resolution_prompt_supports_explicit_rejection() -> None:
    text = PromptRegistry().load_text("case_resolution")

    assert '`outcome = "rejected"`' in text
    assert '`outcome = "resolved"`' in text
    assert "порожні `existing_case_links`, `new_cases` та `case_relations`" in text
    assert "`decision_reason_uk`" in text
