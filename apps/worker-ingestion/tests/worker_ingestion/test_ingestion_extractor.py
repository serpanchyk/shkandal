from datetime import UTC, datetime

from conftest import source_config
from worker_ingestion.extractor import extract_article


def test_extract_article_uses_generic_metadata_and_body_selectors() -> None:
    html = """<!doctype html>
    <html lang="uk">
      <head>
        <link rel="canonical" href="https://example.ua/news/item/">
        <meta property="og:title" content="Заголовок">
        <meta property="og:description" content="Короткий опис">
        <meta name="author" content="Автор">
        <meta property="article:published_time" content="2026-06-01T12:30:00+00:00">
        <meta property="og:image" content="/image.jpg">
      </head>
      <body><article><p>Перший абзац.</p><p>Другий абзац.</p></article></body>
    </html>
    """

    article = extract_article(
        source_config(),
        url="https://example.ua/news/item?utm_source=x",
        html=html,
    )

    assert article.identity_url == "https://example.ua/news/item"
    assert article.title == "Заголовок"
    assert article.lead == "Короткий опис"
    assert article.author == "Автор"
    assert article.published_at == datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    assert article.source_language == "uk"
    assert article.remote_image_url == "https://example.ua/image.jpg"
    assert article.extracted_text == "Перший абзац.\n\nДругий абзац."


def test_extract_article_uses_generic_fallbacks() -> None:
    html = """<html lang="uk"><head></head><body>
      <article>
        <h1>Fallback title</h1>
        <time datetime="2026-06-01T12:00:00+00:00">1 червня</time>
        <p>Перший абзац.</p>
        <p>Другий абзац.</p>
      </article>
    </body></html>"""

    article = extract_article(source_config(), url="https://example.ua/news/fallback", html=html)

    assert article.title == "Fallback title"
    assert article.published_at == datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert article.source_language == "uk"
    assert article.extracted_text == "Перший абзац.\n\nДругий абзац."


def test_extract_article_returns_none_for_invalid_publication_date_and_empty_body() -> None:
    html = """<html><head>
      <meta property="article:published_time" content="not-a-date">
    </head><body><article></article></body></html>"""

    article = extract_article(source_config(), url="https://example.ua/news/empty", html=html)

    assert article.published_at is None
    assert article.extracted_text is None
