from datetime import UTC, datetime
from uuid import uuid4

from worker_ingestion.storage import ArticleInput, SourceInput, SqlAlchemyArticleRepository


def test_source_input_preserves_source_contract_fields() -> None:
    source = SourceInput(
        slug="pravda",
        name="Українська правда",
        source_type="media",
        base_url="https://www.pravda.com.ua",
        language="uk",
        metadata={"kind": "news"},
    )

    assert source.slug == "pravda"
    assert source.source_type == "media"
    assert source.metadata == {"kind": "news"}


def test_article_input_preserves_raw_and_identity_urls_separately() -> None:
    source_id = uuid4()
    article = ArticleInput(
        source_id=source_id,
        url="http://www.example.ua/news/item?utm_source=x#comments",
        identity_url="https://example.ua/news/item",
        title="Title",
        lead=None,
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        fetched_at=datetime(2026, 6, 1, 1, tzinfo=UTC),
        source_language="uk",
        raw_html="<html></html>",
        extracted_text="Text",
        remote_image_url=None,
        remote_image_metadata={},
        source_metadata={"http_status": 200},
    )

    assert article.source_id == source_id
    assert article.url != article.identity_url
    assert article.source_metadata["http_status"] == 200


def test_sqlalchemy_repository_keeps_session_factory() -> None:
    session_factory = object()
    repository = SqlAlchemyArticleRepository(session_factory)  # type: ignore[arg-type]

    assert repository.session_factory is session_factory
