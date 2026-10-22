import unittest

from parser_service.cbr import CbrHandler
from parser_service.executor import ProcessingError
from parser_service.safe_fetch import FetchError, FetchResponse
from parser_service.tests.test_safe_fetch import source_policy

ROBOTS_URL = "https://www.cbr.ru/robots.txt"
FEED_URL = "https://www.cbr.ru/rss/RssPress"


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeFetcher:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def fetch(self, url, *, kind, timeout_seconds, max_bytes):
        self.calls.append({"url": url, "kind": kind,
                           "timeout_seconds": timeout_seconds, "max_bytes": max_bytes})
        response = self.responses[url]
        if isinstance(response, BaseException):
            raise response
        return response


def response(body, content_type, fetched_at="2026-10-21T12:00:00Z"):
    return FetchResponse(body=body.encode(), content_type=content_type, fetched_at=fetched_at)


def rss_item(index, link=None, with_date=True):
    url = link or f"https://www.cbr.ru/press/PR/?file=fixture-{index}.htm"
    published = (
        "<pubDate>Wed, 21 Oct 2026 12:00:00 +0300</pubDate>" if with_date else ""
    )
    return f"""<item><title>Материал {index}</title><link>{url}</link>
    <description>Краткое описание {index}</description>
    {published}</item>"""


def rss(*items):
    return "<?xml version='1.0' encoding='UTF-8'?><rss><channel>" + "".join(items) + "</channel></rss>"


def article_html(index):
    return f"""<html><body><h1>Материал {index}</h1>
    <div class="news-info-line_date">21 октября 2026 года</div>
    <div class="landing-text"><p>Полный искусственный текст {index}.</p>
    <a href="/files/attachment-{index}.pdf">Приложение</a></div></body></html>"""


def request(job_id="job-cbr"):
    return {"job_id": job_id, "mode": "discover", "source_id": "cbr_press",
            "requested_level": "content", "policy_version": "cbr-v1"}


class CbrHandlerTests(unittest.TestCase):
    def test_policy_denial_happens_before_fetch(self):
        for policy in (source_policy(allow_fetch=False), source_policy(allow_persist=False)):
            fetcher = FakeFetcher({})
            with self.assertRaises(ProcessingError) as raised:
                CbrHandler(policy, fetcher=fetcher)(request())
            self.assertEqual(raised.exception.error["code"], "SOURCE_POLICY_DENIED")
            self.assertEqual(fetcher.calls, [])
        fetcher = FakeFetcher({})
        with self.assertRaises(ProcessingError):
            CbrHandler(source_policy(), fetcher=fetcher)(
                {**request(), "policy_version": "other-v1"})
        self.assertEqual(fetcher.calls, [])

    def test_limits_articles_and_budgets_every_fetch(self):
        responses = {ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
                     FEED_URL: response(rss(*(rss_item(i) for i in range(1, 5))),
                                        "application/rss+xml")}
        for index in range(1, 4):
            responses[f"https://www.cbr.ru/press/PR/?file=fixture-{index}.htm"] = response(
                article_html(index), "text/html")
        clock, fetcher = FakeClock(), FakeFetcher(responses)

        result = CbrHandler(source_policy(), fetcher=fetcher,
                            clock=clock.monotonic, sleep=clock.sleep)(request())

        self.assertEqual(result["result_status"], "partial")
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("items", result["incomplete_fields"])
        self.assertEqual([call["kind"] for call in fetcher.calls],
                         ["robots", "feed", "page", "page", "page"])
        self.assertEqual(clock.sleeps, [1, 1, 1, 1, 1])
        self.assertTrue(all(call["timeout_seconds"] <= 10 for call in fetcher.calls))
        self.assertTrue(all(call["max_bytes"] <= 1024 * 1024 for call in fetcher.calls))
        item = result["items"][0]
        self.assertEqual(item["published_at"], "2026-10-21T12:00:00+03:00")
        self.assertEqual(item["fetched_at"], "2026-10-21T12:00:00Z")
        self.assertEqual(item["attachments"][0]["url"],
                         "https://www.cbr.ru/files/attachment-1.pdf")

    def test_blocked_candidate_is_not_fetched_and_is_diagnosed(self):
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
            FEED_URL: response(rss(rss_item(1, "https://example.com/not-cbr")),
                               "application/rss+xml"),
        })
        clock = FakeClock()
        result = CbrHandler(source_policy(), fetcher=fetcher,
                            clock=clock.monotonic, sleep=clock.sleep)(request())
        self.assertEqual([call["url"] for call in fetcher.calls], [ROBOTS_URL, FEED_URL])
        self.assertEqual(result["items"], [])
        self.assertIn("items[0].url_blocked", result["incomplete_fields"])

    def test_article_failure_keeps_other_item_and_safe_error(self):
        first = "https://www.cbr.ru/press/PR/?file=fixture-1.htm"
        second = "https://www.cbr.ru/press/PR/?file=fixture-2.htm"
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
            FEED_URL: response(rss(rss_item(1), rss_item(2)), "application/rss+xml"),
            first: FetchError("TIMEOUT", bytes_read=1024),
            second: response(article_html(2), "text/html"),
        })
        clock = FakeClock()
        result = CbrHandler(source_policy(), fetcher=fetcher,
                            clock=clock.monotonic, sleep=clock.sleep)(request())
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["result_status"], "partial")
        self.assertEqual(result["items"][0]["content_status"], "unavailable")
        self.assertEqual(result["items"][0]["error"]["code"], "TIMEOUT")
        self.assertEqual(result["items"][1]["content_status"], "full")

    def test_robots_denial_and_bad_feed_map_to_processing_errors(self):
        cases = [
            (response("User-agent: *\nDisallow: /rss/", "text/plain"),
             response(rss(rss_item(1)), "application/rss+xml"), "FEED_UNAVAILABLE"),
            (response("User-agent: *\nAllow: /", "text/plain"),
             response("<rss><broken>", "application/rss+xml"), "FEED_INVALID"),
        ]
        for robots_response, feed_response, code in cases:
            with self.subTest(code=code):
                fetcher = FakeFetcher({ROBOTS_URL: robots_response, FEED_URL: feed_response})
                clock = FakeClock()
                with self.assertRaises(ProcessingError) as raised:
                    CbrHandler(source_policy(), fetcher=fetcher,
                               clock=clock.monotonic, sleep=clock.sleep)(request())
                self.assertEqual(raised.exception.error["code"], code)

    def test_dtd_or_entity_feed_is_rejected(self):
        malicious = """<?xml version='1.0' encoding='UTF-8'?>
        <!DOCTYPE rss [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>
        <rss><channel><item><title>&xxe;</title></item></channel></rss>"""
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
            FEED_URL: response(malicious, "application/rss+xml"),
        })
        clock = FakeClock()
        with self.assertRaises(ProcessingError) as raised:
            CbrHandler(source_policy(), fetcher=fetcher,
                       clock=clock.monotonic, sleep=clock.sleep)(request())
        self.assertEqual(raised.exception.error["code"], "FEED_INVALID")

    def test_missing_rss_date_uses_html_day_or_remains_unknown(self):
        first = "https://www.cbr.ru/press/PR/?file=fixture-1.htm"
        second = "https://www.cbr.ru/press/PR/?file=fixture-2.htm"
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
            FEED_URL: response(
                rss(rss_item(1, with_date=False), rss_item(2, with_date=False)),
                "application/rss+xml",
            ),
            first: response(article_html(1), "text/html"),
            second: response(
                "<html><body><h1>Материал 2</h1>"
                "<div class='landing-text'>Текст без даты.</div></body></html>",
                "text/html",
            ),
        })
        clock = FakeClock()
        result = CbrHandler(source_policy(), fetcher=fetcher,
                            clock=clock.monotonic, sleep=clock.sleep)(request())
        dated, unknown = result["items"]
        self.assertEqual((dated["published_date"], dated["date_precision"]),
                         ("2026-10-21", "day"))
        self.assertIsNone(dated["published_at"])
        self.assertEqual(unknown["date_precision"], "unknown")
        self.assertIsNone(unknown["published_at"])
        self.assertIsNone(unknown["published_date"])
        self.assertEqual(result["result_status"], "partial")

    def test_job_deadline_before_feed_fails_and_after_feed_returns_partial(self):
        before_fetcher = FakeFetcher({})
        before_clock = FakeClock()
        with self.assertRaises(ProcessingError) as raised:
            CbrHandler(source_policy(job_timeout_seconds=1), fetcher=before_fetcher,
                       clock=before_clock.monotonic, sleep=before_clock.sleep)(request())
        self.assertEqual(raised.exception.error["code"], "FEED_UNAVAILABLE")
        self.assertEqual(before_fetcher.calls, [])

        after_fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /", "text/plain"),
            FEED_URL: response(rss(rss_item(1)), "application/rss+xml"),
        })
        after_clock = FakeClock()
        result = CbrHandler(
            source_policy(job_timeout_seconds=3), fetcher=after_fetcher,
            clock=after_clock.monotonic, sleep=after_clock.sleep,
        )(request())
        self.assertEqual(result["items"], [])
        self.assertEqual(result["result_status"], "partial")
        self.assertIn("items", result["incomplete_fields"])

    def test_document_and_robots_nofollow_prevent_attachment_delivery(self):
        url = "https://www.cbr.ru/press/PR/?file=fixture-1.htm"
        page = """<html><head><meta name='robots' content='nofollow'></head><body>
        <h1>Материал</h1><div class='landing-text'>Полный текст.
        <a href='/files/attachment.pdf'>PDF</a></div></body></html>"""
        fetcher = FakeFetcher({
            ROBOTS_URL: response("User-agent: *\nAllow: /press/\nDisallow: /files/", "text/plain"),
            FEED_URL: response(rss(rss_item(1)), "application/rss+xml"),
            url: response(page, "text/html"),
        })
        clock = FakeClock()
        result = CbrHandler(source_policy(), fetcher=fetcher,
                            clock=clock.monotonic, sleep=clock.sleep)(request())
        self.assertEqual(result["items"][0]["attachments"], [])
        self.assertEqual([call["kind"] for call in fetcher.calls],
                         ["robots", "feed", "page"])


if __name__ == "__main__":
    unittest.main()
