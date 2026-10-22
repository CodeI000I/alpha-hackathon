import copy
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from parser_service.api import create_app
from parser_service.executor import execute_once
from parser_service.repository import JobConflict, JobRepository, RepositoryUnavailable
from parser_service.tests.test_execution import full_item, handler_result
from parser_service.tests.test_jobs import DatabaseTestCase, PAYLOAD

class FakeRepository:
    def __init__(self):
        self.rows, self.error, self.calls = {}, None, 0

    def submit(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        old = self.rows.get(request["job_id"])
        if old:
            if old["request"] != request:
                raise JobConflict()
            return old
        now = datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
        row = {"job_id": request["job_id"], "request": copy.deepcopy(request),
               "status": "queued", "created_at": now, "updated_at": now}
        self.rows[request["job_id"]] = row
        return row

    def get(self, job_id):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows.get(job_id)

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.client = TestClient(create_app(repository=self.repo, api_token="test-token",
                                            max_request_bytes=4096))
        self.auth = {"Authorization": "Bearer test-token"}
    def assert_error(self, response, status, code, retryable):
        self.assertEqual(response.status_code, status)
        self.assertEqual(set(response.json()), {"error"})
        error = response.json()["error"]
        self.assertEqual(set(error), {"code", "message", "retryable"})
        self.assertEqual((error["code"], error["retryable"]), (code, retryable))
        self.assertIsInstance(error["message"], str)
        self.assertTrue(error["message"])

    def test_submit_returns_queued_job_urls(self):
        response = self.client.post("/v1/jobs", headers=self.auth, json=PAYLOAD)
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(set(body), {"job_id", "status", "status_url", "result_url",
                                     "created_at", "updated_at"})
        self.assertEqual((body["job_id"], body["status"]), ("job-1", "queued"))
        self.assertEqual(body["status_url"], "/v1/jobs/job-1")
        self.assertEqual(body["result_url"], "/v1/jobs/job-1/result")
        datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))

    def test_get_returns_same_job_shape(self):
        created = self.client.post("/v1/jobs", headers=self.auth, json=PAYLOAD)
        fetched = self.client.get("/v1/jobs/job-1", headers=self.auth)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), created.json())

    def test_result_states_and_unknown_job(self):
        self.repo.submit(PAYLOAD)
        self.assert_error(self.client.get("/v1/jobs/job-1/result", headers=self.auth),
                          409, "RESULT_NOT_READY", True)
        for path in ("/v1/jobs/missing", "/v1/jobs/missing/result"):
            self.assert_error(self.client.get(path, headers=self.auth), 404, "JOB_NOT_FOUND", False)

    def test_auth_precedes_body_parsing_and_repository(self):
        for headers in ({"Content-Type": "application/json"},
                        {"Authorization": "Bearer wrong", "Content-Type": "application/json"}):
            response = self.client.post("/v1/jobs", headers=headers, content=b'{"secret":')
            self.assert_error(response, 401, "UNAUTHORIZED", False)
            self.assertNotIn("secret", response.text)
        self.assertEqual(self.repo.calls, 0)

    def test_invalid_json_payload_and_path_return_contract_error(self):
        invalid = [{k: v for k, v in PAYLOAD.items() if k != "mode"}, {**PAYLOAD, "extra": True},
                   {**PAYLOAD, "mode": "fetch"}, {**PAYLOAD, "source_id": "other"},
                   {**PAYLOAD, "requested_level": "metadata"}, {**PAYLOAD, "job_id": 1},
                   {**PAYLOAD, "policy_version": "bad value"}]
        for payload in invalid:
            self.assert_error(self.client.post("/v1/jobs", headers=self.auth, json=payload),
                              422, "INVALID_REQUEST", False)
        malformed = self.client.post("/v1/jobs", headers={**self.auth,
            "Content-Type": "application/json"}, content=b'{"job_id":')
        self.assert_error(malformed, 422, "INVALID_REQUEST", False)
        self.assert_error(self.client.get("/v1/jobs/bad%20value", headers=self.auth),
                          422, "INVALID_REQUEST", False)

    def test_repository_errors_are_mapped_without_input_reflection(self):
        self.repo.error = JobConflict()
        response = self.client.post("/v1/jobs", headers=self.auth,
                                    json={**PAYLOAD, "policy_version": "secret-policy"})
        self.assert_error(response, 409, "JOB_CONFLICT", False)
        self.assertNotIn("secret-policy", response.text)
        self.repo.error = RepositoryUnavailable()
        self.assert_error(self.client.get("/v1/jobs/job-1", headers=self.auth),
                          503, "STORAGE_UNAVAILABLE", True)

    def test_size_limit_applies_before_parsing_with_and_without_content_length(self):
        for content in (b"x" * 4097, (x for x in (b"x" * 2048, b"y" * 2049))):
            response = self.client.post("/v1/jobs", headers={**self.auth,
                "Content-Type": "application/json"}, content=content)
            self.assert_error(response, 413, "REQUEST_TOO_LARGE", False)
        self.assertEqual(self.repo.calls, 0)

    def test_create_app_rejects_empty_token_and_nonpositive_limit(self):
        for token, limit in (("", 1), ("test-token", 0), ("test-token", -1)):
            with self.assertRaises(ValueError):
                create_app(repository=self.repo, api_token=token, max_request_bytes=limit)

    def test_environment_factory_requires_every_setting_and_is_connection_lazy(self):
        settings = {"PARSER_API_TOKEN": "test-token", "PARSER_MAX_REQUEST_BYTES": "4096",
                    "PARSER_DATABASE_URL": "postgresql://x:x@127.0.0.1:1/kib_parser_test",
                    "PARSER_CONNECT_TIMEOUT_SECONDS": "1", "PARSER_STATEMENT_TIMEOUT_MS": "100"}
        with patch.dict(os.environ, settings, clear=True):
            self.assertIsNotNone(create_app())
        for missing in settings:
            with self.subTest(missing=missing), patch.dict(
                os.environ, {k: v for k, v in settings.items() if k != missing}, clear=True
            ):
                with self.assertRaises(ValueError):
                    create_app()
        for name, value in (("PARSER_API_TOKEN", "bad token"),
                            ("PARSER_MAX_REQUEST_BYTES", "nope"),
                            ("PARSER_CONNECT_TIMEOUT_SECONDS", "0"),
                            ("PARSER_STATEMENT_TIMEOUT_MS", "1.5")):
            with self.subTest(name=name), patch.dict(os.environ,
                    {**settings, name: value}, clear=True):
                with self.assertRaises(ValueError):
                    create_app()

    def test_real_unavailable_repository_returns_503(self):
        repository = JobRepository("postgresql://x:x@127.0.0.1:1/kib_parser_test",
                                   connect_timeout=1, statement_timeout_ms=100)
        client = TestClient(create_app(repository=repository, api_token="test-token",
                                       max_request_bytes=4096))
        self.assert_error(client.post("/v1/jobs", headers=self.auth, json=PAYLOAD),
                          503, "STORAGE_UNAVAILABLE", True)

class ApiDatabaseTests(DatabaseTestCase):
    def tearDown(self):
        if self.owned_ids:
            with psycopg.connect(self.dsn) as connection:
                connection.execute(
                    "DELETE FROM parser.jobs WHERE job_id = ANY(%s)",
                    (list(self.owned_ids),),
                )
            self.owned_ids.clear()

    def repository(self):
        return JobRepository(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000
        )

    def client(self, repository=None):
        return TestClient(
            create_app(
                repository=repository or self.repository(),
                api_token="test-token",
                max_request_bytes=4096,
            )
        )

    def test_post_then_new_app_get_uses_persisted_job(self):
        payload = self.payload()
        kwargs = {"api_token": "test-token", "max_request_bytes": 4096}
        created = TestClient(create_app(repository=JobRepository(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000), **kwargs)).post(
            "/v1/jobs", headers={"Authorization": "Bearer test-token"}, json=payload)
        self.assertEqual(created.status_code, 202)
        fetched = TestClient(create_app(repository=JobRepository(
            self.dsn, connect_timeout=3, statement_timeout_ms=3000), **kwargs)).get(
            f"/v1/jobs/{payload['job_id']}", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), created.json())

    def test_commit_failure_returns_503_and_rolls_back_insert(self):
        payload = self.payload()
        suffix = payload["job_id"].replace("-", "_")
        function, trigger = f"fail_commit_{suffix}", f"fail_commit_trigger_{suffix}"
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("""
                CREATE FUNCTION parser.{}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.job_id = {} THEN RAISE EXCEPTION 'forced commit failure'; END IF;
                    RETURN NEW;
                END $$
            """).format(sql.Identifier(function), sql.Literal(payload["job_id"])))
            connection.execute(sql.SQL("""
                CREATE CONSTRAINT TRIGGER {} AFTER INSERT ON parser.jobs
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION parser.{}()
            """).format(sql.Identifier(trigger), sql.Identifier(function)))
        try:
            repository = JobRepository(self.dsn, connect_timeout=3,
                                       statement_timeout_ms=3000)
            client = TestClient(create_app(repository=repository, api_token="test-token",
                                           max_request_bytes=4096))
            original_connect = psycopg.connect
            opened_connections = []

            def observe_connection(*args, **kwargs):
                connection = original_connect(*args, **kwargs)
                opened_connections.append(connection)
                return connection

            with patch(
                "parser_service.repository.psycopg.connect",
                side_effect=observe_connection,
            ):
                response = client.post(
                    "/v1/jobs",
                    headers={"Authorization": "Bearer test-token"},
                    json=payload,
                )
            ApiTests.assert_error(self, response, 503, "STORAGE_UNAVAILABLE", True)
            self.assertEqual(len(opened_connections), 1)
            self.assertTrue(opened_connections[0].closed)
            with psycopg.connect(self.dsn) as connection:
                count = connection.execute("SELECT count(*) FROM parser.jobs WHERE job_id = %s",
                                           (payload["job_id"],)).fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP TRIGGER IF EXISTS {} ON parser.jobs")
                                   .format(sql.Identifier(trigger)))
                connection.execute(sql.SQL("DROP FUNCTION IF EXISTS parser.{}()")
                                   .format(sql.Identifier(function)))

    def test_running_and_succeeded_result_states_hide_internal_fields(self):
        payload = self.payload()
        repository = self.repository()
        repository.submit(payload)
        claimed = repository.claim(lease_seconds=30, max_attempts=3)
        client = self.client(repository)

        running = client.get(
            f"/v1/jobs/{payload['job_id']}", headers={"Authorization": "Bearer test-token"}
        )
        self.assertEqual(running.status_code, 200)
        self.assertEqual(running.json()["status"], "running")
        self.assertNotIn("lease_token", running.json())
        self.assertNotIn("request", running.json())
        ApiTests.assert_error(
            self,
            client.get(
                f"/v1/jobs/{payload['job_id']}/result",
                headers={"Authorization": "Bearer test-token"},
            ),
            409,
            "RESULT_NOT_READY",
            True,
        )

        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                "UPDATE parser.jobs SET lease_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE job_id = %s",
                (payload["job_id"],),
            )
        executed = execute_once(
            repository,
            lambda request: handler_result(
                request["job_id"], items=[full_item()]
            ),
            lease_seconds=30,
            max_attempts=3,
            max_items=10,
        )
        self.assertEqual(executed["status"], "succeeded")
        response = client.get(
            f"/v1/jobs/{payload['job_id']}/result",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["external_id"], "fixture-1")

        repeated = client.post("/v1/jobs", headers={"Authorization": "Bearer test-token"},
                               json=payload)
        self.assertEqual((repeated.status_code, repeated.json()["status"]), (202, "succeeded"))

    def test_failed_job_exposes_only_safe_error(self):
        payload = self.payload()
        repository = self.repository()
        repository.submit(payload)
        claimed = repository.claim(lease_seconds=30, max_attempts=3)
        error = {"code": "FEED_INVALID", "message": "Feed is invalid.", "retryable": False}
        repository.finish(payload["job_id"], claimed["lease_token"], error=error)
        client = self.client(repository)

        status = client.get(
            f"/v1/jobs/{payload['job_id']}", headers={"Authorization": "Bearer test-token"}
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "failed")
        self.assertEqual(status.json()["error"], error)
        self.assertNotIn("lease_token", status.json())
        response = client.get(
            f"/v1/jobs/{payload['job_id']}/result",
            headers={"Authorization": "Bearer test-token"},
        )
        ApiTests.assert_error(self, response, 409, "JOB_FAILED", False)
        self.assertEqual(response.json()["error"]["message"], error["message"])

if __name__ == "__main__":
    unittest.main()
