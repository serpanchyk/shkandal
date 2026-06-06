"""HTML article extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from worker_ingestion.articles.identity import identity_url_for_article, normalize_article_url
from worker_ingestion.discovery.sources import SourceConfig

try:
    import trafilatura
except ImportError:  # pragma: no cover - exercised only before dependency sync.
    trafilatura = None  # type: ignore[assignment]

MIN_GENERIC_TEXT_LENGTH = 120
DEFAULT_PUBLISHER_TIMEZONE = ZoneInfo("Europe/Kyiv")
UKRAINIAN_MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


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
        published_at=published_at_from_html(html, soup=soup),
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


def published_at_from_html(html: str, *, soup: BeautifulSoup | None = None) -> datetime | None:
    """Extract a normalized publication datetime from article HTML."""

    soup = soup or BeautifulSoup(html, "html.parser")
    candidates = [
        _first_meta(
            soup,
            (
                "article:published_time",
                "datePublished",
                "datepublished",
                "publishdate",
                "pubdate",
                "DC.date.issued",
                "article:modified_time",
            ),
        ),
        _first_meta_itemprop(soup, ("datePublished", "dateCreated", "dateModified")),
        _json_ld_date_published(soup),
        _time_published_value(soup),
        _trafilatura_published_date(html),
    ]
    for value in candidates:
        if not value:
            continue
        published_at = _parse_published_datetime(value)
        if published_at:
            return published_at
    return None


def _first_meta_itemprop(soup: BeautifulSoup, itemprops: tuple[str, ...]) -> str | None:
    for itemprop in itemprops:
        element = soup.find("meta", attrs={"itemprop": itemprop})
        value = _content(element)
        if value:
            return value
    return None


def _json_ld_date_published(soup: BeautifulSoup) -> str | None:
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        if not isinstance(script, Tag):
            continue
        content = script.string or script.get_text()
        if not content:
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        value = _find_json_date(payload)
        if value:
            return value
    return None


def _find_json_date(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("datePublished", "dateCreated", "dateModified"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for child in value.values():
            candidate = _find_json_date(child)
            if candidate:
                return candidate
    if isinstance(value, list):
        for child in value:
            candidate = _find_json_date(child)
            if candidate:
                return candidate
    return None


def _time_published_value(soup: BeautifulSoup) -> str | None:
    preferred = soup.find("time", attrs={"itemprop": "datePublished"})
    time_elements = [preferred] if isinstance(preferred, Tag) else []
    time_elements.extend(element for element in soup.find_all("time") if isinstance(element, Tag))
    for time_element in time_elements:
        for attribute in ("content", "datetime"):
            value = time_element.get(attribute)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _trafilatura_published_date(html: str) -> str | None:
    extract_metadata = getattr(trafilatura, "extract_metadata", None)
    if extract_metadata is None:
        return None
    metadata = extract_metadata(html)
    value = getattr(metadata, "date", None)
    return value if isinstance(value, str) and value.strip() else None


def _parse_published_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    try:
        return _as_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
    except ValueError:
        pass

    ukrainian = _parse_ukrainian_datetime(normalized)
    if ukrainian:
        return _as_utc(ukrainian)
    return None


def _parse_ukrainian_datetime(value: str) -> datetime | None:
    match = re.search(
        r"(?P<day>\d{1,2})\s+"
        r"(?P<month>[а-щьюяєіїґ]+)\s+"
        r"(?P<year>\d{4})\s*(?:р\.?)?\s*"
        r"(?:(?P<hour>\d{1,2}):(?P<minute>\d{2}))?",
        value,
        re.I,
    )
    if not match:
        return None
    month = UKRAINIAN_MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    hour = int(match.group("hour") or 0)
    minute = int(match.group("minute") or 0)
    return datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        hour,
        minute,
        tzinfo=DEFAULT_PUBLISHER_TIMEZONE,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=DEFAULT_PUBLISHER_TIMEZONE)
    return value.astimezone(UTC)


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
