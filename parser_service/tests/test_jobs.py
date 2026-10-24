import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from parser_service.migrate import apply_migrations
from parser_service.repository import JobConflict, JobRepository, RepositoryUnavailable

PAYLOAD = {
    "job_id": "job-1",
    "mode": "discover",
    "source_id": "cbr_press",
    "requested_level": "content",
    "policy_version": "cbr-v1",
}


class TestDatabaseUrlTests(unittest.TestCase):
    def test_database_url_pins_local_address_and_rejects_overrides(self):
        with patch.dict(os.environ, {"PARSER_TEST_DATABASE_URL":
                                     "postgresql://localhost/kib_parser_test"}):
            dsn = test_database_url()
        parts = conninfo_to_dict(dsn)
        self.assertEqual(parts["host"], "localhost")
        self.assertEqual(parts["hostaddr"], "127.0.0.1")

    def test_database_url_rejects_remote_address_service_and_multihost(self):
        rejected = [
            "host=localhost hostaddr=203.0.113.2 dbname=kib_parser_test",
            "host=localhost service=external dbname=kib_parser_test",
            "host=localhost,127.0.0.1 dbname=kib_parser_test",
        ]
        for value in rejected:
            with self.subTest(value=value), patch.dict(os.environ,
                    {"PARSER_TEST_DATABASE_URL": value}):
                with self.assertRaises(RuntimeError):
                    test_database_url()

def test_database_url():
    dsn = os.environ.get("PARSER_TEST_DATABASE_URL")
    if not dsn:
        return None
    parts = conninfo_to_dict(dsn)
    if parts.get("dbname") != "kib_parser_test":
        raise RuntimeError("PARSER_TEST_DATABASE_URL must select kib_parser_test")
    host = parts.get("host")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("PARSER_TEST_DATABASE_URL must use an explicit loopback host")
    if parts.get("service") or parts.get("hostaddr") not in (None, "127.0.0.1", "::1"):
        raise RuntimeError("PARSER_TEST_DATABASE_URL must not override its loopback target")
    # Pin localhost to a loopback address before any migration or cleanup runs.
    return make_conninfo(dsn, hostaddr="::1" if host == "::1" else "127.0.0.1")

class DatabaseTestCase(unittest.TestCase):
    owned_ids, lock = set(), threading.Lock()

    @classmethod
    def setUpClass(cls):
        cls.owned_ids = set()
        cls.dsn = test_database_url()
        if not cls.dsn:
            raise unittest.SkipTest("PARSER_TEST_DATABASE_URL is not set")
        apply_migrations(
            cls.dsn, connect_timeout=3, statement_timeout_ms=3000
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "dsn", None) and cls.owned_ids:
            with psycopg.connect(cls.dsn) as connection:
                connection.execute("DELETE FROM parser.jobs WHERE job_id = ANY(%s)",
                                   (list(cls.owned_ids),))

    def payload(self, **changes):
        payload = {**PAYLOAD, "job_id": f"test-{uuid.uuid4()}", **changes}
        with self.lock:
            self.owned_ids.add(payload["job_id"])
        return payload

class JobRepositoryTests(DatabaseTestCase):
    def setUp(self):
        self.repository = JobRepository(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000
        )

    def test_submit_duplicate_ignores_json_key_order(self):
        payload = self.payload()
        first = self.repository.submit(payload)
        repeated = self.repository.submit(dict(reversed(list(payload.items()))))
        self.assertEqual(repeated, first)
        self.assertEqual(first["request"], payload)
        self.assertEqual(first["status"], "queued")
        self.assertIsNotNone(first["created_at"])
        self.assertIsNotNone(first["updated_at"])
        self.assertEqual(self.repository.get(payload["job_id"]), first)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.repository.get(f"test-{uuid.uuid4()}"))

    def test_conflict_rolls_back_before_next_submit(self):
        payload = self.payload()
        self.repository.submit(payload)
        with self.assertRaises(JobConflict):
            self.repository.submit({**payload, "requested_level": "metadata"})
        following = self.payload()
        self.assertEqual(self.repository.submit(following)["request"], following)

    def test_concurrent_duplicates_create_one_row(self):
        payload, barrier = self.payload(), threading.Barrier(6)

        def submit(_):
            barrier.wait()
            return self.repository.submit(dict(payload))

        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(submit, range(6)))
        self.assertTrue(all(row == rows[0] for row in rows))
        with psycopg.connect(self.dsn) as connection:
            count = connection.execute(
                "SELECT count(*) FROM parser.jobs WHERE job_id = %s", (payload["job_id"],)
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_new_repository_reads_persisted_job(self):
        payload = self.payload()
        submitted = self.repository.submit(payload)
        other_repository = JobRepository(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000
        )
        self.assertEqual(other_repository.get(payload["job_id"]), submitted)

    def test_repository_requires_positive_integer_timeouts(self):
        for connect_timeout, statement_timeout_ms in (
            (True, 1), (1.5, 1), (0, 1), (1, False), (1, 1.5), (1, 0)
        ):
            with self.subTest(connect_timeout=connect_timeout,
                              statement_timeout_ms=statement_timeout_ms):
                with self.assertRaises(ValueError):
                    JobRepository(
                        "postgresql://unused",
                        connect_timeout=connect_timeout,
                        statement_timeout_ms=statement_timeout_ms,
                    )

    def test_connection_failure_becomes_repository_unavailable(self):
        repository = JobRepository(
            "postgresql://x:x@127.0.0.1:1/kib_parser_test",
            connect_timeout=1,
            statement_timeout_ms=100,
        )
        with self.assertRaises(RepositoryUnavailable):
            repository.get("test-unavailable")

    def test_reapplying_migrations_is_empty_and_preserves_queued_job(self):
        payload = self.payload()
        submitted = self.repository.submit(payload)

        applied = apply_migrations(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000
        )

        self.assertEqual(applied, [])
        self.assertEqual(self.repository.get(payload["job_id"]), submitted)

if __name__ == "__main__":
    unittest.main()
