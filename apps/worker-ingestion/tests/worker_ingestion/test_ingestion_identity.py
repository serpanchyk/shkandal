from worker_ingestion.articles.identity import (
    canonical_url_from_html,
    identity_url_for_article,
    normalize_article_url,
)


def test_normalize_article_url_removes_common_duplicate_variants() -> None:
    assert (
        normalize_article_url("http://www.example.ua//news/item/?utm_source=tg#comments")
        == "https://example.ua/news/item"
    )


def test_normalize_article_url_preserves_unknown_query_params() -> None:
    assert (
        normalize_article_url("https://example.ua/news/item?print=1&utm_medium=social")
        == "https://example.ua/news/item?print=1"
    )


def test_normalize_article_url_normalizes_percent_encoding() -> None:
    assert (
        normalize_article_url("https://www.example.ua/news/%D1%82%D0%B5%D1%81%D1%82/")
        == "https://example.ua/news/%D1%82%D0%B5%D1%81%D1%82"
    )


def test_canonical_url_from_html_normalizes_relative_canonical_link() -> None:
    html = '<html><head><link rel="canonical" href="/news/item/?utm_source=x"></head></html>'

    assert (
        canonical_url_from_html(html, page_url="http://www.example.ua/news/item#comments")
        == "https://example.ua/news/item"
    )


def test_identity_url_falls_back_to_raw_url_when_canonical_is_missing() -> None:
    assert (
        identity_url_for_article("http://www.example.ua/news/item/?fbclid=abc", "<html></html>")
        == "https://example.ua/news/item"
    )
