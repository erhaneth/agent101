# team/sourcefetcher.py
# 📄 THE SOURCE FETCHER
# Responsibility: Fetch candidate source URLs and parse usable text before evidence judging.
#
# Search APIs are useful, but snippets can be shallow or misleading. This node
# tries to read the actual source page/PDF, detect bad fetches, and enrich
# findings with fetched text and metadata for downstream verification.

from __future__ import annotations

import io
import os
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests
from langsmith import traceable

from team.cache import get_cached_json, set_cached_json, ttl_seconds
from team.state import ResearchAgentState


DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_MAX_FETCH_BYTES = 2_000_000
DEFAULT_MAX_PARSED_CHARS = 12_000
MIN_USEFUL_TEXT_CHARS = 400

USER_AGENT = (
    "FactCrafterResearchAgent/1.0 "
    "(source verification; contact: local-development)"
)

BAD_PAGE_PATTERNS = (
    "enable javascript",
    "access denied",
    "checking your browser",
    "sign in",
    "log in",
    "subscribe to continue",
    "you need to enable cookies",
)


class ReadableHTMLParser(HTMLParser):
    """Small dependency-free parser for visible text and title extraction."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}
    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if self.skip_depth:
            return
        text = unescape(data).strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        self.parts.append(text)
        self.parts.append(" ")

    def text(self) -> str:
        return clean_text("".join(self.parts))

    def title(self) -> str:
        return clean_text(" ".join(self.title_parts))


def clean_text(text: str) -> str:
    """Normalize whitespace and remove low-value repeated space."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    text = re.sub(r"\n ", "\n", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def is_probably_bad_page(text: str) -> bool:
    """Detect login, bot-wall, or script-only pages."""
    lower = (text or "").lower()
    if len(lower) < MIN_USEFUL_TEXT_CHARS:
        return True
    return any(pattern in lower for pattern in BAD_PAGE_PATTERNS)


def content_type_is_pdf(content_type: str, url: str) -> bool:
    parsed = urlparse(url)
    return "application/pdf" in (content_type or "").lower() or parsed.path.lower().endswith(".pdf")


def decode_html(data: bytes, response: requests.Response) -> str:
    encoding = response.encoding or response.apparent_encoding or "utf-8"
    return data.decode(encoding, errors="replace")


def parse_html(data: bytes, response: requests.Response) -> tuple[str, dict]:
    parser = ReadableHTMLParser()
    parser.feed(decode_html(data, response))
    text = parser.text()
    metadata = {"parsed_title": parser.title()}
    return text, metadata


def parse_pdf(data: bytes) -> tuple[str, dict]:
    try:
        from pypdf import PdfReader
    except Exception as error:
        return "", {"pdf_parse_error": f"pypdf unavailable: {error}"}

    try:
        reader = PdfReader(io.BytesIO(data))
        page_text = []
        for page in reader.pages[:12]:
            page_text.append(page.extract_text() or "")
        return clean_text("\n\n".join(page_text)), {"pdf_page_count": len(reader.pages)}
    except Exception as error:
        return "", {"pdf_parse_error": str(error)}


def read_limited_response(response: requests.Response, max_bytes: int) -> bytes:
    chunks = []
    total = 0

    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            remaining = max_bytes - (total - len(chunk))
            if remaining > 0:
                chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)

    return b"".join(chunks)


def fetch_and_parse_source(
    url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_fetch_bytes: int = DEFAULT_MAX_FETCH_BYTES,
    max_parsed_chars: int = DEFAULT_MAX_PARSED_CHARS,
) -> dict:
    """
    Fetch one URL and return parsed source text plus metadata.

    Failures are returned as structured metadata instead of raising so the graph
    can continue and fall back to Tavily text for that source.
    """
    cache_payload = {
        "url": url,
        "max_fetch_bytes": max_fetch_bytes,
        "max_parsed_chars": max_parsed_chars,
        "parser_version": "sourcefetcher-v1",
    }
    source_ttl = ttl_seconds("FACTCRAFTER_SOURCE_CACHE_TTL_SECONDS", 7 * 24 * 60 * 60)
    cached = get_cached_json("source_fetch", cache_payload, ttl=source_ttl)
    if cached is not None:
        cached = dict(cached)
        cached["cache_status"] = "hit"
        return cached

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5"}

    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds, stream=True)
        status_code = response.status_code
        content_type = response.headers.get("content-type", "")

        if status_code >= 400:
            result = {
                "fetch_status": "failed",
                "fetch_error": f"HTTP {status_code}",
                "http_status": status_code,
                "content_type": content_type,
                "final_url": response.url,
                "fetched_text": "",
                "source_metadata": {},
                "cache_status": "miss",
            }
            set_cached_json("source_fetch", cache_payload, result)
            return result

        data = read_limited_response(response, max_fetch_bytes)

        if content_type_is_pdf(content_type, response.url):
            parsed_text, metadata = parse_pdf(data)
            parser = "pdf"
        else:
            parsed_text, metadata = parse_html(data, response)
            parser = "html"

        parsed_text = parsed_text[:max_parsed_chars]
        status = "ok" if parsed_text and not is_probably_bad_page(parsed_text) else "weak"
        result = {
            "fetch_status": status,
            "fetch_error": "" if status == "ok" else "Fetched text was missing, thin, or looked like a blocked/login page.",
            "http_status": status_code,
            "content_type": content_type,
            "final_url": response.url,
            "fetched_text": parsed_text,
            "source_metadata": {
                **metadata,
                "parser": parser,
                "fetched_bytes": len(data),
            },
            "cache_status": "miss",
        }
        set_cached_json("source_fetch", cache_payload, result)
        return result
    except Exception as error:
        result = {
            "fetch_status": "failed",
            "fetch_error": str(error),
            "http_status": 0,
            "content_type": "",
            "final_url": url,
            "fetched_text": "",
            "source_metadata": {},
            "cache_status": "miss",
        }
        set_cached_json("source_fetch", cache_payload, result)
        return result


def should_fetch_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return bool(parsed.netloc)


@traceable(
    name="source_fetcher_agent",
    tags=["source-fetch", "parsing", "tool-use"],
    metadata={"agent": "source_fetcher"},
)
def source_fetcher_agent(state: ResearchAgentState) -> dict:
    """
    Enrich search findings with parsed source text.

    If fetching fails, the finding stays in the pipeline with its existing
    Tavily evidence text. This keeps the agent resilient while improving source
    quality whenever pages are fetchable.
    """
    findings = list(state.get("findings", []))
    max_sources = int(os.getenv("SOURCE_FETCH_MAX_SOURCES", "18"))

    print(f"\n📄 SOURCE FETCHER: Fetching and parsing up to {min(len(findings), max_sources)} sources...")

    enriched = []
    fetched_count = 0
    weak_count = 0
    failed_count = 0

    for index, finding in enumerate(findings, start=1):
        item = dict(finding)
        url = item.get("url", "")

        if index > max_sources or not should_fetch_url(url):
            item.setdefault("fetch_status", "skipped")
            item.setdefault("fetch_error", "source fetch limit reached or invalid URL")
            enriched.append(item)
            continue

        result = fetch_and_parse_source(url)
        fetched_text = result.get("fetched_text", "")
        previous_evidence = item.get("evidence_text") or item.get("snippet", "")

        item.update(result)
        if fetched_text and result.get("fetch_status") == "ok":
            item["evidence_text"] = fetched_text
            fetched_count += 1
        else:
            item["evidence_text"] = previous_evidence
            if result.get("fetch_status") == "weak":
                weak_count += 1
            else:
                failed_count += 1

        enriched.append(item)
        cache_note = " cache" if result.get("cache_status") == "hit" else ""
        print(f"   [{index}] {result.get('fetch_status', 'unknown').upper()}{cache_note} {url[:72]}")

    print(f"   ✅ Parsed: {fetched_count}")
    print(f"   ⚠️ Weak fallback: {weak_count}")
    print(f"   ❌ Failed fallback: {failed_count}")

    return {"findings": enriched}
