import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import ssl

from parser_service.policy import SourcePolicy
from parser_service.safe_fetch import FetchError, SafeFetcher, _fetch_direct


def source_policy(**changes):
    values = {
        "version": "cbr-v1",
        "allow_fetch": True,
        "allow_persist": True,
        "max_items": 3,
        "max_response_bytes": 1024 * 1024,
        "max_total_bytes": 4 * 1024 * 1024,
        "request_timeout_seconds": 10,
        "job_timeout_seconds": 45,
        "min_interval_seconds": 1,
        "user_agent": "KIBNewsPrototype/0.1",
    }
    values.update(changes)
    return SourcePolicy(**values)


class SourcePolicyTests(unittest.TestCase):
    def test_accepts_only_configured_cbr_urls_for_each_kind(self):
        policy = source_policy()
        accepted = {
            "robots": "https://www.cbr.ru/robots.txt",
            "feed": "https://www.cbr.ru/rss/RssPress",
            "page": "https://www.cbr.ru/press/PR/?file=fixture.htm",
            "attachment": "https://www.cbr.ru/files/fixture.pdf",
        }
        for kind, url in accepted.items():
            with self.subTest(kind=kind):
                self.assertEqual(policy.validate_url(url, kind), url)

    def test_rejects_ambiguous_or_out_of_policy_urls(self):
        policy = source_policy()
        rejected = [
            ("http://www.cbr.ru/rss/RssPress", "feed"),
            ("https://cbr.ru/rss/RssPress", "feed"),
            ("https://www.cbr.ru:444/rss/RssPress", "feed"),
            ("https://user@www.cbr.ru/rss/RssPress", "feed"),
            ("https://www.cbr.ru/rss/RssPress#fragment", "feed"),
            ("https://www.cbr.ru/press/../robots.txt", "page"),
            ("https://www.cbr.ru/press/%2e%2e/robots.txt", "page"),
            ("https://www.cbr.ru/press%2f..%2frobots.txt", "page"),
            ("https://www.cbr.ru/press\\fixture.htm", "page"),
            ("https://www.cbr.ru/SaveToPdf?url=/press/fixture", "attachment"),
            ("https://www.cbr.ru/search/?text=fixture.pdf", "attachment"),
            ("https://www.cbr.ru/files/fixture.pdf\nheader", "attachment"),
        ]
        for url, kind in rejected:
            with self.subTest(url=url, kind=kind):
                with self.assertRaises(ValueError):
                    policy.validate_url(url, kind)

    def test_rejects_invalid_policy_configuration(self):
        invalid = [
            {"version": "bad version"},
            {"allow_fetch": 1},
            {"allow_persist": "yes"},
            {"max_items": 0},
            {"max_response_bytes": True},
            {"max_total_bytes": -1},
            {"request_timeout_seconds": 1.5},
            {"job_timeout_seconds": 0},
            {"min_interval_seconds": False},
            {"user_agent": "bad\r\nheader"},
            {"user_agent": "КИБ/0.1"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    source_policy(**changes)


class SafeFetcherTests(unittest.TestCase):
    def _fetch_raw_http(
        self, raw_http, *, kind="page", max_bytes=4096, stream_factory=io.BytesIO
    ):
        observed = {"tls_closed": False}
        self.raw_transport_observed = observed

        class FakeSocket:
            def settimeout(self, _timeout): pass
            def connect(self, _address): pass
            def close(self): pass

        class FakeTls(FakeSocket):
            def __init__(self):
                self.stream = stream_factory(raw_http)

            def getpeername(self): return ("8.8.8.8", 443)
            def makefile(self, *_args, **_kwargs): return self.stream
            def close(self): observed["tls_closed"] = True

        class FakeContext:
            def wrap_socket(self, _socket, server_hostname): return FakeTls()

        class FakeConnection:
            def __init__(self, *_args, **_kwargs): self.sock = None
            def request(self, *_args, **_kwargs): pass
            def close(self):
                if self.sock is not None:
                    self.sock.close()

        address = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                   ("8.8.8.8", 443))
        with patch("parser_service.safe_fetch.socket.getaddrinfo", return_value=[address]), \
             patch("parser_service.safe_fetch.socket.socket", return_value=FakeSocket()), \
             patch("parser_service.safe_fetch.ssl.create_default_context",
                   return_value=FakeContext()), \
             patch("parser_service.safe_fetch.http.client.HTTPSConnection", FakeConnection):
            result = _fetch_direct(
                source_policy(),
                ("https://www.cbr.ru/robots.txt" if kind == "robots"
                 else "https://www.cbr.ru/press/PR/?file=fixture.htm"),
                kind=kind, timeout_seconds=2, max_bytes=max_bytes,
            )
        return result, observed

    def test_fetch_caps_child_request_and_decodes_fixed_protocol(self):
        child_output = json.dumps({
            "ok": True,
            "body": base64.b64encode(b"fixture").decode(),
            "content_type": "application/rss+xml",
            "fetched_at": "2026-10-21T12:00:00+00:00",
        }).encode()
        completed = subprocess.CompletedProcess([], 0, stdout=child_output)
        with patch("parser_service.safe_fetch.subprocess.run", return_value=completed) as run:
            fetched = SafeFetcher(source_policy()).fetch(
                "https://www.cbr.ru/rss/RssPress",
                kind="feed",
                timeout_seconds=100,
                max_bytes=2 * 1024 * 1024,
            )

        self.assertEqual(fetched.body, b"fixture")
        self.assertEqual(fetched.bytes_read, 7)
        call = run.call_args
        payload = json.loads(call.kwargs["input"])
        self.assertEqual(payload["timeout_seconds"], 10.0)
        self.assertEqual(payload["max_bytes"], 1024 * 1024)
        self.assertEqual(call.kwargs["timeout"], 10.0)
        self.assertNotIn("env", call.kwargs)

    def test_chunked_body_exactly_at_limit_is_accepted(self):
        response, _ = self._fetch_raw_http(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n4\r\ntest\r\n0\r\n\r\n",
            max_bytes=4,
        )
        self.assertEqual(response.body, b"test")

    def test_chunked_body_one_byte_over_limit_is_rejected(self):
        with self.assertRaises(FetchError) as raised:
            self._fetch_raw_http(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n5\r\ntests\r\n0\r\n\r\n",
                max_bytes=4,
            )
        self.assertEqual(raised.exception.code, "SIZE_LIMIT")
        self.assertEqual(raised.exception.bytes_read, 5)

    def test_parent_timeout_charges_full_requested_cap(self):
        with patch(
            "parser_service.safe_fetch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["child"], 2),
        ):
            with self.assertRaises(FetchError) as raised:
                SafeFetcher(source_policy()).fetch(
                    "https://www.cbr.ru/rss/RssPress",
                    kind="feed",
                    timeout_seconds=2,
                    max_bytes=4096,
                )
        self.assertEqual(raised.exception.code, "TIMEOUT")
        self.assertEqual(raised.exception.bytes_read, 4096)
        self.assertIs(raised.exception.retryable, True)

    def test_blocked_url_never_starts_child(self):
        with patch("parser_service.safe_fetch.subprocess.run") as run:
            with self.assertRaises(FetchError) as raised:
                SafeFetcher(source_policy()).fetch(
                    "https://example.com/feed", kind="feed",
                    timeout_seconds=2, max_bytes=4096,
                )
        self.assertEqual(raised.exception.code, "URL_BLOCKED")
        run.assert_not_called()

    def test_invalid_or_forged_child_output_is_protocol_error(self):
        outputs = [
            b"not-json",
            json.dumps({"ok": False, "error": {
                "code": "TIMEOUT", "message": "forged", "retryable": True,
                "bytes_read": 1,
            }}).encode(),
            json.dumps({"ok": True, "body": "!!!", "content_type": "text/html",
                        "fetched_at": "not-a-time"}).encode(),
        ]
        for output in outputs:
            with self.subTest(output=output), patch(
                "parser_service.safe_fetch.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=output),
            ):
                with self.assertRaises(FetchError) as raised:
                    SafeFetcher(source_policy()).fetch(
                        "https://www.cbr.ru/rss/RssPress", kind="feed",
                        timeout_seconds=2, max_bytes=4096,
                    )
                self.assertEqual(raised.exception.code, "PROTOCOL_ERROR")

    def test_error_dictionary_contains_only_safe_fixed_fields(self):
        error = FetchError("NETWORK_ERROR", bytes_read=17)
        self.assertEqual(
            error.as_dict(),
            {"code": "NETWORK_ERROR", "message": "Network request failed.",
             "retryable": True, "bytes_read": 17},
        )

    def test_connection_close_response_reads_from_detached_tls_socket(self):
        observed = {}

        class FakeSocket:
            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                pass

            def close(self):
                pass

        class FakeTlsSocket(FakeSocket):
            def getpeername(self):
                return ("8.8.8.8", 443)

        class FakeContext:
            def wrap_socket(self, _socket, server_hostname):
                observed["server_hostname"] = server_hostname
                return FakeTlsSocket()

        class FakeResponse:
            status = 200
            will_close = True

            def __init__(self):
                self.closed = False
                self.body = b"fixture"

            def getheader(self, name):
                return {"Content-Encoding": "identity", "Content-Type": "text/html",
                        "Content-Length": "7"}.get(name)

            def begin(self):
                pass

            def read(self, amount):
                body, self.body = self.body[:amount], self.body[amount:]
                return body

            def close(self):
                self.closed = True

        response = FakeResponse()

        class FakeConnection:
            def __init__(self, host, port, **_kwargs):
                observed["connection_origin"] = (host, port)
                self.sock = None

            def request(self, method, target, headers):
                observed["request"] = (method, target, headers)

            def close(self):
                pass

        address = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                   ("8.8.8.8", 443))
        with patch("parser_service.safe_fetch.socket.getaddrinfo", return_value=[address]), \
             patch("parser_service.safe_fetch.socket.socket", return_value=FakeSocket()), \
             patch("parser_service.safe_fetch.ssl.create_default_context",
                   return_value=FakeContext()), \
             patch("parser_service.safe_fetch.http.client.HTTPSConnection", FakeConnection), \
             patch("parser_service.safe_fetch.http.client.HTTPResponse",
                   return_value=response):
            fetched = _fetch_direct(
                source_policy(),
                "https://www.cbr.ru/press/PR/?file=fixture.htm",
                kind="page",
                timeout_seconds=2,
                max_bytes=4096,
            )

        self.assertEqual(fetched.body, b"fixture")
        self.assertTrue(response.closed)
        self.assertEqual(observed["server_hostname"], "www.cbr.ru")
        self.assertEqual(observed["connection_origin"], ("www.cbr.ru", 443))
        method, target, headers = observed["request"]
        self.assertEqual((method, target), ("GET", "/press/PR/?file=fixture.htm"))
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertEqual(headers["User-Agent"], "KIBNewsPrototype/0.1")

    def test_mixed_public_and_private_dns_is_blocked_before_socket_creation(self):
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
        ]
        with patch("parser_service.safe_fetch.socket.getaddrinfo", return_value=addresses), \
             patch("parser_service.safe_fetch.socket.socket") as create_socket:
            with self.assertRaises(FetchError) as raised:
                _fetch_direct(
                    source_policy(), "https://www.cbr.ru/rss/RssPress", kind="feed",
                    timeout_seconds=2, max_bytes=4096,
                )
        self.assertEqual(raised.exception.code, "IP_BLOCKED")
        create_socket.assert_not_called()

    def test_transport_rejects_status_encoding_mime_size_and_short_body(self):
        class FakeSocket:
            def settimeout(self, _timeout): pass
            def connect(self, _address): pass
            def close(self): pass

        class FakeTls(FakeSocket):
            def getpeername(self): return ("8.8.8.8", 443)

        class FakeContext:
            def wrap_socket(self, _socket, server_hostname): return FakeTls()

        class FakeConnection:
            def __init__(self, *_args, **_kwargs): self.sock = None
            def request(self, *_args, **_kwargs): pass
            def close(self): pass

        class FakeResponse:
            def __init__(self, status, headers, body=b""):
                self.status, self.headers, self.body, self.closed = status, headers, body, False
            def begin(self): pass
            def getheader(self, name): return self.headers.get(name)
            def read(self, amount):
                chunk, self.body = self.body[:amount], self.body[amount:]
                return chunk
            def close(self): self.closed = True

        cases = [
            (FakeResponse(302, {}), "REDIRECT_BLOCKED"),
            (FakeResponse(200, {"Content-Encoding": "gzip"}), "ENCODING_UNSUPPORTED"),
            (FakeResponse(200, {"Content-Type": "application/json"}), "MIME_UNSUPPORTED"),
            (FakeResponse(200, {"Content-Type": "text/html", "Content-Length": "5000"}),
             "SIZE_LIMIT"),
            (FakeResponse(200, {"Content-Type": "text/html", "Content-Length": "8"},
                          b"short"), "PROTOCOL_ERROR"),
        ]
        address = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                   ("8.8.8.8", 443))
        for fake_response, code in cases:
            with self.subTest(code=code), \
                 patch("parser_service.safe_fetch.socket.getaddrinfo", return_value=[address]), \
                 patch("parser_service.safe_fetch.socket.socket", return_value=FakeSocket()), \
                 patch("parser_service.safe_fetch.ssl.create_default_context",
                       return_value=FakeContext()), \
                 patch("parser_service.safe_fetch.http.client.HTTPSConnection", FakeConnection), \
                 patch("parser_service.safe_fetch.http.client.HTTPResponse",
                       return_value=fake_response):
                with self.assertRaises(FetchError) as raised:
                    _fetch_direct(
                        source_policy(), "https://www.cbr.ru/press/PR/?file=fixture.htm",
                        kind="page", timeout_seconds=2, max_bytes=4096,
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertTrue(fake_response.closed)

    def test_real_sleeping_child_is_terminated_by_parent_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = os.path.join(directory, "child.pid")
            command = [
                sys.executable,
                "-c",
                "import os,sys,time;open(sys.argv[1],'w').write(str(os.getpid()));time.sleep(10)",
                pid_path,
            ]
            started = time.monotonic()
            with patch("parser_service.safe_fetch._child_command", return_value=command):
                with self.assertRaises(FetchError) as raised:
                    SafeFetcher(source_policy()).fetch(
                        "https://www.cbr.ru/rss/RssPress", kind="feed",
                        timeout_seconds=0.2, max_bytes=4096,
                    )
            self.assertEqual(raised.exception.code, "TIMEOUT")
            self.assertLess(time.monotonic() - started, 2)
            with open(pid_path, encoding="ascii") as pid_file:
                child_pid = int(pid_file.read())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

    def test_stdlib_http_response_reads_connection_close_body(self):
        raw = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            b"Content-Length: 7\r\nConnection: close\r\n\r\nfixture"
        )

        fetched, observed = self._fetch_raw_http(raw)

        self.assertEqual(fetched.body, b"fixture")
        self.assertTrue(observed["tls_closed"])

    def test_raw_http_rejects_unsupported_empty_unknown_or_duplicate_charset(self):
        content_types = [
            "text/html; charset=windows-1251",
            "text/html; charset=x-unknown-fixture",
            "text/html; charset=",
            "text/html; charset=utf-8; charset=utf-8",
        ]
        for content_type in content_types:
            raw = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                "Content-Length: 7\r\nConnection: close\r\n\r\nfixture"
            ).encode("ascii")
            with self.subTest(content_type=content_type):
                with self.assertRaises(FetchError) as raised:
                    self._fetch_raw_http(raw)
                self.assertEqual(raised.exception.code, "ENCODING_UNSUPPORTED")
                self.assertTrue(self.raw_transport_observed["tls_closed"])

    def test_raw_http_accepts_utf8_aliases_and_returns_bare_mime(self):
        for charset in ("utf-8", "UTF8", "utf_8_sig"):
            raw = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/html; charset={charset}\r\n"
                "Content-Length: 7\r\nConnection: close\r\n\r\nfixture"
            ).encode("ascii")
            with self.subTest(charset=charset):
                fetched, _observed = self._fetch_raw_http(raw)
            self.assertEqual(fetched.body, b"fixture")
            self.assertEqual(fetched.content_type, "text/html")

    def test_raw_http_requires_explicit_valid_robots_mime(self):
        cases = [
            b"HTTP/1.1 200 OK\r\nContent-Type: not-a-media-type\r\n"
            b"Content-Length: 7\r\nConnection: close\r\n\r\nfixture",
            b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n"
            b"Connection: close\r\n\r\nfixture",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(FetchError) as raised:
                    self._fetch_raw_http(raw, kind="robots")
                self.assertEqual(raised.exception.code, "MIME_UNSUPPORTED")

        valid = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
            b"Content-Length: 7\r\nConnection: close\r\n\r\nfixture"
        )
        fetched, _observed = self._fetch_raw_http(valid, kind="robots")
        self.assertEqual(fetched.content_type, "text/plain")

    def test_stdlib_chunked_body_at_exact_cap_is_accepted(self):
        raw = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n7\r\nfixture\r\n0\r\n\r\n"
        )

        fetched, _observed = self._fetch_raw_http(raw, max_bytes=7)
        self.assertEqual(fetched.body, b"fixture")

    def test_certificate_failure_maps_to_tls_error_and_closes_raw_socket(self):
        observed = {"raw_closed": False}

        class FakeSocket:
            def settimeout(self, _timeout): pass
            def connect(self, _address): pass
            def close(self): observed["raw_closed"] = True

        class BadContext:
            def wrap_socket(self, _socket, server_hostname):
                raise ssl.SSLCertVerificationError("fixture certificate failure")

        address = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                   ("8.8.8.8", 443))
        with patch("parser_service.safe_fetch.socket.getaddrinfo", return_value=[address]), \
             patch("parser_service.safe_fetch.socket.socket", return_value=FakeSocket()), \
             patch("parser_service.safe_fetch.ssl.create_default_context",
                   return_value=BadContext()):
            with self.assertRaises(FetchError) as raised:
                _fetch_direct(
                    source_policy(), "https://www.cbr.ru/rss/RssPress", kind="feed",
                    timeout_seconds=2, max_bytes=4096,
                )
        self.assertEqual(raised.exception.code, "TLS_ERROR")
        self.assertTrue(observed["raw_closed"])

    def test_slow_stdlib_body_maps_to_timeout_and_closes_tls(self):
        headers = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            b"Content-Length: 7\r\n\r\n"
        )

        class SlowStream(io.BytesIO):
            def read(self, _amount=-1):
                raise socket.timeout("fixture slow body")

        with self.assertRaises(FetchError) as raised:
            self._fetch_raw_http(headers, stream_factory=SlowStream)

        self.assertEqual(raised.exception.code, "TIMEOUT")
        self.assertTrue(self.raw_transport_observed["tls_closed"])


if __name__ == "__main__":
    unittest.main()
