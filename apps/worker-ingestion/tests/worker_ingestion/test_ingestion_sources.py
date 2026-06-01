from worker_ingestion.sources import MEDIA_SOURCES, SourceConfig


def test_media_source_catalog_contains_unique_slugs() -> None:
    slugs = [source.slug for source in MEDIA_SOURCES]

    assert len(slugs) == len(set(slugs))
    assert len(MEDIA_SOURCES) == 13
    assert all(source.source_type == "media" for source in MEDIA_SOURCES)


def test_media_source_catalog_uses_current_known_sitemap_roots() -> None:
    sources = {source.slug: source for source in MEDIA_SOURCES}

    assert sources["pravda"].sitemap_urls == ("https://www.pravda.com.ua/sitemap/sitemap.xml",)
    assert (
        r"https://nashigroshi\.org/post-sitemap\d*\.xml"
        in sources["nashigroshi"].sitemap_url_patterns
    )
    assert sources["slovoidilo"].sitemap_urls == (
        "https://www.slovoidilo.ua/sitemap_index_uk.xml",
        "https://www.slovoidilo.ua/news_sitemap_uk.xml",
    )


def test_source_config_defaults_to_ukrainian_media_article_selector() -> None:
    source = SourceConfig(
        slug="example",
        name="Example",
        base_url="https://example.ua",
        sitemap_urls=("https://example.ua/sitemap.xml",),
    )

    assert source.language == "uk"
    assert source.source_type == "media"
    assert source.body_selectors == ("article",)
