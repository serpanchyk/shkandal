"""Public reader API contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CaseSort = Literal["latest", "newest", "popular", "biggest", "trending"]


class PublicModel(BaseModel):
    """Base contract with strict public fields."""

    model_config = ConfigDict(extra="forbid")


class SourcePreview(PublicModel):
    slug: str
    name: str
    source_type: str
    homepage_url: str
    logo_path: str | None
    article_count: int | None = None


class ArticlePreview(PublicModel):
    title: str
    url: str
    published_at: datetime | None
    image_url: str | None
    source: SourcePreview


class CaseFeedItem(PublicModel):
    slug: str
    title_uk: str
    summary_uk: str
    latest_article_at: datetime | None
    article_count: int
    view_count: int
    image_url: str | None


class CaseFeedPage(PublicModel):
    items: list[CaseFeedItem]
    sort: CaseSort
    query: str | None
    page: int
    page_size: int
    total_items: int
    total_pages: int


class EntityPreview(PublicModel):
    slug: str
    canonical_name_uk: str
    entity_type: str
    description_uk: str | None
    mention_count: int


class EventPreview(PublicModel):
    slug: str
    title_uk: str
    description_uk: str | None
    event_year: int | None
    event_month: int | None
    event_day: int | None
    event_date_precision: str
    location_uk: str | None
    supporting_articles: list[ArticlePreview]


class RelatedCasePreview(PublicModel):
    slug: str
    title_uk: str
    summary_uk: str


class CasePage(PublicModel):
    slug: str
    title_uk: str
    summary_uk: str
    latest_article_at: datetime | None
    article_count: int
    event_count: int
    view_count: int
    sources: list[SourcePreview]
    entities: list[EntityPreview]
    events: list[EventPreview]
    articles: list[ArticlePreview]
    related_cases: list[RelatedCasePreview]
    disclaimer_uk: str


class EntityPage(PublicModel):
    slug: str
    canonical_name_uk: str
    entity_type: str
    aliases: list[str]
    description_uk: str
    cases: list[RelatedCasePreview]
    articles: list[ArticlePreview]


class ViewCount(PublicModel):
    view_count: int


class SitemapEntry(PublicModel):
    path: str
    updated_at: datetime
