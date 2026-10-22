"""Явные последовательные миграции; API их не запускает."""

from contextlib import closing
import os
from pathlib import Path

import psycopg

from .config import positive_setting


def apply_migrations(dsn, *, connect_timeout, statement_timeout_ms):
    for name, value in (("connect_timeout", connect_timeout),
                        ("statement_timeout_ms", statement_timeout_ms)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    directory = Path(__file__).with_name("migrations")
    applied = []
    with closing(psycopg.connect(
            dsn,
            autocommit=True,
            connect_timeout=connect_timeout,
            options=f"-c statement_timeout={statement_timeout_ms}",
    )) as connection:
        # Session lock spans the original self-contained bootstrap transaction too.
        connection.execute("SELECT pg_advisory_lock(hashtext('kib.parser.migrations'))")
        bootstrap = directory / "0001_jobs.sql"
        connection.execute(bootstrap.read_text(encoding="utf-8"), prepare=False)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS parser.schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
            )
        """)
        connection.execute(
            "INSERT INTO parser.schema_migrations (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (bootstrap.name,),
        )
        for migration in sorted(directory.glob("*.sql")):
            with connection.transaction():
                if connection.execute(
                    "SELECT 1 FROM parser.schema_migrations WHERE name = %s",
                    (migration.name,),
                ).fetchone():
                    continue
                connection.execute(migration.read_text(encoding="utf-8"), prepare=False)
                connection.execute(
                    "INSERT INTO parser.schema_migrations (name) VALUES (%s)",
                    (migration.name,),
                )
            applied.append(migration.name)
    return applied


def main():
    dsn = os.environ.get("PARSER_DATABASE_URL", "")
    if not dsn.strip():
        raise ValueError("PARSER_DATABASE_URL is required")
    try:
        applied = apply_migrations(
            dsn,
            connect_timeout=positive_setting("PARSER_CONNECT_TIMEOUT_SECONDS"),
            statement_timeout_ms=positive_setting("PARSER_STATEMENT_TIMEOUT_MS"),
        )
    except psycopg.Error:
        raise SystemExit("Migration failed; check database access and schema.") from None
    print("Parser migrations applied: " + (", ".join(applied) or "already current"))


if __name__ == "__main__":
    main()
