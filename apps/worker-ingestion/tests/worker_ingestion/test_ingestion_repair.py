from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from worker_ingestion.repair import repair_missing_published_at
from worker_ingestion.storage import PublishedAtRepairRow


class FakeRepairRepository:
    def __init__(self, rows: list[PublishedAtRepairRow]) -> None:
        self.rows = rows
        self.updated: dict[UUID, datetime] = {}

    async def iter_articles_missing_published_at(
        self,
        *,
        source_slug: str | None,
        limit: int | None,
        batch_size: int,
    ) -> list[PublishedAtRepairRow]:
        rows = [row for row in self.rows if source_slug is None or row.source_slug == source_slug]
        return rows[:limit] if limit is not None else rows

    async def update_article_published_at(self, article_id: UUID, published_at: datetime) -> None:
        self.updated[article_id] = published_at


@pytest.mark.asyncio
async def test_repair_missing_published_at_dry_run_does_not_update_rows() -> None:
    article_id = uuid4()
    repository = FakeRepairRepository(
        [
            PublishedAtRepairRow(
                article_id=article_id,
                source_slug="example",
                url="https://example.ua/news/item",
                raw_html="""<html><head>
                  <script type="application/ld+json">
                  {"datePublished": "2026-06-02T09:35:00+03:00"}
                  </script>
                </head><body><article><p>Текст.</p></article></body></html>""",
            )
        ]
    )

    stats = await repair_missing_published_at(repository, apply=False)

    assert stats.scanned_articles == 1
    assert stats.repairable_articles == 1
    assert stats.updated_articles == 0
    assert repository.updated == {}


@pytest.mark.asyncio
async def test_repair_missing_published_at_apply_updates_only_parseable_rows() -> None:
    parseable_id = uuid4()
    invalid_id = uuid4()
    repository = FakeRepairRepository(
        [
            PublishedAtRepairRow(
                article_id=parseable_id,
                source_slug="example",
                url="https://example.ua/news/item",
                raw_html="""<html><body>
                  <time itemprop="datePublished" content="2026-06-02 18:49:39">2 червня</time>
                </body></html>""",
            ),
            PublishedAtRepairRow(
                article_id=invalid_id,
                source_slug="example",
                url="https://example.ua/news/invalid",
                raw_html="<html><body>No date</body></html>",
            ),
        ]
    )

    stats = await repair_missing_published_at(repository, apply=True)

    assert stats.scanned_articles == 2
    assert stats.repairable_articles == 1
    assert stats.updated_articles == 1
    assert repository.updated == {
        parseable_id: datetime(2026, 6, 2, 15, 49, 39, tzinfo=UTC),
    }
