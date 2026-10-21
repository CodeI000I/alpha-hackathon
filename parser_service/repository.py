"""PostgreSQL persistence for queued parser jobs."""

from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class JobConflict(Exception):
    """The job ID is already bound to a different request."""


class RepositoryUnavailable(Exception):
    """The jobs repository could not complete an operation."""


class LeaseLost(Exception):
    """The worker no longer owns an active lease for the job."""


class JobRepository:
    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout: int,
        statement_timeout_ms: int,
    ) -> None:
        if type(connect_timeout) is not int or connect_timeout <= 0:
            raise ValueError("connect_timeout must be a positive integer")
        if type(statement_timeout_ms) is not int or statement_timeout_ms <= 0:
            raise ValueError("statement_timeout_ms must be a positive integer")
        self._dsn = dsn
        self._connect_timeout = connect_timeout
        self._statement_timeout_ms = statement_timeout_ms

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO parser.jobs (job_id, request)
                        VALUES (%s, %s)
                        ON CONFLICT (job_id) DO NOTHING
                        RETURNING *
                        """,
                        (request["job_id"], Jsonb(request)),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            """
                            SELECT * FROM parser.jobs WHERE job_id = %s
                            """,
                            (request["job_id"],),
                        )
                        row = cursor.fetchone()
                        if row is None:
                            raise RepositoryUnavailable("job repository unavailable")
                        if row["request"] != request:
                            raise JobConflict(
                                "job ID already exists with a different request"
                            )
            return dict(row)
        except (JobConflict, RepositoryUnavailable):
            raise
        except psycopg.Error:
            raise RepositoryUnavailable("job repository unavailable") from None

    def get(self, job_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM parser.jobs WHERE job_id = %s
                        """,
                        (job_id,),
                    )
                    row = cursor.fetchone()
            return dict(row) if row is not None else None
        except psycopg.Error:
            raise RepositoryUnavailable("job repository unavailable") from None

    def claim(
        self,
        *,
        lease_seconds: int,
        max_attempts: int,
    ) -> dict[str, Any] | None:
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")

        exhausted_error = {
            "code": "ATTEMPTS_EXHAUSTED",
            "message": "Job attempts exhausted.",
            "retryable": False,
        }
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        WITH candidate AS (
                            SELECT job_id
                            FROM parser.jobs
                            WHERE status = 'queued'
                               OR (status = 'running'
                                   AND lease_expires_at <= clock_timestamp())
                            ORDER BY created_at, job_id
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE parser.jobs AS job
                        SET status = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN 'failed'
                                ELSE 'running'
                            END,
                            attempt = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN job.attempt
                                ELSE job.attempt + 1
                            END,
                            lease_token = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN NULL
                                ELSE %(lease_token)s
                            END,
                            lease_expires_at = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN NULL
                                ELSE clock_timestamp()
                                     + make_interval(secs => %(lease_seconds)s)
                            END,
                            started_at = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN job.started_at
                                ELSE COALESCE(job.started_at, clock_timestamp())
                            END,
                            finished_at = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN clock_timestamp()
                                ELSE NULL
                            END,
                            result = NULL,
                            error = CASE
                                WHEN job.attempt >= %(max_attempts)s
                                    THEN %(exhausted_error)s
                                ELSE NULL
                            END,
                            updated_at = clock_timestamp()
                        FROM candidate
                        WHERE job.job_id = candidate.job_id
                        RETURNING job.*
                        """,
                        {
                            "max_attempts": max_attempts,
                            "lease_token": uuid4(),
                            "lease_seconds": lease_seconds,
                            "exhausted_error": Jsonb(exhausted_error),
                        },
                    )
                    row = cursor.fetchone()
            return dict(row) if row is not None else None
        except psycopg.Error:
            raise RepositoryUnavailable("job repository unavailable") from None

    def finish(
        self,
        job_id: str,
        lease_token: UUID | str,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if (result is None) == (error is None):
            raise ValueError("provide exactly one of result or error")

        status = "succeeded" if result is not None else "failed"
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1 FROM parser.jobs
                        WHERE job_id = %s
                        FOR UPDATE
                        """,
                        (job_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE parser.jobs
                        SET status = %s,
                            result = %s,
                            error = %s,
                            finished_at = clock_timestamp(),
                            updated_at = clock_timestamp(),
                            lease_token = NULL,
                            lease_expires_at = NULL
                        WHERE job_id = %s
                          AND status = 'running'
                          AND lease_token = %s::uuid
                          AND lease_expires_at > clock_timestamp()
                        RETURNING *
                        """,
                        (
                            status,
                            Jsonb(result) if result is not None else None,
                            Jsonb(error) if error is not None else None,
                            job_id,
                            lease_token,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise LeaseLost("job lease is no longer active")
            return dict(row)
        except LeaseLost:
            raise
        except psycopg.Error:
            raise RepositoryUnavailable("job repository unavailable") from None

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        connection = psycopg.connect(
            self._dsn,
            connect_timeout=self._connect_timeout,
            options=f"-c statement_timeout={self._statement_timeout_ms}",
            row_factory=dict_row,
        )
        try:
            connection.isolation_level = IsolationLevel.READ_COMMITTED
            with connection:
                yield connection
        finally:
            connection.close()
