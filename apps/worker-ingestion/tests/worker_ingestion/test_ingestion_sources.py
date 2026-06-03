from worker_ingestion.sources import CURATED_SOURCES, MEDIA_SOURCES, SourceConfig


def test_curated_source_catalog_contains_unique_slugs_and_expected_types() -> None:
    slugs = [source.slug for source in CURATED_SOURCES]

    assert len(slugs) == len(set(slugs))
    assert {source.source_type for source in CURATED_SOURCES} >= {
        "media",
        "institution",
        "court",
        "government",
        "parliament",
        "law_enforcement",
    }
    assert {source.slug for source in CURATED_SOURCES} >= {
        "nabu",
        "hcac",
        "dbr",
        "nazk",
        "arma",
        "gp",
        "ssu",
        "npu",
        "court-gov",
        "supreme-court",
        "ccu",
        "rada",
        "kmu",
        "president",
        "rnbo",
    }


def test_media_source_catalog_contains_unique_slugs() -> None:
    slugs = [source.slug for source in MEDIA_SOURCES]

    assert len(slugs) == len(set(slugs))
    assert len(MEDIA_SOURCES) == 13
    assert all(source.source_type == "media" for source in MEDIA_SOURCES)


def test_media_source_catalog_uses_current_known_sitemap_roots() -> None:
    sources = {source.slug: source for source in MEDIA_SOURCES}

    assert sources["pravda"].sitemap_urls == ("https://www.pravda.com.ua/sitemap/sitemap.xml",)
    assert (
        r"https://www\.pravda\.com\.ua/sitemap/sitemap-archive\.xml"
        in sources["pravda"].sitemap_url_patterns
    )
    assert (
        r"https://nashigroshi\.org/post-sitemap\d*\.xml"
        in sources["nashigroshi"].sitemap_url_patterns
    )
    assert sources["slovoidilo"].sitemap_urls == (
        "https://www.slovoidilo.ua/sitemap_index_uk.xml",
        "https://www.slovoidilo.ua/news_sitemap_uk.xml",
    )


def test_source_catalog_configures_verified_rss_feeds() -> None:
    sources = {source.slug: source for source in CURATED_SOURCES}

    assert sources["pravda"].rss_urls == ("https://www.pravda.com.ua/rss/view_news/",)
    assert sources["radiosvoboda"].rss_urls == ("https://www.radiosvoboda.org/rss/",)
    assert sources["bihus"].rss_urls == ("https://bihus.info/feed/",)
    assert sources["antac"].rss_urls == ("https://antac.org.ua/feed/",)
    assert sources["nashigroshi"].rss_urls == ("https://nashigroshi.org/feed/",)
    assert sources["babel"].rss_urls == ("https://babel.ua/rss.xml",)
    assert sources["texty"].rss_urls == ("https://texty.org.ua/feed.xml",)
    assert sources["espreso"].rss_urls == ("https://espreso.tv/rss",)
    assert sources["tyzhden"].rss_urls == ("https://tyzhden.ua/feed/",)
    assert sources["ccu"].rss_urls == ("https://ccu.gov.ua/rss.xml",)
    assert sources["rada"].rss_urls == ("https://www.rada.gov.ua/rss/",)


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
    assert source.rss_urls == ()
    assert source.section_urls == ()
    assert source.crawl_delay_seconds is None


def test_institutional_source_filters_registry_search_and_pdf_noise() -> None:
    sources = {source.slug: source for source in CURATED_SOURCES}

    nabu = sources["nabu"]
    assert nabu.source_type == "law_enforcement"
    assert nabu.section_urls == ("https://nabu.gov.ua/news/",)
    assert nabu.include_url_patterns == (r"https://nabu\.gov\.ua/news/[^/?#]+/?$",)
    assert any("rozshuk" in pattern for pattern in nabu.exclude_url_patterns)
    assert any("pdf" in pattern for pattern in nabu.exclude_url_patterns)
