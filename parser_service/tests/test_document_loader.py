import json
import unittest

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from parser_service.ai_extract import extract_document
from parser_service.document_loader import DocumentLoadError, load_document
from parser_service.policy import SourcePolicy
from parser_service.safe_fetch import FetchError, FetchResponse


PAGE_URL = "https://www.cbr.ru/press/event/?id=fixture"
ROBOTS_URL = "https://www.cbr.ru/robots.txt"


def policy(**changes):
    values = dict(version="test-v1", allow_fetch=True, allow_persist=True,
                  max_items=1, max_response_bytes=10_000, max_total_bytes=20_000,
                  request_timeout_seconds=5, job_timeout_seconds=20,
                  min_interval_seconds=1, user_agent="KIBTest/1.0")
    values.update(changes)
    return SourcePolicy(**values)


def response(body, content_type, fetched_at="2026-10-22T12:00:00Z"):
    data = body if isinstance(body, bytes) else body.encode("utf-8")
    return FetchResponse(body=data, content_type=content_type, fetched_at=fetched_at)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch(self, url, *, kind, timeout_seconds, max_bytes):
        self.calls.append((url, kind, timeout_seconds, max_bytes))
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        if value.bytes_read > max_bytes:
            raise FetchError("SIZE_LIMIT", bytes_read=max_bytes)
        return value


class DocumentLoaderTests(unittest.TestCase):
    def load(self, fetcher, chosen_policy=None, **changes):
        clock = FakeClock()
        options = dict(url=PAGE_URL, policy=chosen_policy or policy(),
                       document_revision="revision-1", max_output_chars=10_000,
                       fetcher=fetcher, clock=clock.monotonic, sleep=clock.sleep)
        options.update(changes)
        return load_document(**options), clock

    def test_loads_after_robots_and_honors_crawl_delay(self):
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nCrawl-delay: 3\nAllow: /press/", "text/plain"),
            PAGE_URL: response("<article><p>Проверенный текст.</p></article>", "text/html"),
        })

        loaded, clock = self.load(fetcher)

        self.assertEqual([call[1] for call in fetcher.calls], ["robots", "page"])
        self.assertEqual(clock.sleeps, [1, 3])
        self.assertEqual(loaded.document.text, "Проверенный текст.")
        self.assertEqual((loaded.url, loaded.policy_version), (PAGE_URL, "test-v1"))
        self.assertEqual(loaded.fetched_at, "2026-10-22T12:00:00Z")

        rate_fetcher = FakeFetcher({
            ROBOTS_URL: response(
                "User-agent: *\nRequest-rate: 2/10\nAllow: /press/", "text/plain"
            ),
            PAGE_URL: response("<article>Текст.</article>", "text/html"),
        })
        _loaded, rate_clock = self.load(rate_fetcher)
        self.assertEqual(rate_clock.sleeps, [1, 5])

    def test_policy_url_and_robots_fail_before_page_fetch(self):
        cases = [
            (policy(allow_fetch=False), PAGE_URL, {}, "SOURCE_POLICY_DENIED"),
            (policy(allow_persist=False), PAGE_URL, {}, "SOURCE_POLICY_DENIED"),
            (policy(), "https://example.test/news", {}, "URL_BLOCKED"),
            (policy(), PAGE_URL, {ROBOTS_URL: FetchError("ACCESS_DENIED")}, "ACCESS_DENIED"),
            (policy(), PAGE_URL, {ROBOTS_URL: FetchError("NOT_FOUND")}, "NOT_FOUND"),
            (policy(), PAGE_URL, {ROBOTS_URL: response(
                "User-agent: *\nDisallow: /press/", "text/plain")}, "ACCESS_DENIED"),
        ]
        for chosen, url, responses, code in cases:
            fetcher = FakeFetcher(responses)
            with self.subTest(code=code), self.assertRaises(DocumentLoadError) as raised:
                self.load(fetcher, chosen_policy=chosen, url=url,
                          document_revision="r", max_output_chars=1000)
            self.assertEqual(raised.exception.code, code)
            self.assertFalse(any(call[1] == "page" for call in fetcher.calls))

    def test_rejects_malformed_robots_mime_before_page_fetch(self):
        fetcher = FakeFetcher({
            ROBOTS_URL: response(
                "User-agent: *\nAllow: /press/", "not-a-media-type"
            ),
        })

        with self.assertRaises(DocumentLoadError) as raised:
            self.load(fetcher)

        self.assertEqual(raised.exception.code, "MIME_UNSUPPORTED")
        self.assertEqual([call[1] for call in fetcher.calls], ["robots"])

    def test_enforces_transport_content_and_encoding_boundaries(self):
        robots = response("User-agent: *\nAllow: /", "text/plain")
        cases = [
            (FetchError("TIMEOUT"), "TIMEOUT"),
            (response("text", "application/json"), "HTML_INVALID"),
            (response("text", "text/html; charset=windows-1251"), "ENCODING_UNSUPPORTED"),
            (response(b"\xff", "text/html"), "ENCODING_UNSUPPORTED"),
            (response("<nav>nothing</nav>", "text/html"), "HTML_INVALID"),
        ]
        for page, code in cases:
            fetcher = FakeFetcher({ROBOTS_URL: robots, PAGE_URL: page})
            with self.subTest(code=code), self.assertRaises(DocumentLoadError) as raised:
                self.load(fetcher)
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn("nothing", str(raised.exception))

    def test_accounts_for_combined_bytes_and_deadline(self):
        robots = response("User-agent: *\nAllow: /", "text/plain")
        page = response("<article>1234567890</article>", "text/html")
        fetcher = FakeFetcher({ROBOTS_URL: robots, PAGE_URL: page})
        with self.assertRaises(DocumentLoadError) as raised:
            self.load(fetcher, policy(max_total_bytes=robots.bytes_read + 3))
        self.assertEqual(raised.exception.code, "SIZE_LIMIT")

        slow = FakeFetcher({ROBOTS_URL: robots, PAGE_URL: page})
        with self.assertRaises(DocumentLoadError) as raised:
            self.load(slow, policy(job_timeout_seconds=1, min_interval_seconds=1))
        self.assertEqual(raised.exception.code, "TIMEOUT")


class LoaderExtractionFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_fetch_to_langchain_result_with_verified_evidence(self):
        quote = "Ставка составит 16 процентов."
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
            PAGE_URL: response(f"<article><p>{quote}</p></article>", "text/html"),
        })
        loaded = load_document(
            PAGE_URL, policy(), document_revision="revision-e2e",
            max_output_chars=1000, fetcher=fetcher,
            clock=FakeClock().monotonic, sleep=lambda _seconds: None,
        )
        source = loaded.document
        output = json.dumps({
            "title": None,
            "publication": {"at": None, "date": None, "precision": "unknown",
                            "evidence_ids": []},
            "claims": [{"claim_id": "c1", "text": quote, "modality": "announcement",
                        "event_date": None, "effective_date": None,
                        "evidence_ids": ["e1"]}],
            "evidence": [{"evidence_id": "e1", "document_revision": source.document_revision,
                          "text_hash": source.text_hash,
                          "locator": {"block_id": source.blocks[0].block_id,
                                      "start": source.blocks[0].start,
                                      "end": source.blocks[0].end},
                          "quote": quote}],
            "incomplete_fields": ["title", "publication"],
        }, ensure_ascii=False)
        model = FakeMessagesListChatModel(responses=[AIMessage(content=output)])

        extracted = await extract_document(
            source, model, max_input_chars=100_000,
            max_output_chars=10_000, timeout_seconds=1,
        )

        self.assertEqual(extracted.evidence[0].quote, quote)
        self.assertEqual(source.text[source.blocks[0].start:source.blocks[0].end], quote)


if __name__ == "__main__":
    unittest.main()
