import asyncio
import hashlib
import html
import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx

from app.core.config import settings
from app.llm.urls import address_is_private
from app.rag.base import RetrievalResult, RetrievedChunk, Retriever

URL_PATTERN = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class WebEgressError(ValueError):
    """Raised when a web retrieval target violates the outbound URL policy."""


def _csv_domains(value: str) -> set[str]:
    return {
        item.strip().lower().lstrip(".").rstrip(".")
        for item in value.split(",")
        if item.strip()
    }


def _host_matches_domain(hostname: str, domains: set[str]) -> bool:
    return any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in domains
    )


def validate_web_url(url: str) -> str:
    """Validate URL scheme, credentials, and domain allow/block policy."""
    cleaned = url.strip().rstrip(".,;:")
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise WebEgressError("Web URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise WebEgressError("Web URL must not contain credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    blocked = _csv_domains(settings.WEB_BLOCKED_DOMAINS)
    if blocked and _host_matches_domain(hostname, blocked):
        raise WebEgressError(f"Domain '{hostname}' is blocked by web policy")

    allowed = _csv_domains(settings.WEB_ALLOWED_DOMAINS)
    if allowed and not _host_matches_domain(hostname, allowed):
        raise WebEgressError(f"Domain '{hostname}' is not in allowed web domains")

    if settings.WEB_BLOCK_PRIVATE_NETWORKS:
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise WebEgressError("Web URL targets a private or local network")
        try:
            ip_addr = ipaddress.ip_address(hostname)
        except ValueError:
            return cleaned
        if address_is_private(str(ip_addr)):
            raise WebEgressError("Web URL targets a private or local network")
    return cleaned


async def assert_web_url_allowed(url: str) -> str:
    """Validate URL policy and verify DNS resolution does not hit private networks."""
    cleaned = validate_web_url(url)
    if not settings.WEB_BLOCK_PRIVATE_NETWORKS:
        return cleaned

    parsed = urlsplit(cleaned)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
        return cleaned
    except ValueError:
        pass

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise WebEgressError(f"Web hostname '{hostname}' could not be resolved") from exc

    resolved = {str(item[4][0]) for item in addresses}
    if not resolved:
        raise WebEgressError(f"Web hostname '{hostname}' did not resolve to an address")
    if any(address_is_private(addr) for addr in resolved):
        raise WebEgressError(
            f"Web hostname '{hostname}' resolves to a private or local network"
        )
    return cleaned


class _HTMLTextExtractor(HTMLParser):
    """Extract clean title and body text from HTML while ignoring script/style tags."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}
    _BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "br",
    }

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
        elif lowered == "title" and self._skip_depth == 0:
            self._in_title = True
        elif lowered in self._BLOCK_TAGS and self._skip_depth == 0:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif lowered == "title":
            self._in_title = False
        elif lowered in self._BLOCK_TAGS and self._skip_depth == 0:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._text_parts.append(data)

    def result(self) -> tuple[str, str]:
        title = re.sub(r"\s+", " ", html.unescape("".join(self._title_parts))).strip()
        raw_text = html.unescape("".join(self._text_parts))
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw_text.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return title, cleaned


def extract_html_text(content: str) -> tuple[str, str]:
    parser = _HTMLTextExtractor()
    parser.feed(content)
    parser.close()
    return parser.result()


def _resolve_ddg_url(href: str) -> str:
    cleaned = html.unescape(href).strip()
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    parsed = urlsplit(cleaned)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        target = qs.get("uddg", [None])[0]
        if target:
            return unquote(target)
    return cleaned


class _DuckDuckGoHTMLParser(HTMLParser):
    """Parse DuckDuckGo HTML search result links and snippets."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._current_href = ""
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._in_link = True
            self._current_href = attr_map.get("href") or ""
            self._current_title = []
        elif tag in {"a", "div", "span"} and "result__snippet" in classes:
            self._in_snippet = True
            self._current_snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
            url = _resolve_ddg_url(self._current_href)
            title = re.sub(
                r"\s+", " ", html.unescape("".join(self._current_title))
            ).strip()
            if url.startswith(("http://", "https://")) and title:
                self.results.append({"url": url, "title": title, "snippet": ""})
        elif self._in_snippet and tag in {"a", "div", "span"}:
            self._in_snippet = False
            snippet = re.sub(
                r"\s+", " ", html.unescape("".join(self._current_snippet))
            ).strip()
            if self.results and snippet and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = snippet

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)


def parse_duckduckgo_html(markup: str, limit: int) -> list[dict[str, str]]:
    parser = _DuckDuckGoHTMLParser()
    parser.feed(markup)
    parser.close()
    return parser.results[:limit]


def extract_urls(query: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_PATTERN.findall(query):
        cleaned = match.rstrip(".,;:")
        if cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)
    return urls


def _chunk_id(url: str) -> str:
    return f"web:{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


class WebRetriever(Retriever):
    """Retrieve live web search results and validated HTTP(S) page content."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=settings.WEB_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=False,
            transport=self._transport,
        )

    async def _fetch_page(self, url: str) -> tuple[str, str, str]:
        """Fetch a single URL safely across redirects and return (url, title, text)."""
        current_url = await assert_web_url_allowed(url)
        async with self._client() as client:
            response: httpx.Response | None = None
            for _ in range(4):
                response = await client.get(current_url)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break
                    next_url = urljoin(current_url, location)
                    current_url = await assert_web_url_allowed(next_url)
                    continue
                break
            assert response is not None
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                kind in content_type
                for kind in ("text/", "application/json", "application/xhtml+xml")
            ):
                raise ValueError(f"Unsupported content type: {content_type}")

            raw = response.content[: settings.WEB_MAX_PAGE_BYTES]
            encoding = response.encoding or "utf-8"
            decoded = raw.decode(encoding, errors="replace")

        if "html" in content_type or "<html" in decoded[:500].lower():
            title, text = extract_html_text(decoded)
        else:
            title, text = "", re.sub(r"\n{3,}", "\n\n", decoded).strip()

        if not title:
            title = _domain(current_url) or current_url
        return current_url, title, text[: settings.WEB_MAX_CONTENT_CHARS]

    async def _search_duckduckgo(self, query: str, limit: int) -> list[dict[str, str]]:
        async with self._client() as client:
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            response.raise_for_status()
            return parse_duckduckgo_html(response.text, limit)

    async def _search_tavily(self, query: str, limit: int) -> list[dict[str, str]]:
        if not settings.WEB_SEARCH_API_KEY:
            raise RuntimeError("WEB_SEARCH_API_KEY is required for Tavily web search")
        async with self._client() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.WEB_SEARCH_API_KEY,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            payload = response.json()
        return [
            {
                "url": str(item.get("url", "")),
                "title": str(item.get("title", "")),
                "snippet": str(item.get("content", "")),
            }
            for item in payload.get("results", [])[:limit]
            if item.get("url")
        ]

    async def _search_searxng(self, query: str, limit: int) -> list[dict[str, str]]:
        base_url = settings.WEB_SEARXNG_URL.strip().rstrip("/")
        if not base_url:
            raise RuntimeError("WEB_SEARXNG_URL is required for SearXNG web search")
        async with self._client() as client:
            response = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
        return [
            {
                "url": str(item.get("url", "")),
                "title": str(item.get("title", "")),
                "snippet": str(item.get("content", "")),
            }
            for item in payload.get("results", [])[:limit]
            if item.get("url")
        ]

    async def _search_brave(self, query: str, limit: int) -> list[dict[str, str]]:
        if not settings.WEB_SEARCH_API_KEY:
            raise RuntimeError("WEB_SEARCH_API_KEY is required for Brave web search")
        async with self._client() as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit},
                headers={"X-Subscription-Token": settings.WEB_SEARCH_API_KEY},
            )
            response.raise_for_status()
            payload = response.json()
        items = payload.get("web", {}).get("results", [])
        return [
            {
                "url": str(item.get("url", "")),
                "title": str(item.get("title", "")),
                "snippet": str(item.get("description", "")),
            }
            for item in items[:limit]
            if item.get("url")
        ]

    async def _search(self, query: str, limit: int) -> list[dict[str, str]]:
        provider = settings.WEB_SEARCH_PROVIDER
        if provider == "duckduckgo":
            return await self._search_duckduckgo(query, limit)
        if provider == "tavily":
            return await self._search_tavily(query, limit)
        if provider == "searxng":
            return await self._search_searxng(query, limit)
        if provider == "brave":
            return await self._search_brave(query, limit)
        raise RuntimeError(f"Unsupported web search provider: {provider}")

    async def _enrich_search_result(
        self, item: dict[str, str], *, fetch_content: bool
    ) -> dict[str, str] | None:
        url = item["url"]
        try:
            validated_url = validate_web_url(url)
        except WebEgressError:
            return None

        title = item.get("title", "") or _domain(validated_url)
        snippet = item.get("snippet", "")
        text = snippet

        if fetch_content and settings.WEB_FETCH_PAGE_CONTENT:
            try:
                final_url, page_title, page_text = await self._fetch_page(validated_url)
                validated_url = final_url
                if page_title:
                    title = page_title
                if page_text:
                    text = page_text
            except Exception:  # noqa: BLE001 - fall back to search snippet
                pass

        if not text:
            return None
        return {
            "url": validated_url,
            "title": title,
            "snippet": snippet or text[:320],
            "text": text[: settings.WEB_MAX_CONTENT_CHARS],
        }

    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        if not settings.WEB_RETRIEVAL_ENABLED:
            raise RuntimeError("Web retrieval is disabled by configuration")

        started = time.monotonic()
        limit = min(max(top_k, 1), settings.WEB_MAX_RESULTS)
        explicit_urls = extract_urls(query)
        extra_urls = (filters or {}).get("urls") or []
        for url in extra_urls:
            if isinstance(url, str) and url not in explicit_urls:
                explicit_urls.append(url)

        entries: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        if explicit_urls:
            fetched = await asyncio.gather(
                *(self._fetch_page(url) for url in explicit_urls[:limit]),
                return_exceptions=True,
            )
            for item in fetched:
                if isinstance(item, BaseException):
                    if len(explicit_urls) == 1 and not URL_PATTERN.sub("", query).strip():
                        raise RuntimeError(f"Could not fetch URL: {item}") from item
                    continue
                final_url, title, text = item
                if text and final_url not in seen_urls:
                    seen_urls.add(final_url)
                    entries.append(
                        {
                            "url": final_url,
                            "title": title,
                            "snippet": text[:320],
                            "text": text,
                        }
                    )

        search_query = URL_PATTERN.sub("", query).strip()
        if not explicit_urls and search_query:
            raw_results = await self._search(search_query, limit)
            enriched = await asyncio.gather(
                *(
                    self._enrich_search_result(item, fetch_content=idx < 3)
                    for idx, item in enumerate(raw_results)
                ),
                return_exceptions=False,
            )
            for enriched_item in enriched:
                if enriched_item is None or enriched_item["url"] in seen_urls:
                    continue
                seen_urls.add(enriched_item["url"])
                entries.append(enriched_item)
                if len(entries) >= limit:
                    break

        chunks = [
            RetrievedChunk(
                id=_chunk_id(entry["url"]),
                content=(
                    f"Title: {entry['title']}\n"
                    f"URL: {entry['url']}\n\n"
                    f"{entry['text']}"
                ),
                source="web",
                score=round(max(0.1, 1.0 - index * 0.08), 4),
                metadata={
                    "url": entry["url"],
                    "title": entry["title"],
                    "label": entry["title"],
                    "domain": _domain(entry["url"]),
                    "snippet": entry["snippet"],
                    "provider": (
                        "direct_url" if explicit_urls else settings.WEB_SEARCH_PROVIDER
                    ),
                },
            )
            for index, entry in enumerate(entries[:limit])
        ]
        return RetrievalResult(
            source="web",
            query=query,
            chunks=chunks,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
