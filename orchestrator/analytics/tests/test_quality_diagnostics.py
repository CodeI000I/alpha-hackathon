import json
import unittest
from unittest.mock import patch

from orchestrator.analytics.models import NewsArticle, Scope
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import MemoryStore
from orchestrator.analytics.tests.test_service import FakeModel, NOW, profile
from orchestrator.llm import AIError


class QualityDiagnosticsTests(unittest.TestCase):
    def test_checkpoint_read_error_is_not_attributed_to_synthesis(self):
        store = MemoryStore()
        service = AnalyticsService(store, FakeModel(), clock=lambda: NOW)
        scope = Scope(tenant_id='quality-test', company_id='company')
        service.update_company_profile(scope, profile())
        event_id = service.ingest_news(NewsArticle(news_id='n1', title='supplier',
            content='supplier changes price', published_at=NOW, received_at=NOW))['event_id']
        service.checkpointer = object()
        with patch.object(service.impact_graph, 'get_state', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                service.analyze_event_for_company(scope, event_id)
        self.assertEqual(store.list('run', **scope.db())[0].payload['failed_node'], 'checkpoint')

    def test_run_records_route_coverage_cache_and_node_outcomes(self):
        store = MemoryStore()
        service = AnalyticsService(store, FakeModel(), clock=lambda: NOW)
        scope = Scope(tenant_id='quality-test', company_id='company')
        service.update_company_profile(scope, profile())
        event_id = service.ingest_news(NewsArticle(news_id='n1', title='supplier',
            content='supplier changes price', published_at=NOW, received_at=NOW))['event_id']
        with self.assertLogs('orchestrator.quality', level='INFO') as logs:
            impact = service.analyze_event_for_company(scope, event_id)
        run = store.list('run', **scope.db())[0].payload
        self.assertEqual(run['quality'], dict(route='accepted', evidence_count=2,
                                             causal_claim_count=1, context_truncated=False))
        events = [json.loads(record.getMessage()) for record in logs.records]
        self.assertEqual([event['node'] for event in events], ['retrieve', 'triage', 'assess', 'save'])
        self.assertTrue(all(event['run_id'] == run['run_id'] for event in events))
        with self.assertLogs('orchestrator.quality', level='INFO') as cached_logs:
            cached = service.analyze_event_for_company(scope, event_id)
        self.assertEqual(cached, impact)
        self.assertEqual(len(cached_logs.records), 1)
        self.assertTrue(store.list('run', **scope.db())[0].payload['cached'])

    def test_run_records_failed_node_without_exception_content(self):
        class BrokenModel(FakeModel):
            def structured(self, stage, instruction, context, schema, validate=None):
                if schema.__name__ == 'ImpactAssessment':
                    raise AIError('invalid_response', 'secret source content')
                return super().structured(stage, instruction, context, schema, validate)

        store = MemoryStore()
        service = AnalyticsService(store, BrokenModel(), clock=lambda: NOW)
        scope = Scope(tenant_id='quality-test', company_id='company')
        service.update_company_profile(scope, profile())
        event_id = service.ingest_news(NewsArticle(news_id='n1', title='supplier',
            content='supplier changes price', published_at=NOW, received_at=NOW))['event_id']
        with self.assertLogs('orchestrator.quality', level='INFO') as logs:
            with self.assertRaises(AIError):
                service.analyze_event_for_company(scope, event_id)
        run = store.list('run', **scope.db())[0].payload
        self.assertEqual(run['failed_node'], 'assess')
        self.assertEqual(run['error'], 'invalid_response')
        self.assertNotIn('secret source content', json.dumps(run))
        self.assertNotIn('secret source content', '\n'.join(logs.output))
