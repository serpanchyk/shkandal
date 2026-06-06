"""Article URL identity helpers."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
}


def normalize_article_url(url: str, *, base_url: str | None = None) -> str:
    """Return a deterministic article identity URL."""

    absolute_url = urljoin(base_url, url.strip()) if base_url else url.strip()
    parsed = urlsplit(absolute_url)
    scheme = "https"
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    netloc = hostname
    if parsed.port and parsed.port not in {80, 443}:
        netloc = f"{hostname}:{parsed.port}"

    path = _normalize_path(parsed.path)
    query_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_PARAMS
    ]
    query = urlencode(query_params, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def canonical_url_from_html(html: str, *, page_url: str) -> str | None:
    """Extract a normalized canonical URL from HTML when available."""

    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if not canonical:
        return None
    href = canonical.get("href")
    if not isinstance(href, str) or not href.strip():
        return None
    return normalize_article_url(href, base_url=page_url)


def identity_url_for_article(raw_url: str, html: str | None = None) -> str:
    """Resolve the final article identity URL."""

    if html:
        canonical = canonical_url_from_html(html, page_url=raw_url)
        if canonical:
            return canonical
    return normalize_article_url(raw_url)


def _normalize_path(path: str) -> str:
    decoded = unquote(path or "/")
    decoded = re.sub(r"/{2,}", "/", decoded)
    normalized = posixpath.normpath(decoded)
    if decoded.endswith("/") and normalized != "/":
        normalized = normalized.rstrip("/")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized == "/":
        return ""
    return quote(normalized.rstrip("/"), safe="/-._~!$&'()*+,;=:@")
