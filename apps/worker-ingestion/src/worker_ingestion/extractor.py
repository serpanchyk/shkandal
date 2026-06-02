"""HTML article extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from worker_ingestion.identity import identity_url_for_article, normalize_article_url
from worker_ingestion.sources import SourceConfig

try:
    import trafilatura
except ImportError:  # pragma: no cover - exercised only before dependency sync.
    trafilatura = None  # type: ignore[assignment]

MIN_GENERIC_TEXT_LENGTH = 120


@dataclass(frozen=True)
class ExtractedArticle:
    identity_url: str
    title: str | None
    lead: str | None
    author: str | None
    published_at: datetime | None
    source_language: str | None
    extracted_text: str | None
    remote_image_url: str | None


def extract_article(source: SourceConfig, *, url: str, html: str) -> ExtractedArticle:
    """Extract article fields from one HTML page."""

    soup = BeautifulSoup(html, "html.parser")
    return ExtractedArticle(
        identity_url=identity_url_for_article(url, html),
        title=_first_meta(soup, ("og:title", "twitter:title")) or _text(soup.find("h1")),
        lead=_first_meta(soup, ("og:description", "description", "twitter:description")),
        author=_first_meta_by_name(soup, ("author",)),
        published_at=_published_at(soup),
        source_language=_html_language(soup) or source.language,
        extracted_text=_article_text(html, soup, source.body_selectors),
        remote_image_url=_normalized_image_url(
            _first_meta(soup, ("og:image", "twitter:image")),
            page_url=url,
        ),
    )


def _first_meta(soup: BeautifulSoup, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        element = soup.find("meta", property=key) or soup.find("meta", attrs={"name": key})
        value = _content(element)
        if value:
            return value
    return None


def _first_meta_by_name(soup: BeautifulSoup, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = _content(soup.find("meta", attrs={"name": name}))
        if value:
            return value
    return None


def _content(element: Tag | None) -> str | None:
    if not element:
        return None
    value = element.get("content")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _text(element: Tag | None) -> str | None:
    if not element:
        return None
    value = element.get_text(" ", strip=True)
    return value or None


def _published_at(soup: BeautifulSoup) -> datetime | None:
    value = _first_meta(soup, ("article:published_time", "article:modified_time"))
    if not value:
        time_element = soup.find("time")
        if isinstance(time_element, Tag):
            datetime_attr = time_element.get("datetime")
            value = datetime_attr if isinstance(datetime_attr, str) else None
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _html_language(soup: BeautifulSoup) -> str | None:
    html = soup.find("html")
    if not isinstance(html, Tag):
        return None
    language = html.get("lang")
    return language if isinstance(language, str) and language else None


def _body_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        element = soup.select_one(selector)
        if not isinstance(element, Tag):
            continue
        paragraphs = [
            paragraph.get_text(" ", strip=True)
            for paragraph in element.find_all("p")
            if paragraph.get_text(" ", strip=True)
        ]
        if paragraphs:
            return "\n\n".join(paragraphs)
        text = element.get_text(" ", strip=True)
        if text:
            return text
    return None


def _article_text(html: str, soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    generic_text = _generic_text(html)
    if generic_text and len(generic_text) >= MIN_GENERIC_TEXT_LENGTH:
        return generic_text
    return _body_text(soup, selectors) or generic_text


def _generic_text(html: str) -> str | None:
    if trafilatura is None:
        return None
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        output_format="txt",
    )
    if not text:
        return None
    return text.strip() or None


def _normalized_image_url(url: str | None, *, page_url: str) -> str | None:
    if not url:
        return None
    return normalize_article_url(url, base_url=page_url)
