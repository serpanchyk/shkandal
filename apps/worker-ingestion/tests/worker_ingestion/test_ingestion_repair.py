from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from worker_ingestion.maintenance.repair import repair_missing_published_at
from worker_ingestion.persistence.articles import PublishedAtRepairRow


class FakeRepairRepository:
    def __init__(self, rows: list[PublishedAtRepairRow]) -> None:
        self.rows = sorted(rows, key=lambda row: (row.created_at, row.article_id))
        self.fetch_limits: list[int | None] = []
        self.updated: dict[UUID, datetime] = {}

    async def fetch_articles_missing_published_at_batch(
        self,
        *,
        source_slug: str | None,
        limit: int | None,
        after_created_at: datetime | None,
        after_article_id: UUID | None,
    ) -> list[PublishedAtRepairRow]:
        self.fetch_limits.append(limit)
        rows = [row for row in self.rows if source_slug is None or row.source_slug == source_slug]
        if after_created_at is not None and after_article_id is not None:
            rows = [
                row
                for row in rows
                if (row.created_at, row.article_id) > (after_created_at, after_article_id)
            ]
        return rows[:limit] if limit is not None else rows

    async def update_article_published_at(self, article_id: UUID, published_at: datetime) -> None:
        self.updated[article_id] = published_at


def repair_row(
    *,
    article_id: UUID | None = None,
    created_at: datetime = datetime(2026, 6, 1, tzinfo=UTC),
    source_slug: str = "example",
    url: str = "https://example.ua/news/item",
    raw_html: str = "<html><body>No date</body></html>",
) -> PublishedAtRepairRow:
    return PublishedAtRepairRow(
        article_id=article_id or uuid4(),
        created_at=created_at,
        source_slug=source_slug,
        url=url,
        raw_html=raw_html,
    )


@pytest.mark.asyncio
async def test_repair_missing_published_at_dry_run_does_not_update_rows() -> None:
    article_id = uuid4()
    repository = FakeRepairRepository(
        [
            repair_row(
                article_id=article_id,
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
            repair_row(
                article_id=parseable_id,
                raw_html="""<html><body>
                  <time itemprop="datePublished" content="2026-06-02 18:49:39">2 червня</time>
                </body></html>""",
            ),
            repair_row(
                article_id=invalid_id,
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


@pytest.mark.asyncio
async def test_repair_missing_published_at_batches_unlimited_repairs() -> None:
    rows = [
        repair_row(
            created_at=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(minutes=index),
            raw_html="""<html><head>
              <meta property="article:published_time" content="2026-06-02T09:35:00+03:00" />
            </head></html>""",
        )
        for index in range(5)
    ]
    repository = FakeRepairRepository(rows)

    stats = await repair_missing_published_at(repository, apply=False, batch_size=2)

    assert stats.scanned_articles == 5
    assert stats.repairable_articles == 5
    assert stats.updated_articles == 0
    assert repository.fetch_limits == [2, 2, 2, 2]


@pytest.mark.asyncio
async def test_repair_missing_published_at_caps_final_batch_by_limit() -> None:
    rows = [
        repair_row(created_at=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(minutes=index))
        for index in range(5)
    ]
    repository = FakeRepairRepository(rows)

    stats = await repair_missing_published_at(
        repository,
        limit=3,
        batch_size=2,
    )

    assert stats.scanned_articles == 3
    assert repository.fetch_limits == [2, 1]


@pytest.mark.asyncio
async def test_repair_missing_published_at_rejects_invalid_batch_size() -> None:
    repository = FakeRepairRepository([])

    with pytest.raises(ValueError, match="batch_size"):
        await repair_missing_published_at(repository, batch_size=0)
