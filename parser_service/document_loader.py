"""Load one CBR HTML page through the existing bounded network boundary."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from email.message import Message
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .extraction_models import SourceDocument
from .html_document import HtmlCleanError, clean_html
from .policy import SourcePolicy
from .safe_fetch import FetchError, SafeFetcher


class DocumentLoadError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("Invalid document load error code")
        self.code = code
        super().__init__("Document loading failed.")


@dataclass(frozen=True)
class LoadedDocument:
    document: SourceDocument
    url: str
    fetched_at: str
    policy_version: str
    incomplete_fields: tuple[str, ...]


def _content_type(value: str) -> tuple[str, list[str]]:
    if not isinstance(value, str) or not value.strip():
        return "", []
    message = Message()
    message["content-type"] = value
    params = message.get_params(header="content-type", failobj=[]) or []
    charsets = [item for name, item in params[1:] if name.lower() == "charset"]
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type, charsets


def _utf8_content(value: str, expected: str) -> None:
    media_type, charsets = _content_type(value)
    if media_type != expected:
        raise DocumentLoadError("HTML_INVALID" if expected == "text/html" else "MIME_UNSUPPORTED")
    if len(charsets) > 1:
        raise DocumentLoadError("ENCODING_UNSUPPORTED")
    if charsets:
        try:
            encoding = codecs.lookup(charsets[0]).name
        except (LookupError, TypeError):
            raise DocumentLoadError("ENCODING_UNSUPPORTED") from None
        if encoding not in {"utf-8", "utf-8-sig"}:
            raise DocumentLoadError("ENCODING_UNSUPPORTED")


def load_document(
    url: str,
    policy: SourcePolicy,
    *,
    document_revision: str,
    max_output_chars: int,
    fetcher=None,
    clock=time.monotonic,
    sleep=time.sleep,
) -> LoadedDocument:
    """Fetch, clean and return one policy-approved static HTML document."""
    if not isinstance(document_revision, str) or not document_revision.strip():
        raise ValueError("document_revision must not be blank")
    if type(max_output_chars) is not int or max_output_chars <= 0:
        raise ValueError("max_output_chars must be a positive integer")
    if not policy.allow_fetch or not policy.allow_persist:
        raise DocumentLoadError("SOURCE_POLICY_DENIED") from None
    try:
        normalized_url = policy.validate_url(url, "page")
        parts = urlsplit(normalized_url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        policy.validate_url(robots_url, "robots")
    except ValueError:
        raise DocumentLoadError("URL_BLOCKED") from None

    active_fetcher = fetcher if fetcher is not None else SafeFetcher(policy)
    deadline = clock() + policy.job_timeout_seconds
    remaining_bytes = policy.max_total_bytes
    interval = float(policy.min_interval_seconds)

    def fetch(target: str, kind: str):
        nonlocal remaining_bytes
        remaining_time = deadline - clock()
        if remaining_bytes <= 0:
            raise DocumentLoadError("SIZE_LIMIT")
        if interval >= remaining_time:
            raise DocumentLoadError("TIMEOUT")
        sleep(interval)
        remaining_time = deadline - clock()
        if remaining_time <= 0:
            raise DocumentLoadError("TIMEOUT")
        cap = min(policy.max_response_bytes, remaining_bytes)
        timeout = min(policy.request_timeout_seconds, remaining_time)
        try:
            response = active_fetcher.fetch(
                target, kind=kind, timeout_seconds=timeout, max_bytes=cap
            )
        except FetchError as exc:
            raise DocumentLoadError(exc.code) from None
        except Exception:
            raise DocumentLoadError("NETWORK_ERROR") from None
        if clock() >= deadline:
            raise DocumentLoadError("TIMEOUT")
        if response.bytes_read > cap:
            raise DocumentLoadError("SIZE_LIMIT")
        remaining_bytes -= response.bytes_read
        return response

    robots_response = fetch(robots_url, "robots")
    _utf8_content(robots_response.content_type, "text/plain")
    try:
        robots_text = robots_response.body.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise DocumentLoadError("ENCODING_UNSUPPORTED") from None
    robots = RobotFileParser(robots_url)
    robots.parse(robots_text.splitlines())
    if not robots.can_fetch(policy.user_agent, normalized_url):
        raise DocumentLoadError("ACCESS_DENIED") from None
    delay = robots.crawl_delay(policy.user_agent)
    rate = robots.request_rate(policy.user_agent)
    rate_interval = rate.seconds / rate.requests if rate and rate.requests else 0
    interval = max(interval, delay or 0, rate_interval)

    page_response = fetch(normalized_url, "page")
    _utf8_content(page_response.content_type, "text/html")
    try:
        html = page_response.body.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise DocumentLoadError("ENCODING_UNSUPPORTED") from None
    try:
        cleaned = clean_html(
            html,
            document_revision=document_revision,
            max_input_chars=policy.max_response_bytes,
            max_output_chars=max_output_chars,
        )
    except HtmlCleanError as exc:
        code = "SIZE_LIMIT" if exc.code == "OUTPUT_LIMIT" else "HTML_INVALID"
        raise DocumentLoadError(code) from None
    if clock() >= deadline:
        raise DocumentLoadError("TIMEOUT") from None
    return LoadedDocument(
        document=cleaned.document,
        url=normalized_url,
        fetched_at=page_response.fetched_at,
        policy_version=policy.version,
        incomplete_fields=cleaned.incomplete_fields,
    )
