"""Один явно запрошенный проход, без встроенного расписания и миграций."""

import argparse
from contextlib import closing
import json
import os

import psycopg

from .cbr import CbrHandler
from .config import positive_setting
from .executor import execute_once
from .policy import SourcePolicy
from .repository import JobRepository, LeaseLost, RepositoryUnavailable


def run_once(repository, handler, *, lease_seconds, max_attempts, max_items):
    for name, value in (("lease_seconds", lease_seconds), ("max_attempts", max_attempts),
                        ("max_items", max_items)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not callable(handler):
        raise ValueError("handler must be callable")
    policy = getattr(handler, "policy", None)
    if policy is not None:
        if not policy.allow_fetch or not policy.allow_persist:
            raise ValueError("Source permissions must allow this worker")
        if lease_seconds <= policy.job_timeout_seconds:
            raise ValueError("Lease must exceed the source job budget")
    try:
        # Autocommit: session lock spans HTTP, no open SQL transaction spans HTTP.
        with closing(psycopg.connect(
            repository._dsn, connect_timeout=repository._connect_timeout,
            options=f"-c statement_timeout={repository._statement_timeout_ms}",
            autocommit=True,
        )) as connection:
            locked = connection.execute(
                "SELECT pg_try_advisory_lock(hashtext('kib.parser.source.cbr_press'))"
            ).fetchone()[0]
            if not locked:
                return None
            return execute_once(repository, handler, lease_seconds=lease_seconds,
                                max_attempts=max_attempts, max_items=max_items)
    except psycopg.Error:
        raise RepositoryUnavailable("source worker storage unavailable") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", required=True)
    parser.parse_args()
    try:
        policy = SourcePolicy.from_env()
        dsn = os.environ.get("PARSER_DATABASE_URL")
        if not dsn:
            raise ValueError("PARSER_DATABASE_URL is required")
        repository = JobRepository(
            dsn, connect_timeout=positive_setting("PARSER_CONNECT_TIMEOUT_SECONDS"),
            statement_timeout_ms=positive_setting("PARSER_STATEMENT_TIMEOUT_MS"))
        row = run_once(repository, CbrHandler(policy),
                       lease_seconds=positive_setting("PARSER_LEASE_SECONDS"),
                       max_attempts=positive_setting("PARSER_MAX_ATTEMPTS"),
                       max_items=policy.max_items)
    except (ValueError, RepositoryUnavailable, LeaseLost) as exc:
        print(json.dumps({"error": type(exc).__name__}))
        return 2
    print(json.dumps({"job_id": row["job_id"], "status": row["status"]}
                     if row else {"status": "no_job_or_source_busy"}))
    return 1 if row and row["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
