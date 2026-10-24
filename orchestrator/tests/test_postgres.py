import os
import threading
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

try:
    import psycopg
except ImportError:  # pragma: no cover - dependency is optional for offline unit tests
    psycopg = None

from orchestrator.analytics.store import PostgresStore, RevisionConflict, ScopeRequired
from orchestrator.models import digest

try:
    from orchestrator.analytics.migrate import apply_migrations
except ImportError:  # pragma: no cover - psycopg is optional for offline unit tests
    apply_migrations = None


DSN = os.environ.get('ANALYTICS_TEST_DATABASE_URL')


@unittest.skipUnless(DSN and psycopg and apply_migrations,
                     'set ANALYTICS_TEST_DATABASE_URL and install psycopg for temporary PostgreSQL+pgvector tests')
class PostgresStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DSN, connect_timeout=3, statement_timeout_ms=5000)
        with psycopg.connect(DSN) as connection:
            installed = connection.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')").fetchone()[0]
        if not installed:
            raise RuntimeError('temporary test database must have pgvector installed')

    def setUp(self):
        self.store = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=5000)
        self.suffix = uuid4().hex

    def tearDown(self):
        self.store.close()

    def test_versioning_scope_and_idempotency(self):
        key = f'event-{self.suffix}'
        first = self.store.put('event', key, {'summary': 'first'})
        replay = self.store.put('event', key, {'summary': 'first'})
        second = self.store.put('event', key, {'summary': 'second'}, expected_version=1)
        self.assertEqual((first.version, replay.version, second.version), (1, 1, 2))
        self.assertEqual([row.version for row in self.store.history('event', key)], [1, 2])
        with self.assertRaises(RevisionConflict):
            self.store.put('event', key, {'summary': 'stale'}, expected_version=1)

        with self.assertRaises(ScopeRequired):
            self.store.put('company_fact', f'fact-{self.suffix}', {'text': 'private'})
        private_key = f'fact-{self.suffix}'
        tenant_id, company_id = f'tenant-{self.suffix}', f'company-{self.suffix}'
        self.store.put('company_fact', private_key, {'text': 'private'}, tenant_id=tenant_id, company_id=company_id)
        self.assertIsNone(self.store.get('company_fact', private_key, tenant_id='tenant-other', company_id=company_id))

    def test_concurrent_expected_version_allows_only_one_update(self):
        key = f'event-race-{self.suffix}'
        self.store.put('event', key, {'summary': 'initial'})

        def update(value):
            try:
                return self.store.put('event', key, {'summary': value}, expected_version=1).version
            except RevisionConflict:
                return 'conflict'

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(update, ('first', 'second')))
        self.assertCountEqual(outcomes, [2, 'conflict'])
        self.assertEqual([record.version for record in self.store.history('event', key)], [1, 2])

    def test_outer_transaction_rolls_back_all_nested_store_writes(self):
        key = f'event-rollback-{self.suffix}'
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.put('event', key, {'summary': 'temporary'})
                self.store.index_text('event', key, 'temporary event')
                raise RuntimeError('rollback')
        self.assertIsNone(self.store.get('event', key))
        self.assertEqual(self.store.search('temporary', tenant_id='t', company_id='c'), [])

    def test_advisory_lock_is_reentrant_and_blocks_another_session(self):
        lock_key = f'company:{self.suffix}'
        entered = threading.Event()

        def acquire():
            entered.set()
            with self.store.lock(lock_key):
                return True

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with self.store.lock(lock_key):
                with self.store.lock(lock_key):
                    pass
                future = executor.submit(acquire)
                self.assertTrue(entered.wait(1))
                self.assertFalse(future.done())
            self.assertTrue(future.result(timeout=2))
        finally:
            executor.shutdown(wait=True)

    def test_search_combines_russian_fts_and_pgvector_without_cross_tenant_results(self):
        key = f'fact-{self.suffix}'
        tenant_id, company_id = f'tenant-{self.suffix}', f'company-{self.suffix}'
        self.store.index_text('company_fact', key, 'Ключевой поставщик сырья', tenant_id=tenant_id,
                              company_id=company_id, vector=[1.0, 0.0], model_id='fixture',
                              model_version='1', text_version='1')
        self.store.index_text('company_fact', key, 'Ключевой поставщик сырья', tenant_id='tenant-other',
                              company_id=company_id, vector=[1.0, 0.0], model_id='fixture',
                              model_version='1', text_version='1')

        results = self.store.search('поставщик', tenant_id=tenant_id, company_id=company_id,
                                    query_vector=[1.0, 0.0], model_id='fixture', model_version='1')
        self.assertEqual([(row['kind'], row['key']) for row in results], [('company_fact', key)])
        self.assertEqual(results[0]['channel'], 'fts+vector')
        with self.assertRaises(ValueError):
            self.store.search('поставщик', tenant_id=tenant_id, company_id=company_id,
                              query_vector=[1.0, 0.0, 0.0], model_id='fixture', model_version='1')
        with self.assertRaises(ValueError):
            self.store.index_text('company_fact', f'bad-{self.suffix}', 'bad dimension', tenant_id=tenant_id,
                                  company_id=company_id, vector=[1.0, 0.0, 0.0], model_id='fixture',
                                  model_version='1', text_version='1')
        with self.assertRaises(ValueError):
            self.store.index_text('company_fact', f'nan-{self.suffix}', 'bad value', tenant_id=tenant_id,
                                  company_id=company_id, vector=[float('nan')], model_id='other',
                                  model_version='1', text_version='1')

    def test_budget_cache_and_usage_metrics_persist(self):
        account, now = f'account-{self.suffix}', time.time()
        self.store.cache_put(self.suffix, {'status': 'ready'})
        self.assertEqual(self.store.cache_get(self.suffix), {'status': 'ready'})
        self.store.block_budget(account, now + 120)
        self.assertAlmostEqual(self.store.blocked_until(account), now + 120, delta=0.001)
        first_call_id, retry_at = self.store.reserve_call(account, 'stage', 'model', 1, now)
        self.assertIsNotNone(first_call_id)
        self.assertEqual(retry_at, 0)
        call_id, retry_at = self.store.reserve_call(account, 'stage', 'model', 1, now + 1)
        self.assertIsNone(call_id)
        self.assertAlmostEqual(retry_at, now + 60, delta=0.00001)
        self.store.record_call(first_call_id, 'ok')
        metric = next(row for row in self.store.metrics()
                      if row['model'] == 'model' and row['status'] == 'ok')
        self.assertGreaterEqual(metric['calls'], 1)
        self.assertIsNone(metric['estimated_cost'])

    def test_operational_cleanup_keeps_business_records_and_only_prunes_eligible_checkpoints(self):
        from langgraph.checkpoint.postgres import PostgresSaver

        now = datetime.now(timezone.utc)
        cutoff = datetime(2000, 1, 2, tzinfo=timezone.utc)
        cache_old, cache_fresh = f'old-{self.suffix}', f'fresh-{self.suffix}'
        self.store.cache_put(cache_old, {'value': 'old'})
        self.store.cache_put(cache_fresh, {'value': 'fresh'})
        expired_account, active_account = f'expired-{self.suffix}', f'active-{self.suffix}'
        self.store.block_budget(expired_account, now.timestamp() - 120)
        self.store.block_budget(active_account, now.timestamp() + 120)
        call_id, _ = self.store.reserve_call(f'calls-{self.suffix}', 'stage', 'model', 10, now.timestamp())
        active_call, _ = self.store.reserve_call(f'active-calls-{self.suffix}', 'stage', 'model', 10,
                                                 now.timestamp())
        self.store.record_call(call_id, 'ok')

        run_id, running_id = f'old-run-{self.suffix}', f'running-{self.suffix}'
        scope = dict(tenant_id=f'tenant-{self.suffix}', company_id=f'company-{self.suffix}')
        self.store.put('run', run_id, {'status': 'completed'}, **scope)
        self.store.put('run', running_id, {'status': 'running'}, **scope)
        self.store.put('fact', f'fact-{self.suffix}', {'text': 'must survive'}, **scope)
        thread_ids = [f'impact:{run_id}', f'impact:{running_id}', f'manual:{run_id}']
        configs = []
        with PostgresSaver.from_conn_string(DSN) as saver:
            saver.setup()
            for thread_id in thread_ids:
                config = {'configurable': {'thread_id': thread_id, 'checkpoint_ns': ''}}
                checkpoint = {'v': 1, 'id': uuid4().hex, 'ts': now.isoformat(),
                              'channel_values': {}, 'channel_versions': {}, 'versions_seen': {}}
                configs.append(saver.put(config, checkpoint, {}, {}))
            self.assertTrue(all(saver.get_tuple(config) for config in configs))

        with psycopg.connect(DSN) as connection:
            connection.execute('UPDATE analytics.cache SET updated_at=%s WHERE cache_key=%s',
                               (cutoff - timedelta(days=1), cache_old))
            connection.execute('UPDATE analytics.cache SET updated_at=%s WHERE cache_key=%s',
                               (cutoff + timedelta(seconds=1), cache_fresh))
            connection.execute('UPDATE analytics.calls SET finished_at=%s WHERE id=%s',
                               (cutoff - timedelta(days=1), call_id))
            connection.execute('UPDATE analytics.calls SET finished_at=NULL WHERE id=%s', (active_call,))
            connection.execute('UPDATE analytics.budgets SET blocked_until=%s WHERE account=%s',
                               (cutoff - timedelta(days=1), expired_account))
            connection.execute('''UPDATE analytics.records SET created_at=%s
                WHERE kind='run' AND tenant_id=%s AND company_id=%s AND record_key=%s''',
                               (cutoff - timedelta(days=1), scope['tenant_id'], scope['company_id'], run_id))

        counts = self.store.cleanup_operational(cutoff)

        self.assertEqual(counts['cache'], 1)
        self.assertEqual(counts['calls'], 1)
        self.assertEqual(counts['budgets'], 1)
        self.assertGreaterEqual(counts['checkpoints'], 1)
        self.assertIsNone(self.store.cache_get(cache_old))
        self.assertEqual(self.store.cache_get(cache_fresh), {'value': 'fresh'})
        self.assertGreater(self.store.blocked_until(active_account), cutoff.timestamp())
        self.assertEqual(self.store.get('fact', f'fact-{self.suffix}', **scope).payload['text'],
                         'must survive')
        with PostgresSaver.from_conn_string(DSN) as saver:
            self.assertIsNone(saver.get_tuple(configs[0]))
            self.assertIsNotNone(saver.get_tuple(configs[1]))
            self.assertIsNotNone(saver.get_tuple(configs[2]))

    def test_cleanup_rechecks_run_after_waiting_for_company_lock(self):
        from langgraph.checkpoint.postgres import PostgresSaver

        cutoff = datetime(2000, 1, 2, tzinfo=timezone.utc)
        scope = dict(tenant_id=f'tenant-race-{self.suffix}', company_id=f'company-race-{self.suffix}')
        run_id = f'race-run-{self.suffix}'
        record = self.store.put('run', run_id, {'status': 'completed'}, **scope)
        with psycopg.connect(DSN) as connection:
            connection.execute('''UPDATE analytics.records SET created_at=%s
                WHERE kind='run' AND tenant_id=%s AND company_id=%s AND record_key=%s''',
                               (cutoff - timedelta(days=1), scope['tenant_id'], scope['company_id'], run_id))
        thread_id = 'impact:' + run_id
        config = {'configurable': {'thread_id': thread_id, 'checkpoint_ns': ''}}
        checkpoint = {'v': 1, 'id': uuid4().hex, 'ts': datetime.now(timezone.utc).isoformat(),
                      'channel_values': {}, 'channel_versions': {}, 'versions_seen': {}}
        with PostgresSaver.from_conn_string(DSN) as saver:
            saver.setup()
            checkpoint_config = saver.put(config, checkpoint, {}, {})

        lock_key = 'company:' + digest(scope)
        original_lock = self.store.lock
        cleanup_waiting = threading.Event()

        @contextmanager
        def observed_lock(key):
            if key == lock_key:
                cleanup_waiting.set()
            with original_lock(key):
                yield

        self.store.lock = observed_lock
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                with original_lock(lock_key):
                    cleanup = executor.submit(self.store.cleanup_operational, cutoff)
                    self.assertTrue(cleanup_waiting.wait(2), 'cleanup did not wait on the company lock')
                    self.store.put('run', run_id, {'status': 'running'}, **scope,
                                   expected_version=record.version)
                cleanup.result(timeout=2)
        finally:
            self.store.lock = original_lock

        cleanup.result(timeout=2)
        with PostgresSaver.from_conn_string(DSN) as saver:
            self.assertIsNotNone(saver.get_tuple(checkpoint_config))

    def test_cleanup_can_skip_checkpoint_tables(self):
        cutoff = datetime.now(timezone.utc)
        result = self.store.cleanup_operational(cutoff, checkpoints=False)
        self.assertEqual(result['checkpoints'], 0)


if __name__ == '__main__':
    unittest.main()
