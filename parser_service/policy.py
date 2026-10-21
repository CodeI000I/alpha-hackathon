"""Явная политика одного источника прототипа; разрешающих defaults нет."""

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .config import positive_setting


@dataclass(frozen=True)
class SourcePolicy:
    version: str
    allow_fetch: bool
    allow_persist: bool
    max_items: int
    max_response_bytes: int
    max_total_bytes: int
    request_timeout_seconds: int
    job_timeout_seconds: int
    min_interval_seconds: int
    user_agent: str

    def __post_init__(self):
        if not isinstance(self.version, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.version
        ):
            raise ValueError("Invalid CBR policy version")
        if type(self.allow_fetch) is not bool or type(self.allow_persist) is not bool:
            raise ValueError("Source permissions must be explicit booleans")
        for name in ("max_items", "max_response_bytes", "max_total_bytes",
                     "request_timeout_seconds", "job_timeout_seconds", "min_interval_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (not isinstance(self.user_agent, str) or not self.user_agent
                or not self.user_agent.isascii()
                or any(not c.isprintable() for c in self.user_agent)):
            raise ValueError("A printable ASCII User-Agent is required")

    def validate_url(self, url, kind):
        if (not isinstance(url, str) or not url or not url.isascii()
                or any(c.isspace() or not c.isprintable() for c in url)
                or "\\" in url or "#" in url):
            raise ValueError("URL blocked by source policy")
        try:
            parts = urlsplit(url)
            valid_origin = (
                parts.scheme == "https"
                and parts.netloc.lower() in ("www.cbr.ru", "www.cbr.ru:443")
                and parts.port in (None, 443)
            )
        except ValueError:
            raise ValueError("URL blocked by source policy") from None
        path = parts.path
        if (not valid_origin or "%" in path or "//" in path
                or any(segment in (".", "..") for segment in path.split("/"))
                or path.lower().startswith(("/search/", "/content/savetopdf/"))):
            raise ValueError("URL blocked by source policy")
        allowed = {
            "robots": path == "/robots.txt" and not parts.query,
            "feed": path == "/rss/RssPress" and not parts.query,
            "page": path.startswith("/press/"),
            "attachment": path.lower().endswith(".pdf"),
        }
        if not allowed.get(kind, False):
            raise ValueError("URL blocked by source policy")
        return url

    @classmethod
    def from_env(cls):
        def permission(name):
            value = os.environ.get(name)
            if value not in ("true", "false"):
                raise ValueError(f"{name} must be explicitly true or false")
            return value == "true"

        limits = {
            name: positive_setting("PARSER_CBR_" + name.upper())
            for name in ("max_items", "max_response_bytes", "max_total_bytes",
                         "request_timeout_seconds", "job_timeout_seconds", "min_interval_seconds")
        }
        return cls(
            version=os.environ.get("PARSER_CBR_POLICY_VERSION", ""),
            allow_fetch=permission("PARSER_CBR_ALLOW_FETCH"),
            allow_persist=permission("PARSER_CBR_ALLOW_PERSIST"),
            user_agent=os.environ.get("PARSER_CBR_USER_AGENT", ""),
            **limits,
        )
