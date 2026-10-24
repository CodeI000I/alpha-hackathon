"""Apply analytics migrations explicitly; serving APIs never migrate on startup."""

from contextlib import closing
import os
from pathlib import Path

import psycopg


def apply_migrations(dsn: str, *, connect_timeout: int, statement_timeout_ms: int) -> list[str]:
    for name, value in (('connect_timeout', connect_timeout), ('statement_timeout_ms', statement_timeout_ms)):
        if type(value) is not int or value <= 0:
            raise ValueError(f'{name} must be a positive integer')
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError('dsn is required')
    directory = Path(__file__).with_name('migrations')
    applied = []
    with closing(psycopg.connect(dsn, autocommit=True, connect_timeout=connect_timeout,
                                 options=f'-c statement_timeout={statement_timeout_ms}')) as connection:
        connection.execute("SELECT pg_advisory_lock(hashtextextended('alpha.analytics.migrations', 0))")
        connection.execute('CREATE SCHEMA IF NOT EXISTS analytics')
        connection.execute('''CREATE TABLE IF NOT EXISTS analytics.schema_migrations (
            name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())''')
        for migration in sorted(directory.glob('*.sql')):
            with connection.transaction():
                exists = connection.execute('SELECT 1 FROM analytics.schema_migrations WHERE name=%s',
                                             (migration.name,)).fetchone()
                if exists:
                    continue
                connection.execute(migration.read_text(encoding='utf-8'), prepare=False)
                connection.execute('INSERT INTO analytics.schema_migrations(name) VALUES (%s)',
                                   (migration.name,))
            applied.append(migration.name)
        connection.execute("SELECT pg_advisory_unlock(hashtextextended('alpha.analytics.migrations', 0))")
    return applied


def main() -> None:
    dsn = os.environ.get('ANALYTICS_DATABASE_URL', '')
    if not dsn.strip():
        raise ValueError('ANALYTICS_DATABASE_URL is required')
    try:
        applied = apply_migrations(dsn, connect_timeout=5, statement_timeout_ms=5000)
    except psycopg.Error:
        raise SystemExit('Analytics migration failed; check PostgreSQL and pgvector availability.') from None
    print('Analytics migrations applied: ' + (', '.join(applied) or 'already current'))


if __name__ == '__main__':
    main()
