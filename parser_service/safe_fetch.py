"""Bounded HTTPS fetching in a disposable child process."""

from __future__ import annotations

import base64
import binascii
import codecs
from email.message import Message
import http.client
import ipaddress
import json
import math
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from .policy import SourcePolicy


_ERRORS = {
    "URL_BLOCKED": ("URL is not allowed by source policy.", False),
    "DNS_ERROR": ("DNS resolution failed.", True),
    "IP_BLOCKED": ("Resolved address is not allowed.", False),
    "TLS_ERROR": ("TLS verification failed.", False),
    "NETWORK_ERROR": ("Network request failed.", True),
    "TIMEOUT": ("Request timed out.", True),
    "REDIRECT_BLOCKED": ("Redirects are not allowed.", False),
    "ACCESS_DENIED": ("Source denied access.", False),
    "NOT_FOUND": ("Resource was not found.", False),
    "RATE_LIMITED": ("Source rate limit was reached.", True),
    "HTTP_UNAVAILABLE": ("Source is temporarily unavailable.", True),
    "HTTP_ERROR": ("Source returned an HTTP error.", False),
    "MIME_UNSUPPORTED": ("Response media type is not supported.", False),
    "ENCODING_UNSUPPORTED": ("Response content encoding is not supported.", False),
    "SIZE_LIMIT": ("Response exceeded the allowed size.", False),
    "PROTOCOL_ERROR": ("Fetcher child returned an invalid response.", False),
}

_ALLOWED_MIME = {
    "robots": {"text/plain"},
    "feed": {"application/rss+xml", "application/xml", "text/xml"},
    "page": {"text/html"},
}


class FetchError(Exception):
    def __init__(self, code: str, bytes_read: int = 0) -> None:
        try:
            message, retryable = _ERRORS[code]
        except KeyError as exc:
            raise ValueError("unknown fetch error code") from exc
        if type(bytes_read) is not int or bytes_read < 0:
            raise ValueError("bytes_read must be a non-negative integer")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.bytes_read = bytes_read
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "bytes_read": self.bytes_read,
        }


@dataclass(frozen=True)
class FetchResponse:
    body: bytes
    content_type: str
    fetched_at: str

    @property
    def bytes_read(self) -> int:
        return len(self.body)


class SafeFetcher:
    def __init__(self, policy: SourcePolicy) -> None:
        self.policy = policy

    def fetch(
        self,
        url: str,
        *,
        kind: str,
        timeout_seconds: float,
        max_bytes: int,
    ) -> FetchResponse:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if not self.policy.allow_fetch:
            raise FetchError("URL_BLOCKED")

        try:
            normalized_url = self.policy.validate_url(url, kind)
        except ValueError:
            raise FetchError("URL_BLOCKED") from None
        requested_timeout = min(
            float(timeout_seconds), float(self.policy.request_timeout_seconds)
        )
        requested_cap = min(max_bytes, self.policy.max_response_bytes)
        payload = {
            "policy": asdict(self.policy),
            "url": normalized_url,
            "kind": kind,
            "timeout_seconds": requested_timeout,
            "max_bytes": requested_cap,
        }
        try:
            completed = subprocess.run(
                _child_command(),
                input=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=requested_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise FetchError("TIMEOUT", bytes_read=requested_cap) from None
        except OSError:
            raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap) from None

        if completed.returncode != 0:
            raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
        return _decode_child_response(completed.stdout, requested_cap)


def _child_command() -> list[str]:
    return [sys.executable, "-m", "parser_service.safe_fetch", "--child"]


def _decode_child_response(stdout: bytes, requested_cap: int) -> FetchResponse:
    encoded_bound = 4 * ((requested_cap + 2) // 3) + 1024
    if len(stdout) > encoded_bound:
        raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
    try:
        response = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap) from None
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)

    if response["ok"] is False:
        error = response.get("error")
        if not isinstance(error, dict):
            raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
        code = error.get("code")
        bytes_read = error.get("bytes_read")
        if (
            code not in _ERRORS
            or type(bytes_read) is not int
            or not 0 <= bytes_read <= requested_cap
        ):
            raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
        expected_message, expected_retryable = _ERRORS[code]
        if (
            error.get("message") != expected_message
            or error.get("retryable") is not expected_retryable
        ):
            raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
        raise FetchError(code, bytes_read=bytes_read)

    body_text = response.get("body")
    content_type = response.get("content_type")
    fetched_at = response.get("fetched_at")
    if not all(isinstance(value, str) for value in (body_text, content_type, fetched_at)):
        raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
    try:
        body = base64.b64decode(body_text, validate=True)
        timestamp = datetime.fromisoformat(fetched_at)
    except (binascii.Error, ValueError):
        raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap) from None
    if len(body) > requested_cap or timestamp.utcoffset() != timezone.utc.utcoffset(None):
        raise FetchError("PROTOCOL_ERROR", bytes_read=requested_cap)
    return FetchResponse(body=body, content_type=content_type, fetched_at=fetched_at)


def _fetch_direct(
    policy: SourcePolicy,
    url: str,
    *,
    kind: str,
    timeout_seconds: float,
    max_bytes: int,
) -> FetchResponse:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > policy.request_timeout_seconds
        or type(max_bytes) is not int
        or max_bytes <= 0
        or max_bytes > policy.max_response_bytes
    ):
        raise FetchError("PROTOCOL_ERROR")
    if not policy.allow_fetch:
        raise FetchError("URL_BLOCKED")
    try:
        normalized_url = policy.validate_url(url, kind)
    except ValueError:
        raise FetchError("URL_BLOCKED") from None
    parsed = urlsplit(normalized_url)
    hostname = parsed.hostname
    if hostname != "www.cbr.ru" or parsed.port not in (None, 443):
        raise FetchError("URL_BLOCKED")

    started = time.monotonic()
    body = bytearray()
    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    connection: http.client.HTTPSConnection | None = None
    response: http.client.HTTPResponse | None = None
    try:
        try:
            addresses = socket.getaddrinfo(
                hostname, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
        except socket.gaierror:
            raise FetchError("DNS_ERROR") from None
        if not addresses:
            raise FetchError("DNS_ERROR")

        validated = []
        for family, socktype, proto, _canonname, sockaddr in addresses:
            try:
                address = ipaddress.ip_address(sockaddr[0])
            except ValueError:
                raise FetchError("IP_BLOCKED") from None
            if (
                not address.is_global
                or address.is_reserved
                or address.is_multicast
                or address.is_unspecified
                or getattr(address, "ipv4_mapped", None) is not None
            ):
                raise FetchError("IP_BLOCKED")
            validated.append((family, socktype, proto, sockaddr, address))

        family, socktype, proto, sockaddr, chosen_address = validated[0]
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise FetchError("TIMEOUT")
        raw_socket = socket.socket(family, socktype, proto)
        raw_socket.settimeout(remaining)
        raw_socket.connect(sockaddr)

        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise FetchError("TIMEOUT")
        raw_socket.settimeout(remaining)
        context = ssl.create_default_context()
        tls_socket = context.wrap_socket(raw_socket, server_hostname=hostname)
        raw_socket = None
        peer_address = ipaddress.ip_address(tls_socket.getpeername()[0])
        if peer_address != chosen_address:
            raise FetchError("IP_BLOCKED")

        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise FetchError("TIMEOUT")
        tls_socket.settimeout(remaining)
        connection = http.client.HTTPSConnection(
            hostname, 443, timeout=remaining, context=context
        )
        connection.sock = tls_socket
        tls_socket = None
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request(
            "GET",
            target,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": policy.user_agent,
            },
        )
        response = http.client.HTTPResponse(connection.sock, method="GET")
        response.begin()
        status = response.status
        if 300 <= status < 400:
            raise FetchError("REDIRECT_BLOCKED")
        if status == 403:
            raise FetchError("ACCESS_DENIED")
        if status == 404:
            raise FetchError("NOT_FOUND")
        if status == 429:
            raise FetchError("RATE_LIMITED")
        if 500 <= status < 600:
            raise FetchError("HTTP_UNAVAILABLE")
        if status != 200:
            raise FetchError("HTTP_ERROR")

        content_encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if content_encoding != "identity":
            raise FetchError("ENCODING_UNSUPPORTED")
        raw_content_type = response.getheader("Content-Type") or ""
        content_type_header = Message()
        content_type_header["content-type"] = raw_content_type
        parameters = content_type_header.get_params(header="content-type", failobj=[]) or []
        charsets = [value for name, value in parameters[1:] if name.lower() == "charset"]
        if kind in {"page", "robots"} and charsets:
            if len(charsets) != 1:
                raise FetchError("ENCODING_UNSUPPORTED")
            try:
                charset = codecs.lookup(charsets[0]).name
            except (LookupError, TypeError):
                raise FetchError("ENCODING_UNSUPPORTED") from None
            if charset not in {"utf-8", "utf-8-sig"}:
                raise FetchError("ENCODING_UNSUPPORTED")
        content_type = raw_content_type.split(";", 1)[0].strip().lower()
        if kind not in _ALLOWED_MIME or content_type not in _ALLOWED_MIME[kind]:
            raise FetchError("MIME_UNSUPPORTED")

        content_length_text = response.getheader("Content-Length")
        content_length: int | None = None
        if content_length_text is not None:
            try:
                content_length = int(content_length_text)
            except ValueError:
                raise FetchError("PROTOCOL_ERROR") from None
            if content_length < 0:
                raise FetchError("PROTOCOL_ERROR")
            if content_length > max_bytes:
                raise FetchError("SIZE_LIMIT")

        while True:
            if content_length is None and len(body) == max_bytes:
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise FetchError("TIMEOUT", bytes_read=len(body))
                connection.sock.settimeout(remaining)
                if response.read(1):
                    raise FetchError("SIZE_LIMIT", bytes_read=len(body) + 1)
                break
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise FetchError("TIMEOUT", bytes_read=len(body))
            connection.sock.settimeout(remaining)
            allowance = max_bytes - len(body)
            if content_length is not None:
                allowance = min(allowance, content_length - len(body))
                if allowance == 0:
                    break
            chunk = response.read(min(64 * 1024, allowance))
            if not chunk:
                break
            body.extend(chunk)

        if content_length is not None and len(body) != content_length:
            raise FetchError("PROTOCOL_ERROR", bytes_read=len(body))
        return FetchResponse(
            body=bytes(body),
            content_type=content_type,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    except FetchError:
        raise
    except ssl.SSLError:
        raise FetchError("TLS_ERROR", bytes_read=len(body)) from None
    except (TimeoutError, socket.timeout):
        raise FetchError("TIMEOUT", bytes_read=len(body)) from None
    except (OSError, http.client.HTTPException):
        raise FetchError("NETWORK_ERROR", bytes_read=len(body)) from None
    finally:
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()
        if tls_socket is not None:
            tls_socket.close()
        if raw_socket is not None:
            raw_socket.close()


def _child_main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
        if not isinstance(payload, dict) or not isinstance(payload.get("policy"), dict):
            raise ValueError
        policy = SourcePolicy(**payload["policy"])
        response = _fetch_direct(
            policy,
            payload["url"],
            kind=payload["kind"],
            timeout_seconds=payload["timeout_seconds"],
            max_bytes=payload["max_bytes"],
        )
        output = {
            "ok": True,
            "body": base64.b64encode(response.body).decode("ascii"),
            "content_type": response.content_type,
            "fetched_at": response.fetched_at,
        }
    except FetchError as exc:
        output = {"ok": False, "error": exc.as_dict()}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        output = {
            "ok": False,
            "error": FetchError("PROTOCOL_ERROR").as_dict(),
        }
    sys.stdout.buffer.write(json.dumps(output, separators=(",", ":")).encode("utf-8"))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--child"]:
        raise SystemExit(2)
    raise SystemExit(_child_main())
