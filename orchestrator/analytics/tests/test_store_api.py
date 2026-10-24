"""Adapter contract tests for scoped bulk history and bounded advisory locks."""

import os
from threading import Event, Thread
from datetime import timedelta
import unittest
from uuid import uuid4
from unittest.mock import patch

from orchestrator.analytics.migrate import apply_migrations
from orchestrator.analytics.models import Scope, utcnow
from orchestrator.analytics.store import MemoryStore, PostgresStore, StoreBusy


DSN = os.environ.get('ANALYTICS_TEST_DATABASE_URL')


class MemoryStoreApiTests(unittest.TestCase):
    def test_histories_returns_scoped_records_by_key_and_version(self):
        store = MemoryStore()
        store.put('document', 'b', {'value': 1}, tenant_id='tenant', company_id='company')
        store.put('document', 'a', {'value': 1}, tenant_id='tenant', company_id='company')
        store.put('document', 'b', {'value': 2}, tenant_id='tenant', company_id='company')
        store.put('document', 'a', {'value': 9}, tenant_id='other', company_id='company')

        histories = store.histories('document', tenant_id='tenant', company_id='company')
        self.assertEqual(list(histories), ['a', 'b'])
        self.assertEqual([record.version for record in histories['a']], [1])
        self.assertEqual([record.version for record in histories['b']], [1, 2])
        self.assertEqual(histories['b'][1].payload, {'value': 2})


@unittest.skipUnless(DSN, 'set ANALYTICS_TEST_DATABASE_URL for PostgreSQL adapter tests')
class PostgresStoreApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DSN, connect_timeout=3, statement_timeout_ms=5000)

    def test_histories_returns_scoped_records_by_key_and_version(self):
        suffix = uuid4().hex
        scope = Scope(tenant_id='histories-' + suffix, company_id='company-' + suffix)
        store = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=5000)
        try:
            store.put('document', 'b', {'value': 1}, **scope.db())
            store.put('document', 'a', {'value': 1}, **scope.db())
            store.put('document', 'b', {'value': 2}, **scope.db())
            store.put('document', 'a', {'value': 9}, tenant_id='other-' + suffix,
                      company_id=scope.company_id)

            histories = store.histories('document', **scope.db())
            self.assertEqual(list(histories), ['a', 'b'])
            self.assertEqual([record.version for record in histories['a']], [1])
            self.assertEqual([record.version for record in histories['b']], [1, 2])
            self.assertEqual(histories['b'][1].payload, {'value': 2})
        finally:
            store.close()

    def test_advisory_lock_timeout_is_reported_as_store_busy(self):
        key = 'store-busy-test:' + uuid4().hex
        locked = Event()
        release = Event()
        owner = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=2000)
        waiter = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=100)
        result = {}

        def hold_lock():
            with owner.lock(key):
                locked.set()
                release.wait(3)

        def wait_for_lock():
            try:
                with waiter.lock(key):
                    result['acquired'] = True
            except Exception as exc:
                result['error'] = exc

        thread = Thread(target=hold_lock)
        thread.start()
        self.assertTrue(locked.wait(3))
        try:
            wait_for_lock()
            self.assertIsInstance(result.get('error'), StoreBusy)
            self.assertNotIn('acquired', result)
        finally:
            release.set()
            thread.join(3)
            owner.close()
            waiter.close()
        self.assertFalse(thread.is_alive())

    def test_cleanup_checkpoint_count_counts_threads_only_once(self):
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver

        suffix = uuid4().hex
        scope = Scope(tenant_id='cleanup-' + suffix, company_id='company-' + suffix)
        run_id = 'run-' + suffix
        cutoff = utcnow() - timedelta(days=1)
        store = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=5000)
        try:
            with PostgresSaver.from_conn_string(DSN) as saver:
                saver.setup()
            store.put('run', run_id, dict(run_id=run_id, event_id='unused', status='completed'), **scope.db())
            with psycopg.connect(DSN) as connection:
                connection.execute('''UPDATE analytics.records SET created_at=%s
                    WHERE kind='run' AND tenant_id=%s AND company_id=%s AND record_key=%s''',
                    (cutoff - timedelta(days=1), scope.tenant_id, scope.company_id, run_id))

            first = store.cleanup_operational(cutoff, checkpoints=True)
            second = store.cleanup_operational(cutoff, checkpoints=True)
            self.assertEqual(first['checkpoints'], 0)
            self.assertEqual(second['checkpoints'], 0)
            self.assertIsNotNone(store.get('run', run_id, **scope.db()))
        finally:
            store.close()

    def test_runtime_migrations_keep_checkpoint_setup_under_cross_process_lock(self):
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from orchestrator.analytics.runtime import AnalyticsSettings, migrate
        setup = PostgresSaver.setup

        def guarded_setup(saver):
            with psycopg.connect(DSN, autocommit=True) as contender:
                acquired = contender.execute("SELECT pg_try_advisory_lock(hashtextextended('alpha.analytics.runtime-migrations', 0))").fetchone()[0]
                self.assertFalse(acquired, 'checkpoint schema migration must be serialized with the other init container')
            return setup(saver)

        with patch.object(PostgresSaver, 'setup', guarded_setup):
            migrate(AnalyticsSettings(database_url=DSN))


if __name__ == '__main__':
    unittest.main()
