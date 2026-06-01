"""Curated media source configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceConfig:
    slug: str
    name: str
    base_url: str
    sitemap_urls: tuple[str, ...]
    sitemap_url_patterns: tuple[str, ...] = ()
    include_url_patterns: tuple[str, ...] = ()
    exclude_url_patterns: tuple[str, ...] = ()
    body_selectors: tuple[str, ...] = ("article",)
    language: str = "uk"
    source_type: str = "media"
    metadata: dict[str, str] = field(default_factory=dict)


MEDIA_SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(
        slug="pravda",
        name="Українська правда",
        base_url="https://www.pravda.com.ua",
        sitemap_urls=("https://www.pravda.com.ua/sitemap.xml",),
        sitemap_url_patterns=(
            r"https://www\.pravda\.com\.ua/sitemap/sitemap-\d{4}-\d{2}\.xml\.gz",
        ),
        include_url_patterns=(r"https://www\.pravda\.com\.ua/news/.+",),
        exclude_url_patterns=(r"/rus/", r"/eng/"),
        body_selectors=("div.post_news_text", "article"),
    ),
    SourceConfig(
        slug="hromadske",
        name="hromadske",
        base_url="https://hromadske.ua",
        sitemap_urls=("https://hromadske.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://hromadske\.ua/sitemaps/posts/\d{4}/\d{1,2}\.xml",),
        exclude_url_patterns=(r"/ru/", r"/en/"),
        body_selectors=("div.s-content", "article"),
    ),
    SourceConfig(
        slug="radiosvoboda",
        name="Радіо Свобода",
        base_url="https://www.radiosvoboda.org",
        sitemap_urls=("https://www.radiosvoboda.org/sitemap.xml",),
        sitemap_url_patterns=(r"https://www\.radiosvoboda\.org/sitemap_9_latest\.xml\.gz",),
        body_selectors=("div.wsw", "article"),
    ),
    SourceConfig(
        slug="suspilne",
        name="Суспільне",
        base_url="https://suspilne.media",
        sitemap_urls=("https://suspilne.media/sitemap.xml",),
        sitemap_url_patterns=(r"https://suspilne\.media/suspilne/sitemap/post-sitemap\d+\.xml",),
        body_selectors=("div.l-article-content__container-inner", "article"),
    ),
    SourceConfig(
        slug="bihus",
        name="Bihus.Info",
        base_url="https://bihus.info",
        sitemap_urls=("https://bihus.info/sitemap.xml",),
        sitemap_url_patterns=(r"https://bihus\.info/post-sitemap\d+\.xml",),
        body_selectors=("div.bi-single-content", "article"),
    ),
    SourceConfig(
        slug="antac",
        name="Центр протидії корупції",
        base_url="https://antac.org.ua",
        sitemap_urls=("https://antac.org.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://antac\.org\.ua/news-sitemap\d+\.xml",),
        body_selectors=("article.article-content", "article"),
    ),
    SourceConfig(
        slug="nashigroshi",
        name="Наші гроші",
        base_url="https://nashigroshi.org",
        sitemap_urls=("https://nashigroshi.org/sitemap.xml",),
        sitemap_url_patterns=(r"https://nashigroshi\.org/sitemap-pt-post-\d{4}-\d{2}\.xml",),
        body_selectors=("div.column-two-third.single.article", "article"),
    ),
    SourceConfig(
        slug="babel",
        name="Бабель",
        base_url="https://babel.ua",
        sitemap_urls=("https://babel.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://babel\.ua/ukrainian/default/.+\.xml",),
        body_selectors=("div.c-post-text", "article"),
    ),
    SourceConfig(
        slug="texty",
        name="Тексти",
        base_url="https://texty.org.ua",
        sitemap_urls=("https://texty.org.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://texty\.org\.ua/sitemap-articles\.xml",),
        body_selectors=("article",),
    ),
    SourceConfig(
        slug="espreso",
        name="Еспресо",
        base_url="https://espreso.tv",
        sitemap_urls=("https://espreso.tv/sitemap.xml",),
        sitemap_url_patterns=(r"https://espreso\.tv/sitemap_news_\d+\.xml",),
        body_selectors=("section.content_current_article", "article"),
    ),
    SourceConfig(
        slug="slovoidilo",
        name="Слово і Діло",
        base_url="https://www.slovoidilo.ua",
        sitemap_urls=("https://www.slovoidilo.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://www\.slovoidilo\.ua/sitemap/monthly_\d{4}-\d{2}_uk\.xml",),
        body_selectors=("div.article-body", "article"),
    ),
    SourceConfig(
        slug="tyzhden",
        name="Український тиждень",
        base_url="https://tyzhden.ua",
        sitemap_urls=("https://tyzhden.ua/wp-sitemap.xml",),
        sitemap_url_patterns=(r"https://tyzhden\.ua/wp-sitemap-posts-post-\d+\.xml",),
        body_selectors=("div.entry-content", "article"),
    ),
    SourceConfig(
        slug="chesno",
        name="Рух Чесно",
        base_url="https://www.chesno.org",
        sitemap_urls=("https://www.chesno.org/sitemap.xml",),
        sitemap_url_patterns=(r"https://www\.chesno\.org/sitemap-posts\.xml",),
        body_selectors=("div.publication-row", "article"),
    ),
)
