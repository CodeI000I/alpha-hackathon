import threading
import unittest

import psycopg

from parser_service.repository import JobRepository
from parser_service.tests.test_jobs import DatabaseTestCase
from parser_service.worker import run_once


class WorkerTests(DatabaseTestCase):
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

    def test_advisory_lock_allows_only_one_worker_through_finish(self):
        first_payload = self.payload()
        second_payload = self.payload()
        self.repository.submit(first_payload)
        self.repository.submit(second_payload)
        handler_started = threading.Event()
        release_handler = threading.Event()
        outcome = {}

        def blocking_handler(request):
            handler_started.set()
            if not release_handler.wait(timeout=5):
                raise AssertionError("test did not release handler")
            return {"job_id": request["job_id"], "result_status": "complete", "items": []}

        def first_worker():
            outcome["row"] = run_once(
                self.repository,
                blocking_handler,
                lease_seconds=90,
                max_attempts=2,
                max_items=3,
            )

        thread = threading.Thread(target=first_worker)
        try:
            thread.start()
            self.assertTrue(handler_started.wait(timeout=5))
            blocked = run_once(
                JobRepository(self.dsn, connect_timeout=3, statement_timeout_ms=3000),
                lambda _request: self.fail("second handler must not run"),
                lease_seconds=90,
                max_attempts=2,
                max_items=3,
            )
            self.assertIsNone(blocked)
        finally:
            release_handler.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["row"]["status"], "succeeded")
        statuses = {
            self.repository.get(first_payload["job_id"])["status"],
            self.repository.get(second_payload["job_id"])["status"],
        }
        self.assertEqual(statuses, {"queued", "succeeded"})


if __name__ == "__main__":
    unittest.main()
