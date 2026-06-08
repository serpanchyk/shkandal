"""Tests for prompt registry behavior."""

from worker_ml.llm.prompts import PROMPTS, PromptRegistry


def test_prompt_registry_loads_all_registered_prompts() -> None:
    registry = PromptRegistry()

    for name, definition in PROMPTS.items():
        prompt = registry.chat_prompt(name)

        assert registry.load_text(name)
        assert definition.name == name
        assert set(definition.input_variables).issubset(set(prompt.input_variables))


def test_article_card_prompt_has_strict_case_candidate_rules() -> None:
    prompt = PromptRegistry().load_text("article_card")

    assert "дипломатії, міжнародної підтримки" in prompt
    assert "рутинних регуляторних штрафів" in prompt
    assert "рутинної кримінальної хроніки" in prompt
    assert "Mercedes-Benz" in prompt
    assert "Країни не є `organization`" in prompt
    assert "Не вигадуй типи `country`, `city`, `region`" in prompt
    assert "Міста, регіони, речовини" in prompt
    assert "Це не дубль списку `entities`" in prompt
    assert "`1 млн доларів`" in prompt
    assert "`Національний банк України` зазвичай" in prompt
    assert '`noise_reason = "diplomacy"`' in prompt
    assert '`noise_reason = "policy_law"`' in prompt
    assert '`noise_reason = "routine_regulatory"`' in prompt
    assert "`Полтавапаливо`" in prompt


def test_repair_prompt_enforces_schema_limits_and_non_case_shape() -> None:
    prompt = PromptRegistry().load_text("repair")

    assert "видали елементи списків з неприпустимими типами" in prompt
    assert "якщо список перевищує максимум" in prompt
    assert "не вигадуй значення enum" in prompt
    assert "`is_case_candidate = false`" in prompt
