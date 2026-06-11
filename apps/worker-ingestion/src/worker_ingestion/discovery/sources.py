"""Curated source configuration.

Live ingestion validation, 2026-06-02:

Works: pravda, hromadske, radiosvoboda, suspilne, bihus, antac,
nashigroshi, babel, texty, espreso, slovoidilo, tyzhden, chesno, hcac,
nazk, arma, gp, npu, court-gov, supreme-court, ccu, rada, rnbo.

Retry with browser impersonation: nabu, dbr, ssu, kmu, president.

Prior broken-source reasons:
- nabu blocks the configured transparent project user-agent with HTTP 403.
- dbr has an incomplete TLS certificate chain in this runtime; it works only
  with certificate verification disabled, which ingestion should not do by
  default.
- ssu and president return Akamai-style HTTP 403 Access Denied for project and
  browser user-agents from this environment.
- kmu exposes discoverable sitemap URLs but article and API fetches are
  redirected to a Radware captcha page, so extracted text is captcha content.
These sources now use the same browser-impersonated transport as pravda.
Validation on 2026-06-05 showed nabu, ssu, and president can fetch and extract
sample articles; dbr still fails on its TLS chain, and kmu needs a discovery
fix after its timeline endpoint returns 200 without discovered article URLs.

Robots-only 404/403 is not treated as ingestion failure when section/article
discovery and extraction work.

RSS validation, 2026-06-03:

Verified RSS feeds are configured for daily low-cost discovery where they expose
parser-valid article URLs. No reliable RSS/Atom feed was found for hromadske,
suspilne, slovoidilo, chesno, hcac, nazk, arma, gp, npu, court-gov,
supreme-court, rnbo, or the blocked sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceConfig:
    slug: str
    name: str
    base_url: str
    sitemap_urls: tuple[str, ...] = ()
    sitemap_url_patterns: tuple[str, ...] = ()
    rss_urls: tuple[str, ...] = ()
    section_urls: tuple[str, ...] = ()
    include_url_patterns: tuple[str, ...] = ()
    exclude_url_patterns: tuple[str, ...] = ()
    body_selectors: tuple[str, ...] = ("article",)
    crawl_delay_seconds: float | None = None
    discovery_notes: str | None = None
    language: str = "uk"
    source_type: str = "media"
    logo_path: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


CURATED_SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(
        slug="pravda",
        name="Українська правда",
        base_url="https://www.pravda.com.ua",
        sitemap_urls=("https://www.pravda.com.ua/sitemap/sitemap.xml",),
        sitemap_url_patterns=(
            r"https://www\.pravda\.com\.ua/sitemap/sitemap-archive\.xml",
            r"https://www\.pravda\.com\.ua/sitemap/sitemap-now\.xml\.gz",
            r"https://www\.pravda\.com\.ua/sitemap/sitemap-news\.xml",
            r"https://www\.pravda\.com\.ua/sitemap/sitemap-\d{4}-\d{2}\.xml\.gz",
        ),
        rss_urls=("https://www.pravda.com.ua/rss/view_news/",),
        include_url_patterns=(r"https://www\.pravda\.com\.ua/news/.+",),
        exclude_url_patterns=(r"/rus/", r"/eng/"),
        body_selectors=("div.post_news_text", "article"),
        crawl_delay_seconds=0.5,
        logo_path="/sources/pravda.svg",
    ),
    SourceConfig(
        slug="hromadske",
        name="hromadske",
        base_url="https://hromadske.ua",
        sitemap_urls=("https://hromadske.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://hromadske\.ua/sitemaps/posts/\d{4}/\d{1,2}\.xml",),
        exclude_url_patterns=(r"/ru/", r"/en/"),
        body_selectors=("div.s-content", "article"),
        logo_path="/sources/hromadske.svg",
    ),
    SourceConfig(
        slug="radiosvoboda",
        name="Радіо Свобода",
        base_url="https://www.radiosvoboda.org",
        sitemap_urls=("https://www.radiosvoboda.org/sitemap.xml",),
        sitemap_url_patterns=(r"https://www\.radiosvoboda\.org/sitemap_9_latest\.xml\.gz",),
        rss_urls=("https://www.radiosvoboda.org/rss/",),
        body_selectors=("div.wsw", "article"),
        logo_path="/sources/radiosvoboda.svg",
    ),
    SourceConfig(
        slug="suspilne",
        name="Суспільне",
        base_url="https://suspilne.media",
        sitemap_urls=("https://suspilne.media/sitemap.xml",),
        sitemap_url_patterns=(r"https://suspilne\.media/suspilne/sitemap/post-sitemap\d+\.xml",),
        body_selectors=("div.l-article-content__container-inner", "article"),
        logo_path="/sources/suspilne.svg",
    ),
    SourceConfig(
        slug="bihus",
        name="Bihus.Info",
        base_url="https://bihus.info",
        sitemap_urls=("https://bihus.info/sitemap.xml",),
        sitemap_url_patterns=(r"https://bihus\.info/post-sitemap\d+\.xml",),
        rss_urls=("https://bihus.info/feed/",),
        body_selectors=("div.bi-single-content", "article"),
        logo_path="/sources/bihus.svg",
    ),
    SourceConfig(
        slug="antac",
        name="Центр протидії корупції",
        base_url="https://antac.org.ua",
        sitemap_urls=("https://antac.org.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://antac\.org\.ua/news-sitemap\d+\.xml",),
        rss_urls=("https://antac.org.ua/feed/",),
        body_selectors=("article.article-content", "article"),
    ),
    SourceConfig(
        slug="nashigroshi",
        name="Наші гроші",
        base_url="https://nashigroshi.org",
        sitemap_urls=("https://nashigroshi.org/sitemap.xml",),
        sitemap_url_patterns=(r"https://nashigroshi\.org/post-sitemap\d*\.xml",),
        rss_urls=("https://nashigroshi.org/feed/",),
        body_selectors=("div.column-two-third.single.article", "article"),
    ),
    SourceConfig(
        slug="babel",
        name="Бабель",
        base_url="https://babel.ua",
        sitemap_urls=("https://babel.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://babel\.ua/ukrainian/default/.+\.xml",),
        rss_urls=("https://babel.ua/rss.xml",),
        body_selectors=("div.c-post-text", "article"),
    ),
    SourceConfig(
        slug="texty",
        name="Тексти",
        base_url="https://texty.org.ua",
        sitemap_urls=("https://texty.org.ua/sitemap.xml",),
        sitemap_url_patterns=(r"https://texty\.org\.ua/sitemap-articles\.xml",),
        rss_urls=("https://texty.org.ua/feed.xml",),
        include_url_patterns=(r"https://texty\.org\.ua/articles/.+",),
        body_selectors=("article",),
    ),
    SourceConfig(
        slug="espreso",
        name="Еспресо",
        base_url="https://espreso.tv",
        sitemap_urls=("https://espreso.tv/sitemap.xml",),
        sitemap_url_patterns=(r"https://espreso\.tv/sitemap_news_\d+\.xml",),
        rss_urls=("https://espreso.tv/rss",),
        body_selectors=("section.content_current_article", "article"),
    ),
    SourceConfig(
        slug="slovoidilo",
        name="Слово і Діло",
        base_url="https://www.slovoidilo.ua",
        sitemap_urls=(
            "https://www.slovoidilo.ua/sitemap_index_uk.xml",
            "https://www.slovoidilo.ua/news_sitemap_uk.xml",
        ),
        sitemap_url_patterns=(r"https://www\.slovoidilo\.ua/sitemap/monthly_\d{4}-\d{2}_uk\.xml",),
        body_selectors=("div.article-body", "article"),
    ),
    SourceConfig(
        slug="tyzhden",
        name="Український тиждень",
        base_url="https://tyzhden.ua",
        sitemap_urls=("https://tyzhden.ua/wp-sitemap.xml",),
        sitemap_url_patterns=(r"https://tyzhden\.ua/wp-sitemap-posts-post-\d+\.xml",),
        rss_urls=("https://tyzhden.ua/feed/",),
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
    SourceConfig(
        slug="nabu",
        name="Національне антикорупційне бюро України",
        base_url="https://nabu.gov.ua",
        section_urls=("https://nabu.gov.ua/news/",),
        include_url_patterns=(r"https://nabu\.gov\.ua/news/[^/?#]+/?$",),
        exclude_url_patterns=(
            r"/en/",
            r"[?&]s=",
            r"/page/",
            r"/rozporyadzhennya",
            r"/povistky",
            r"/rozshuk",
            r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)",
        ),
        source_type="law_enforcement",
        discovery_notes="Official news section only; registry/document pages are excluded.",
    ),
    SourceConfig(
        slug="hcac",
        name="Вищий антикорупційний суд",
        base_url="https://hcac.court.gov.ua",
        section_urls=(
            "https://hcac.court.gov.ua/hcac/pres-centr/news/",
            "https://hcac.court.gov.ua/hcac/info_sud/news",
        ),
        include_url_patterns=(
            r"https://hcac\.court\.gov\.ua/hcac/(?:pres-centr/news|info_sud/news)/\d+/?$",
        ),
        source_type="court",
    ),
    SourceConfig(
        slug="dbr",
        name="Державне бюро розслідувань",
        base_url="https://dbr.gov.ua",
        section_urls=("https://dbr.gov.ua/news",),
        include_url_patterns=(r"https://dbr\.gov\.ua/news/[^/?#]+/?$",),
        exclude_url_patterns=(
            r"/(?:assets|admin|search)(?:/|$)",
            r"\.(?:pdf|docx?|xlsx?|zip|jpg|jpeg|png|webp)(?:$|\?)",
        ),
        source_type="law_enforcement",
    ),
    SourceConfig(
        slug="nazk",
        name="Національне агентство з питань запобігання корупції",
        base_url="https://nazk.gov.ua",
        section_urls=("https://nazk.gov.ua/uk/novyny/",),
        include_url_patterns=(r"https://nazk\.gov\.ua/uk/novyny/[^/?#]+/?$",),
        exclude_url_patterns=(
            r"/(?:declarations|dashboard|documents|uploads)(?:/|$)",
            r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)",
        ),
        source_type="institution",
    ),
    SourceConfig(
        slug="arma",
        name="АРМА",
        base_url="https://arma.gov.ua",
        section_urls=("https://arma.gov.ua/news",),
        include_url_patterns=(r"https://arma\.gov\.ua/news/typical/[^/?#]+/?$",),
        exclude_url_patterns=(r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)",),
        source_type="institution",
    ),
    SourceConfig(
        slug="gp",
        name="Офіс Генерального прокурора",
        base_url="https://gp.gov.ua",
        section_urls=("https://gp.gov.ua/ua/categories/novini",),
        include_url_patterns=(r"https://gp\.gov\.ua/ua/posts/[^/?#]+/?$",),
        exclude_url_patterns=(
            r"https://[^/]+\.gp\.gov\.ua/",
            r"/ua/posts/(?:kontakti-dlya-zmi|sajti-oblasnih-prokuratur)/?$",
            r"/(?:documents|search)(?:/|$)",
            r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)",
        ),
        source_type="law_enforcement",
        discovery_notes=(
            "Official news category and post/article paths only; regional subdomains are excluded."
        ),
    ),
    SourceConfig(
        slug="ssu",
        name="Служба безпеки України",
        base_url="https://ssu.gov.ua",
        section_urls=("https://ssu.gov.ua/novyny",),
        include_url_patterns=(r"https://ssu\.gov\.ua/novyny/[^/?#]+/?$",),
        exclude_url_patterns=(r"/en/", r"/(?:gallery|search)(?:/|$)"),
        source_type="law_enforcement",
    ),
    SourceConfig(
        slug="npu",
        name="Національна поліція України",
        base_url="https://npu.gov.ua",
        section_urls=("https://npu.gov.ua/api/timeline?type=posts&category_id=35&page=1",),
        include_url_patterns=(r"https://npu\.gov\.ua/news/[^/?#]+/?$",),
        exclude_url_patterns=(
            r"/search(?:/|$)",
            r"\.(?:pdf|docx?|xlsx?|zip|jpg|jpeg|png|webp)(?:$|\?)",
        ),
        source_type="law_enforcement",
        discovery_notes="Official news timeline is JSON/API-backed, not server-rendered HTML.",
    ),
    SourceConfig(
        slug="court-gov",
        name="Судова влада України",
        base_url="https://court.gov.ua",
        section_urls=("https://court.gov.ua/press/news/",),
        include_url_patterns=(r"https://court\.gov\.ua/press/news/\d+/?$",),
        exclude_url_patterns=(r"/(?:fair|schedule|search|storage)(?:/|$)",),
        source_type="court",
    ),
    SourceConfig(
        slug="supreme-court",
        name="Верховний Суд",
        base_url="https://supreme.court.gov.ua",
        section_urls=("https://supreme.court.gov.ua/supreme/pres-centr/news/",),
        include_url_patterns=(r"https://supreme\.court\.gov\.ua/supreme/pres-centr/news/\d+/?$",),
        source_type="court",
    ),
    SourceConfig(
        slug="ccu",
        name="Конституційний Суд України",
        base_url="https://ccu.gov.ua",
        section_urls=("https://ccu.gov.ua/storinka/novyny",),
        include_url_patterns=(
            r"https://ccu\.gov\.ua/novyna/[^/?#]+/?$",
            r"https://ccu\.gov\.ua/.+/novyny/[^/?#]+/?$",
        ),
        rss_urls=("https://ccu.gov.ua/rss.xml",),
        exclude_url_patterns=(
            r"/(?:docs|document|rishennya|akty)(?:/|$)",
            r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)",
        ),
        source_type="court",
        discovery_notes=(
            "Canonical news section needs live validation; document libraries are excluded."
        ),
    ),
    SourceConfig(
        slug="rada",
        name="Верховна Рада України",
        base_url="https://www.rada.gov.ua",
        section_urls=(
            "https://www.rada.gov.ua/news/Novyny/",
            "https://www.rada.gov.ua/news/news_kom/",
        ),
        rss_urls=("https://www.rada.gov.ua/rss/",),
        include_url_patterns=(r"https://www\.rada\.gov\.ua/news/(?:Novyny|news_kom)/\d+\.html$",),
        exclude_url_patterns=(
            r"https://zakon\.rada\.gov\.ua/",
            r"/(?:billInfo|uploads|search)(?:/|$)",
            r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)",
        ),
        source_type="parliament",
    ),
    SourceConfig(
        slug="kmu",
        name="Кабінет Міністрів України",
        base_url="https://www.kmu.gov.ua",
        section_urls=("https://www.kmu.gov.ua/timeline?&type=posts",),
        include_url_patterns=(r"https://www\.kmu\.gov\.ua/news/[^/?#]+/?$",),
        exclude_url_patterns=(r"/(?:npas|petitions|storage|search)(?:/|$)",),
        source_type="government",
    ),
    SourceConfig(
        slug="president",
        name="Президент України",
        base_url="https://www.president.gov.ua",
        section_urls=("https://www.president.gov.ua/news",),
        include_url_patterns=(r"https://www\.president\.gov\.ua/news/[^/?#]+-\d+/?$",),
        exclude_url_patterns=(r"/(?:documents|petitions|photos|videos)(?:/|$)",),
        source_type="government",
    ),
    SourceConfig(
        slug="rnbo",
        name="Рада національної безпеки і оборони України",
        base_url="https://www.rnbo.gov.ua",
        section_urls=("https://www.rnbo.gov.ua/ua/Diialnist/",),
        include_url_patterns=(r"https://www\.rnbo\.gov\.ua/ua/Diialnist/\d+\.html$",),
        exclude_url_patterns=(r"/files(?:/|$)", r"\.(?:pdf|docx?|xlsx?|zip)(?:$|\?)"),
        source_type="government",
    ),
)

MEDIA_SOURCES: tuple[SourceConfig, ...] = tuple(
    source for source in CURATED_SOURCES if source.source_type == "media"
)
