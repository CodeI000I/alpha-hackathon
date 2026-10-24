import threading
import unittest
from datetime import datetime, timedelta, timezone

from orchestrator.analytics.store import MemoryStore, RevisionConflict, ScopeRequired


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_put_is_idempotent_and_history_is_immutable(self):
        first = self.store.put('event', 'e1', {'summary': 'initial'})
        replay = self.store.put('event', 'e1', {'summary': 'initial'})
        second = self.store.put('event', 'e1', {'summary': 'updated'}, expected_version=1)

        self.assertEqual(first.version, replay.version)
        self.assertEqual(second.version, 2)
        first.payload['summary'] = 'mutated outside the store'
        self.assertEqual([r.version for r in self.store.history('event', 'e1')], [1, 2])
        self.assertEqual(self.store.get('event', 'e1', version=1).payload['summary'], 'initial')
        self.assertEqual(self.store.get('event', 'e1').payload['summary'], 'updated')
        self.assertEqual([r.version for r in self.store.list('event')], [2])

    def test_expected_version_conflict_does_not_write(self):
        self.store.put('event', 'e1', {'summary': 'initial'})

        with self.assertRaises(RevisionConflict):
            self.store.put('event', 'e1', {'summary': 'lost update'}, expected_version=0)

        self.assertEqual(len(self.store.history('event', 'e1')), 1)

    def test_private_records_fail_closed_and_are_tenant_scoped(self):
        with self.assertRaises(ScopeRequired):
            self.store.put('company_fact', 'f1', {'text': 'secret'})

        self.store.put('company_fact', 'f1', {'text': 'secret'}, tenant_id='t1', company_id='c1')
        self.assertIsNone(self.store.get('company_fact', 'f1', tenant_id='t2', company_id='c1'))
        self.assertEqual(self.store.list('company_fact', tenant_id='t2', company_id='c1'), [])

    def test_concurrent_updates_serialize_revision_assignment(self):
        self.store.put('company_fact', 'f1', {'text': 'initial'}, tenant_id='t', company_id='c')
        outcomes = []

        def update(text):
            try:
                outcomes.append(self.store.put('company_fact', 'f1', {'text': text},
                                               tenant_id='t', company_id='c', expected_version=1).version)
            except RevisionConflict:
                outcomes.append('conflict')

        threads = [threading.Thread(target=update, args=(text,)) for text in ('one', 'two')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, [2, 'conflict'])

    def test_search_uses_only_matching_scope_and_reports_channels(self):
        self.store.index_text('fact', 'f1', 'Ключевой поставщик сырья', tenant_id='t1', company_id='c1',
                              vector=[1.0, 0.0], model_id='m', model_version='v1', text_version='1')
        with self.assertRaises(ValueError):
            self.store.index_text('fact', 'f2', 'Ключевой поставщик', tenant_id='t1', company_id='c1',
                                  vector=[1.0, 0.0, 0.0], model_id='m', model_version='v1', text_version='1')
        with self.assertRaises(ValueError):
            self.store.index_text('fact', 'f3', 'bad vector', tenant_id='t1', company_id='c1',
                                  vector=[float('nan')], model_id='m', model_version='v2', text_version='1')
        self.store.index_text('fact', 'f1', 'Ключевой поставщик сырья', tenant_id='t2', company_id='c1',
                              vector=[1.0, 0.0], model_id='m', model_version='v1', text_version='1')

        results = self.store.search('поставщик', tenant_id='t1', company_id='c1',
                                    query_vector=[1.0, 0.0], model_id='m', model_version='v1')

        self.assertEqual([(row['kind'], row['key']) for row in results], [('fact', 'f1')])
        self.assertEqual(results[0]['channel'], 'fts+vector')
        with self.assertRaises(ValueError):
            self.store.search('поставщик', tenant_id='t1', company_id='c1', query_vector=[1, 0, 0],
                              model_id='m', model_version='v1')

    def test_operational_methods_match_llm_client_contract(self):
        self.assertIsNone(self.store.cache_get('k'))
        self.store.cache_put('k', {'answer': 42})
        self.assertEqual(self.store.cache_get('k'), {'answer': 42})
        self.assertEqual(self.store.blocked_until('account'), 0)
        self.store.block_budget('account', 120.0)
        self.assertEqual(self.store.blocked_until('account'), 120.0)
        call_id, retry_at = self.store.reserve_call('account', 'decision', 'model', 1, 10.0)
        self.assertIsNotNone(call_id)
        self.assertEqual(retry_at, 0)
        self.assertEqual(self.store.reserve_call('account', 'decision', 'model', 1, 11.0),
                         (None, 70.0))
        self.store.record_call(call_id, 'ok')
        metrics = self.store.metrics()
        self.assertEqual(metrics[0]['calls'], 1)
        self.assertIsNone(metrics[0]['estimated_cost'])

    def test_transaction_rolls_back_and_record_payload_cannot_mutate_history(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.put('event', 'rollback', {'summary': 'temporary'})
                raise RuntimeError('rollback')
        self.assertIsNone(self.store.get('event', 'rollback'))

        record = self.store.put('event', 'immutable', {'nested': {'value': 1}})
        record.payload['nested']['value'] = 2
        self.assertEqual(self.store.get('event', 'immutable').payload['nested']['value'], 1)

    def test_cleanup_removes_only_expired_operational_data(self):
        self.store.cache_put('old', {'value': 1})
        self.store.cache_put('fresh', {'value': 2})
        old_call, _ = self.store.reserve_call('old-account', 'stage', 'model', 10, 10.0)
        active_call, _ = self.store.reserve_call('active-account', 'stage', 'model', 10, 10.0)
        self.store.record_call(old_call, 'ok')
        self.store.block_budget('expired', 0.0)
        self.store.block_budget('active', datetime.now(timezone.utc).timestamp() + 3600)

        # Use internal timestamps to make the retention boundary deterministic.
        cutoff = datetime.now(timezone.utc)
        self.store._cache_updated_at['old'] = cutoff - timedelta(days=2)
        self.store._cache_updated_at['fresh'] = cutoff
        self.store._calls[old_call]['finished_at'] = (cutoff - timedelta(days=2)).timestamp()
        self.store._calls[active_call]['finished_at'] = None
        for kind in ('company', 'document', 'fact', 'edge', 'impact', 'issue', 'snapshot',
                     'conversation', 'user_state', 'run', 'candidate_audit'):
            self.store.put(kind, kind + '-1', {'status': 'completed'}, tenant_id='t', company_id='c')

        counts = self.store.cleanup_operational(cutoff)

        self.assertEqual(counts, dict(cache=1, calls=1, budgets=1, checkpoints=0))
        self.assertIsNone(self.store.cache_get('old'))
        self.assertEqual(self.store.cache_get('fresh'), {'value': 2})
        self.assertNotIn(old_call, self.store._calls)
        self.assertIn(active_call, self.store._calls)
        self.assertEqual(self.store.blocked_until('expired'), 0)
        self.assertGreater(self.store.blocked_until('active'), cutoff.timestamp())
        for kind in ('company', 'document', 'fact', 'edge', 'impact', 'issue', 'snapshot',
                     'conversation', 'user_state', 'run', 'candidate_audit'):
            self.assertEqual(self.store.get(kind, kind + '-1', tenant_id='t', company_id='c').version, 1)

    def test_cleanup_requires_aware_cutoff(self):
        with self.assertRaises(ValueError):
            self.store.cleanup_operational(datetime(2025, 1, 1))


if __name__ == '__main__':
    unittest.main()
