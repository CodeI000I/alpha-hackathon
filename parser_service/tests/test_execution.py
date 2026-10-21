import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from parser_service.executor import ProcessingError, execute_once
from parser_service.repository import JobRepository, LeaseLost, RepositoryUnavailable
from parser_service.tests.test_jobs import DatabaseTestCase


def full_item(external_id="fixture-1"):
    return {
        "external_id": external_id,
        "url": "https://www.cbr.ru/press/PR/?file=fixture.htm",
        "title": "Явно тестовый материал",
        "description": None,
        "published_at": "2026-10-21T12:00:00+03:00",
        "published_date": None,
        "date_precision": "second",
        "published_at_source": "rss_pubDate",
        "content_text": "Искусственный текст проверки.",
        "content_status": "full",
        "extraction_method": "test_fixture",
        "fetched_at": "2026-10-21T12:00:00Z",
        "provenance": {
            "source_id": "cbr_press",
            "discovery_method": "rss",
            "discovery_url": "https://www.cbr.ru/rss/RssPress",
            "policy_version": "cbr-v1",
        },
        "attachments": [],
        "incomplete_fields": [],
        "error": None,
    }


def handler_result(job_id, *, items=None, status="complete"):
    return {
        "job_id": job_id,
        "result_status": status,
        "items": [full_item()] if items is None else items,
    }


class ExecutionTests(DatabaseTestCase):
    def setUp(self):
        self.repository = JobRepository(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000
        )
        self.test_ids = set()

    def tearDown(self):
        if self.test_ids:
            with psycopg.connect(self.dsn) as connection:
                connection.execute(
                    "DELETE FROM parser.jobs WHERE job_id = ANY(%s)",
                    (list(self.test_ids),),
                )

    def payload(self, **changes):
        payload = super().payload(**changes)
        self.test_ids.add(payload["job_id"])
        return payload

    def expire(self, job_id):
        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                "UPDATE parser.jobs SET lease_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE job_id = %s",
                (job_id,),
            )

    def test_concurrent_claims_give_one_worker_the_job(self):
        payload = self.payload()
        self.repository.submit(payload)
        barrier = threading.Barrier(2)

        def claim(_):
            barrier.wait()
            repository = JobRepository(
                self.dsn, connect_timeout=3, statement_timeout_ms=3000
            )
            return repository.claim(lease_seconds=30, max_attempts=3)

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, range(2)))

        rows = [row for row in claims if row is not None]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["job_id"], row["status"], row["attempt"]),
                         (payload["job_id"], "running", 1))
        self.assertIsNotNone(row["lease_token"])
        self.assertIsNotNone(row["lease_expires_at"])
        self.assertIsNotNone(row["started_at"])

    def test_expired_lease_is_fenced_and_reclaimed_with_new_token(self):
        payload = self.payload()
        self.repository.submit(payload)
        first = self.repository.claim(lease_seconds=30, max_attempts=3)
        self.expire(payload["job_id"])

        with self.assertRaises(LeaseLost):
            self.repository.finish(
                payload["job_id"], first["lease_token"], result=handler_result(payload["job_id"])
            )
        second = self.repository.claim(lease_seconds=30, max_attempts=3)
        self.assertNotEqual(second["lease_token"], first["lease_token"])
        self.assertEqual(second["attempt"], 2)
        with self.assertRaises(LeaseLost):
            self.repository.finish(
                payload["job_id"], first["lease_token"], result=handler_result(payload["job_id"])
            )

        result = handler_result(payload["job_id"])
        finished = self.repository.finish(
            payload["job_id"], second["lease_token"], result=result
        )
        self.assertEqual((finished["status"], finished["result"]), ("succeeded", result))
        self.assertIsNone(finished["lease_token"])
        self.assertIsNotNone(finished["finished_at"])
        self.assertEqual(self.repository.submit(payload), finished)

    def test_claim_marks_exhausted_job_failed_without_new_lease(self):
        payload = self.payload()
        self.repository.submit(payload)
        claimed = self.repository.claim(lease_seconds=30, max_attempts=1)
        self.expire(payload["job_id"])

        exhausted = self.repository.claim(lease_seconds=30, max_attempts=1)

        self.assertEqual(exhausted["status"], "failed")
        self.assertEqual(exhausted["attempt"], claimed["attempt"])
        self.assertEqual(exhausted["error"]["code"], "ATTEMPTS_EXHAUSTED")
        self.assertIs(exhausted["error"]["retryable"], False)
        self.assertIsNone(exhausted["lease_token"])

    def test_finish_requires_exactly_one_outcome_and_terminal_is_fenced(self):
        payload = self.payload()
        self.repository.submit(payload)
        claimed = self.repository.claim(lease_seconds=30, max_attempts=3)
        for kwargs in ({}, {"result": {}, "error": {}}):
            with self.assertRaises(ValueError):
                self.repository.finish(payload["job_id"], claimed["lease_token"], **kwargs)
        self.repository.finish(
            payload["job_id"], claimed["lease_token"],
            error={"code": "FEED_INVALID", "message": "Feed is invalid.", "retryable": False},
        )
        with self.assertRaises(LeaseLost):
            self.repository.finish(
                payload["job_id"], claimed["lease_token"], result=handler_result(payload["job_id"])
            )

    def test_execute_once_persists_valid_complete_result(self):
        payload = self.payload()
        self.repository.submit(payload)

        row = execute_once(
            self.repository,
            lambda request: handler_result(request["job_id"]),
            lease_seconds=30,
            max_attempts=3,
            max_items=10,
        )

        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["result"]["result_status"], "complete")
        self.assertEqual(self.repository.get(payload["job_id"]), row)

    def test_execute_once_preserves_partial_and_truncates_items(self):
        payload = self.payload()
        self.repository.submit(payload)
        items = [full_item("fixture-1"), full_item("fixture-2")]

        row = execute_once(
            self.repository,
            lambda request: handler_result(request["job_id"], items=items, status="partial"),
            lease_seconds=30,
            max_attempts=3,
            max_items=1,
        )

        self.assertEqual(row["result"]["result_status"], "partial")
        self.assertEqual(len(row["result"]["items"]), 1)
        self.assertEqual(row["result"]["incomplete_fields"], ["items"])

    def test_incomplete_item_makes_complete_batch_partial(self):
        payload = self.payload()
        self.repository.submit(payload)
        item = full_item()
        item.update({
            "published_at": None,
            "date_precision": "unknown",
            "published_at_source": None,
            "incomplete_fields": ["published_at"],
        })

        row = execute_once(
            self.repository,
            lambda request: handler_result(request["job_id"], items=[item]),
            lease_seconds=30,
            max_attempts=3,
            max_items=10,
        )

        self.assertEqual(row["result"]["result_status"], "partial")

    def test_missing_fetched_at_is_preserved_and_marked_incomplete(self):
        payload = self.payload()
        self.repository.submit(payload)
        item = full_item()
        item["fetched_at"] = None

        row = execute_once(
            self.repository,
            lambda request: handler_result(request["job_id"], items=[item]),
            lease_seconds=30,
            max_attempts=3,
            max_items=10,
        )

        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["result"]["result_status"], "partial")
        self.assertIsNone(row["result"]["items"][0]["fetched_at"])
        self.assertIn(
            "fetched_at", row["result"]["items"][0]["incomplete_fields"]
        )

    def test_day_date_attachment_and_error_item_survive_as_partial_result(self):
        payload = self.payload()
        self.repository.submit(payload)
        day_item = full_item()
        day_item.update({
            "published_at": None,
            "published_date": "2026-10-21",
            "date_precision": "day",
            "published_at_source": "html_date",
            "attachments": [
                {"url": "https://www.cbr.ru/files/fixture.pdf", "media_type": "application/pdf"}
            ],
        })
        error_item = full_item("fixture-2")
        error_item.update({
            "published_at": None,
            "date_precision": "unknown",
            "published_at_source": None,
            "content_text": None,
            "content_status": "unavailable",
            "error": {"code": "FETCH_FAILED", "message": "Unavailable.", "retryable": True},
        })

        row = execute_once(
            self.repository,
            lambda request: handler_result(request["job_id"], items=[day_item, error_item]),
            lease_seconds=30,
            max_attempts=3,
            max_items=10,
        )

        result = row["result"]
        self.assertEqual(result["result_status"], "partial")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["published_date"], "2026-10-21")
        self.assertIsNone(result["items"][0]["published_at"])
        self.assertEqual(result["items"][0]["attachments"][0]["media_type"], "application/pdf")
        self.assertEqual(result["items"][1]["error"]["code"], "FETCH_FAILED")

    def test_safe_processing_and_unknown_errors_are_persisted(self):
        cases = [
            (ProcessingError("FEED_UNAVAILABLE"), "FEED_UNAVAILABLE", True),
            (RuntimeError("secret-value"), "PROCESSING_FAILED", False),
        ]
        for exception, code, retryable in cases:
            with self.subTest(code=code):
                payload = self.payload()
                self.repository.submit(payload)

                def fail(_request, error=exception):
                    raise error

                row = execute_once(
                    self.repository, fail, lease_seconds=30, max_attempts=3, max_items=10
                )
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["error"]["code"], code)
                self.assertIs(row["error"]["retryable"], retryable)
                self.assertNotIn("secret-value", str(row["error"]))

    def test_invalid_handler_result_is_stored_as_safe_failure(self):
        for make_invalid in (
            lambda payload: handler_result("another-job"),
            lambda payload: handler_result(
                payload["job_id"],
                items=[{**full_item(), "published_at": "2026-10-21T12:00:00"}],
            ),
            lambda payload: handler_result(
                payload["job_id"],
                items=[{
                    **full_item(),
                    "provenance": {**full_item()["provenance"], "policy_version": "other-v1"},
                }],
            ),
        ):
            payload = self.payload()
            self.repository.submit(payload)
            row = execute_once(
                self.repository, lambda _request: make_invalid(payload),
                lease_seconds=30, max_attempts=3, max_items=10,
            )
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["error"]["code"], "INVALID_RESULT")

    def test_finish_commit_failure_rolls_back_and_closes_connection(self):
        payload = self.payload()
        self.repository.submit(payload)
        claimed = self.repository.claim(lease_seconds=30, max_attempts=3)
        suffix = payload["job_id"].replace("-", "_")
        function = f"fail_finish_{suffix}"
        trigger = f"fail_finish_trigger_{suffix}"
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("""
                CREATE FUNCTION parser.{}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.job_id = {} THEN RAISE EXCEPTION 'forced finish failure'; END IF;
                    RETURN NEW;
                END $$
            """).format(sql.Identifier(function), sql.Literal(payload["job_id"])))
            connection.execute(sql.SQL("""
                CREATE CONSTRAINT TRIGGER {} AFTER UPDATE ON parser.jobs
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION parser.{}()
            """).format(sql.Identifier(trigger), sql.Identifier(function)))
        try:
            original_connect = psycopg.connect
            opened_connections = []

            def observe_connection(*args, **kwargs):
                connection = original_connect(*args, **kwargs)
                opened_connections.append(connection)
                return connection

            with patch("parser_service.repository.psycopg.connect",
                       side_effect=observe_connection):
                with self.assertRaises(RepositoryUnavailable):
                    self.repository.finish(
                        payload["job_id"], claimed["lease_token"],
                        result=handler_result(payload["job_id"]),
                    )
            self.assertEqual(len(opened_connections), 1)
            self.assertTrue(opened_connections[0].closed)
            stored = self.repository.get(payload["job_id"])
            self.assertEqual(stored["status"], "running")
            self.assertIsNone(stored["result"])
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP TRIGGER IF EXISTS {} ON parser.jobs")
                                   .format(sql.Identifier(trigger)))
                connection.execute(sql.SQL("DROP FUNCTION IF EXISTS parser.{}()")
                                   .format(sql.Identifier(function)))

    def test_finish_waiting_on_unchanged_row_lock_rechecks_expired_lease(self):
        payload = self.payload()
        self.repository.submit(payload)
        claimed = self.repository.claim(lease_seconds=3, max_attempts=3)
        application_name = f"finish_lock_{payload['job_id']}"
        blocking_repository = JobRepository(
            make_conninfo(self.dsn, application_name=application_name),
            connect_timeout=3,
            statement_timeout_ms=10000,
        )
        locker = psycopg.connect(self.dsn)
        observer = psycopg.connect(self.dsn, autocommit=True)
        outcome = {}

        def finish():
            try:
                outcome["row"] = blocking_repository.finish(
                    payload["job_id"],
                    claimed["lease_token"],
                    result=handler_result(payload["job_id"]),
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=finish)
        try:
            locker.execute(
                "SELECT job_id FROM parser.jobs WHERE job_id = %s FOR UPDATE",
                (payload["job_id"],),
            )
            worker.start()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                wait_event = observer.execute(
                    "SELECT wait_event_type FROM pg_stat_activity "
                    "WHERE application_name = %s AND state = 'active'",
                    (application_name,),
                ).fetchone()
                if wait_event and wait_event[0] == "Lock":
                    break
                time.sleep(0.02)
            else:
                self.fail("finish did not block on the row lock")

            while time.monotonic() < deadline:
                expired = observer.execute(
                    "SELECT clock_timestamp() >= %s", (claimed["lease_expires_at"],)
                ).fetchone()[0]
                if expired:
                    break
                time.sleep(0.02)
            else:
                self.fail("lease did not expire before the deadline")
            locker.rollback()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(outcome.get("error"), LeaseLost)
            self.assertNotIn("row", outcome)
            stored = self.repository.get(payload["job_id"])
            self.assertEqual(stored["status"], "running")
            self.assertIsNone(stored["result"])
        finally:
            locker.rollback()
            locker.close()
            worker.join(timeout=5)
            observer.close()

    def test_exhausted_job_does_not_call_handler(self):
        payload = self.payload()
        self.repository.submit(payload)
        self.repository.claim(lease_seconds=30, max_attempts=1)
        self.expire(payload["job_id"])

        def must_not_run(_request):
            raise AssertionError("handler must not run")

        row = execute_once(
            self.repository, must_not_run,
            lease_seconds=30, max_attempts=1, max_items=10,
        )
        self.assertEqual(row["error"]["code"], "ATTEMPTS_EXHAUSTED")

    def test_keyboard_interrupt_leaves_running_job_reclaimable(self):
        payload = self.payload()
        self.repository.submit(payload)

        def crash(_request):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            execute_once(
                self.repository, crash, lease_seconds=30, max_attempts=3, max_items=10
            )
        running = self.repository.get(payload["job_id"])
        self.assertEqual(running["status"], "running")
        self.expire(payload["job_id"])

        recovered = execute_once(
            self.repository,
            lambda request: handler_result(request["job_id"]),
            lease_seconds=30,
            max_attempts=3,
            max_items=10,
        )
        self.assertEqual((recovered["status"], recovered["attempt"]), ("succeeded", 2))

    def test_execute_once_validates_configuration_before_claim(self):
        class NoClaimRepository:
            def claim(self, **_kwargs):
                raise AssertionError("claim must not run")

        for handler, lease_seconds, max_attempts, max_items in (
            (None, 1, 1, 1),
            (lambda request: request, True, 1, 1),
            (lambda request: request, 1, 0, 1),
            (lambda request: request, 1, 1, 1.5),
        ):
            with self.subTest(handler=handler, lease_seconds=lease_seconds,
                              max_attempts=max_attempts, max_items=max_items):
                with self.assertRaises(ValueError):
                    execute_once(
                        NoClaimRepository(), handler,
                        lease_seconds=lease_seconds,
                        max_attempts=max_attempts,
                        max_items=max_items,
                    )

    def test_repository_failure_and_lost_lease_are_not_rewritten(self):
        class FinishFailureRepository:
            failure = None

            def claim(self, **_kwargs):
                return {"job_id": "job-1", "request": {**self_request},
                        "status": "running", "lease_token": "token"}

            def finish(self, *_args, **_kwargs):
                raise self.failure()

        self_request = {"job_id": "job-1", "source_id": "cbr_press",
                        "policy_version": "cbr-v1"}
        for failure in (RepositoryUnavailable, LeaseLost):
            with self.subTest(failure=failure):
                repository = FinishFailureRepository()
                repository.failure = failure
                with self.assertRaises(failure):
                    execute_once(
                        repository, lambda request: handler_result(request["job_id"]),
                        lease_seconds=30, max_attempts=3, max_items=10,
                    )


if __name__ == "__main__":
    unittest.main()
