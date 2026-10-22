"""Ограниченный RSS → HTML проход для явно разрешённого прототипа ЦБ."""

from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import time
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from .cbr_html import extract_article
from .executor import ProcessingError
from .safe_fetch import FetchError, SafeFetcher

ROBOTS_URL = "https://www.cbr.ru/robots.txt"
FEED_URL = "https://www.cbr.ru/rss/RssPress"


class _Summary(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _summary(text):
    parser = _Summary()
    parser.feed(text or "")
    return " ".join(" ".join(parser.parts).split()) or None


def _publication(text):
    try:
        value = parsedate_to_datetime(text)
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.isoformat()
    except (ValueError, TypeError, IndexError, OverflowError):
        pass
    return None


def _safe_error(code, message, retryable=False):
    return {"code": code, "message": message, "retryable": retryable}


class CbrHandler:
    def __init__(self, policy, fetcher=None, *, clock=time.monotonic, sleep=time.sleep):
        self.policy = policy
        self.fetcher = fetcher if fetcher is not None else SafeFetcher(policy)
        self.clock, self.sleep = clock, sleep

    def __call__(self, request):
        p = self.policy
        if (not p.allow_fetch or not p.allow_persist
                or request.get("policy_version") != p.version
                or request.get("source_id") != "cbr_press"
                or request.get("mode") != "discover"
                or request.get("requested_level") != "content"):
            raise ProcessingError("SOURCE_POLICY_DENIED")
        deadline = self.clock() + p.job_timeout_seconds
        remaining_bytes = p.max_total_bytes
        interval = p.min_interval_seconds

        def budget():
            return self.clock() + interval < deadline and remaining_bytes > 0

        def fetch(url, kind):
            nonlocal remaining_bytes
            if not budget():
                raise FetchError("TIMEOUT")
            self.sleep(interval)
            timeout = min(p.request_timeout_seconds, deadline - self.clock())
            cap = min(p.max_response_bytes, remaining_bytes)
            if timeout <= 0:
                raise FetchError("TIMEOUT")
            try:
                response = self.fetcher.fetch(url, kind=kind,
                                              timeout_seconds=timeout, max_bytes=cap)
            except FetchError as exc:
                remaining_bytes -= min(cap, exc.bytes_read)
                raise
            remaining_bytes -= len(response.body)
            return response

        try:
            robots_response = fetch(ROBOTS_URL, "robots")
            robots = RobotFileParser(ROBOTS_URL)
            robots.parse(robots_response.body.decode("utf-8-sig", errors="strict").splitlines())
            delay = robots.crawl_delay(p.user_agent)
            rate = robots.request_rate(p.user_agent)
            interval = max(interval, delay or 0,
                           rate.seconds / rate.requests if rate else 0)
            if not robots.can_fetch(p.user_agent, FEED_URL):
                raise FetchError("ACCESS_DENIED")
            feed = fetch(FEED_URL, "feed")
        except (FetchError, UnicodeError):
            raise ProcessingError("FEED_UNAVAILABLE") from None
        try:
            xml = feed.body.decode("utf-8-sig", errors="strict")
            if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
                raise ValueError("XML declarations are not allowed")
            root = ET.fromstring(xml)
            channel = root.find("channel")
            if root.tag != "rss" or channel is None:
                raise ValueError("RSS channel required")
            candidates = channel.findall("item")
        except (ET.ParseError, UnicodeError, ValueError):
            raise ProcessingError("FEED_INVALID") from None
        incomplete = ["items"] if len(candidates) > p.max_items else []
        items = []
        for index, candidate in enumerate(candidates[:p.max_items]):
            if not budget():
                if "items" not in incomplete:
                    incomplete.append("items")
                break
            url = (candidate.findtext("link") or "").strip()
            try:
                p.validate_url(url, "page")
                if not robots.can_fetch(p.user_agent, url):
                    raise ValueError("Robots denied")
            except ValueError:
                incomplete.append(f"items[{index}].url_blocked" if url else f"items[{index}].url")
                continue
            publication = _publication(candidate.findtext("pubDate"))
            item = {
                "external_id": candidate.findtext("guid"), "url": url,
                "title": (candidate.findtext("title") or "").strip() or None,
                "description": _summary(candidate.findtext("description")),
                "published_at": publication, "published_date": None,
                "date_precision": "second" if publication else "unknown",
                "published_at_source": "rss.pubDate" if candidate.findtext("pubDate") else None,
                "content_text": None, "content_status": "unavailable",
                "extraction_method": "cbr.landing-text.v1", "fetched_at": None,
                "provenance": {"source_id": "cbr_press", "discovery_method": "rss",
                               "discovery_url": FEED_URL, "policy_version": p.version},
                "attachments": [], "incomplete_fields": [], "error": None,
            }
            try:
                page = fetch(url, "page")
                item["fetched_at"] = page.fetched_at
                article = extract_article(page.body.decode("utf-8-sig", errors="strict"))
                item["title"] = article["title"] or item["title"]
                item["content_text"] = article["content_text"]
                if not publication and article["published_date"]:
                    item.update(published_date=article["published_date"], date_precision="day",
                                published_at_source="html.news-info-line_date")
                if article["complete"]:
                    item["content_status"] = "full"
                else:
                    item["content_status"] = "partial" if article["content_text"] else "unavailable"
                    item["error"] = _safe_error("EXTRACTION_INCOMPLETE", "Article structure is incomplete.")
                for href in article["attachments"]:
                    attachment = urljoin(url, href)
                    try:
                        p.validate_url(attachment, "attachment")
                    except ValueError:
                        continue
                    if robots.can_fetch(p.user_agent, attachment):
                        item["attachments"].append({"url": attachment, "media_type": "application/pdf"})
            except FetchError as exc:
                item["error"] = _safe_error(exc.code, exc.message, exc.retryable)
            except (UnicodeError, ValueError):
                item["error"] = _safe_error("EXTRACTION_FAILED", "Article could not be decoded or parsed.")
            if item["fetched_at"] is None:
                item["incomplete_fields"].append("fetched_at")
            items.append(item)
        if self.clock() >= deadline and "items" not in incomplete:
            incomplete.append("items")
        partial = incomplete or any(
            item["content_status"] != "full" or item["date_precision"] == "unknown"
            or item["incomplete_fields"] for item in items)
        return {"job_id": request["job_id"], "result_status": "partial" if partial else "complete",
                "items": items, "incomplete_fields": incomplete}
