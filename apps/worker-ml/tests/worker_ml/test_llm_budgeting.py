from worker_ml.llm.budgeting import (
    budget_text,
    compact_article_cards,
    count_metadata,
    first_latest_sample,
    lifecycle_sample,
    prompt_size_chars,
)


def test_budget_text_reports_truncation() -> None:
    budget = budget_text("abcdef", limit=3)

    assert budget.text == "abc"
    assert budget.original_chars == 6
    assert budget.included_chars == 3
    assert budget.truncated is True


def test_first_latest_sample_preserves_earliest_and_latest_cards() -> None:
    cards = [{"position": index} for index in range(12)]

    assert first_latest_sample(cards, limit=6) == [
        {"position": 0},
        {"position": 1},
        {"position": 2},
        {"position": 9},
        {"position": 10},
        {"position": 11},
    ]


def test_lifecycle_sample_preserves_full_span() -> None:
    cards = [{"position": index} for index in range(100)]

    sample = lifecycle_sample(cards, limit=6)

    assert len(sample) == 6
    assert sample[0] == {"position": 0}
    assert sample[-1] == {"position": 99}
    assert [card["position"] for card in sample] == sorted(card["position"] for card in sample)


def test_compact_article_cards_keeps_only_factual_context() -> None:
    assert compact_article_cards(
        [
            {
                "article_id": "article-a",
                "published_at": "2026-06-15",
                "title_uk": "Назва",
                "summary_uk": "Опис",
                "entities": [{"name": "Не потрібно"}],
            }
        ]
    ) == [
        {
            "article_id": "article-a",
            "published_at": "2026-06-15",
            "title_uk": "Назва",
            "summary_uk": "Опис",
        }
    ]


def test_count_metadata_uses_standard_fields() -> None:
    assert count_metadata(prefix="article_card", original_count=10, included_count=4) == {
        "article_card_count": 10,
        "included_article_card_count": 4,
        "input_truncated": True,
    }


def test_prompt_size_chars_sums_payload_parts() -> None:
    assert prompt_size_chars("abc", "de") == 5
