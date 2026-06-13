"""Tests for prompt registry behavior."""

import pytest
from worker_ml.llm.prompts import PROMPTS, PromptRegistry


def test_prompt_registry_loads_all_registered_prompts() -> None:
    registry = PromptRegistry()

    for name, definition in PROMPTS.items():
        prompt = registry.chat_prompt(name)

        assert registry.load_text(name)
        assert definition.name == name
        assert set(definition.input_variables) == set(prompt.input_variables)


def test_article_card_prompt_has_strict_case_candidate_rules() -> None:
    prompt = PromptRegistry().load_text("article_card")

    assert "дипломатію, переговори, міжнародну підтримку" in prompt
    assert "рутинних регуляторних штрафів" in prompt
    assert "рутинної кримінальної хроніки" in prompt
    assert "Mercedes-Benz" in prompt
    assert "Не додавай країни як `organization`" in prompt
    assert "Не використовуй інші типи, зокрема `country`, `city`, `region`" in prompt
    assert "Країни, міста, регіони, речовини" in prompt
    assert "Це не дубль `entities`" in prompt
    assert "`1 млн доларів`" in prompt
    assert "НБУ → `Національний банк України`" in prompt
    assert "шляху України до вступу в Європейський Союз" in prompt
    assert "відстежуваної зовнішньої політики України" in prompt
    assert '`noise_reason = "policy_law"`' in prompt
    assert '`noise_reason = "routine_regulatory"`' in prompt
    assert "`Полтавапаливо`" in prompt


def test_repair_prompt_enforces_schema_limits_and_non_case_shape() -> None:
    prompt = PromptRegistry().load_text("repair")

    assert "видали цей елемент зі списку" in prompt
    assert "Якщо список перевищує максимум" in prompt
    assert "Не вигадуй значення enum" in prompt
    assert "`is_case_candidate = false`" in prompt


@pytest.mark.parametrize(
    ("prompt_name", "identity_field"),
    [
        ("entity_resolution", "existing_entity_id"),
        ("event_resolution", "existing_event_id"),
    ],
)
def test_identity_resolution_prompts_restrict_existing_ids_to_same_item_candidates(
    prompt_name: str,
    identity_field: str,
) -> None:
    prompt = PromptRegistry().load_text(prompt_name)

    assert identity_field in prompt
    assert "для того самого `provisional_ref`" in prompt
    assert "`case_id`" in prompt


def test_entity_resolution_prompt_rejects_non_global_actors() -> None:
    prompt = PromptRegistry().load_text("entity_resolution")

    assert "стабільний реальний актор" in prompt
    assert "посади без імені" in prompt
    assert "анонімних осіб" in prompt
    assert "«приватна компанія»" in prompt
    assert "лише місце події" in prompt
    assert "Не створюй `unknown_actor`" in prompt


def test_entity_resolution_prompt_separates_identity_from_article_role() -> None:
    prompt = PromptRegistry().load_text("entity_resolution")

    assert "Схожість тексту" in prompt
    assert "не доводять тотожність" in prompt
    assert "не перетворюй роль зі статті на alias" in prompt
    assert "а не переказувати\nйого роль чи дію у конкретній справі" in prompt
    assert "Якщо стабільний опис неможливо сформувати з контексту" in prompt


def test_entity_resolution_prompt_limits_mutations_and_case_assignments() -> None:
    prompt = PromptRegistry().load_text("entity_resolution")

    assert "`rename_existing` або `retype_existing` лише коли кандидат точно" in prompt
    assert "Не використовуй rename для стилістичної переваги" in prompt
    assert "Кожна прийнята сутність повинна мати щонайменше один" in prompt
    assert "Використовуй лише `case_id` з `linked_cases`" in prompt
    assert "побіжну згадку, фон, місце події або історичний контекст" in prompt


def test_event_resolution_prompt_rejects_non_occurrences() -> None:
    prompt = PromptRegistry().load_text("event_resolution")

    assert "конкретна реальна occurrence" in prompt
    assert "«Подія 1»" in prompt
    assert "переказ усієї статті як одну подію" in prompt
    assert "стани без конкретної дії" in prompt
    assert "занадто широкі multi-event summaries" in prompt
    assert "неможливо відрізнити від інших схожих подій" in prompt


def test_event_resolution_prompt_requires_compatible_identity_anchors() -> None:
    prompt = PromptRegistry().load_text("event_resolution")

    assert "Відсутній anchor не є конфліктом" in prompt
    assert "Відомий суперечливий anchor забороняє merge" in prompt
    assert "процесуальний етап" in prompt
    assert "та сама справа" in prompt
    assert "недостатні для merge" in prompt
    assert "Не виправляй existing event автоматично" in prompt


def test_event_resolution_prompt_preserves_date_and_case_assignment_rules() -> None:
    prompt = PromptRegistry().load_text("event_resolution")

    assert "Не використовуй дату публікації як дату" in prompt
    assert '`event_date_precision = "unknown"`' in prompt
    assert "`YYYY-MM-DD`" in prompt
    assert "Використовуй лише `case_id` з `linked_cases`" in prompt
    assert "справді є частиною event chain" in prompt
