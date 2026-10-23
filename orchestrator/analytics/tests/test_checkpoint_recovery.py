"""Real PostgresSaver resume check; opt-in via ANALYTICS_TEST_DATABASE_URL."""

import os
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from orchestrator.analytics.models import CompanyFact, CompanyProfile, NewsArticle, Scope
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import MemoryStore
from orchestrator.llm import AIError
from orchestrator.analytics.tests.test_service import FakeModel


DSN = os.environ.get('ANALYTICS_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'set ANALYTICS_TEST_DATABASE_URL for local PostgreSQL checkpoint recovery')
class CheckpointRecoveryTests(unittest.TestCase):
    def test_assessment_resumes_from_postgres_checkpoint_after_transient_failure(self):
        from langgraph.checkpoint.postgres import PostgresSaver

        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        suffix = uuid4().hex
        scope = Scope(tenant_id='checkpoint-' + suffix, company_id='company-' + suffix)
        store = MemoryStore()

        class OneFailureModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.fail = True
                self.assessment_attempts = 0

            def structured(self, stage, instruction, context, schema, validate=None):
                if schema.__name__ == 'ImpactAssessment':
                    self.assessment_attempts += 1
                    if self.fail:
                        self.fail = False
                        raise AIError('temporary', 'synthetic transient failure')
                return super().structured(stage, instruction, context, schema, validate)

        model = OneFailureModel()
        with PostgresSaver.from_conn_string(DSN) as saver:
            saver.setup()
            service = AnalyticsService(store, model, checkpointer=saver, clock=lambda: now,
                                       debounce_seconds=0)
            service.update_company_profile(scope, CompanyProfile(name='Checkpoint fixture', facts=[
                CompanyFact(fact_id='contract-' + suffix, text='supplier floating price',
                    subject_id=scope.company_id, predicate='buys_from', object_id='supplier',
                    exposure='order-1', business_factors=['procurement_cost'],
                    verification_status='user_asserted')
            ]))
            article = NewsArticle(news_id='news-' + suffix, title='Price update',
                content='Supplier changes price.', published_at=now, received_at=now)
            event_id = service.ingest_news(article)['event_id']

            with self.assertRaises(AIError):
                service.analyze_event_for_company(scope, event_id)

            event_record = store.get('event', event_id)
            run_id = service.store.list('run', **scope.db())[0].key
            config = {'configurable': {'thread_id': 'impact:' + run_id}}
            pending = service.impact_graph.get_state(config)
            self.assertEqual(pending.next, ('assess',))
            self.assertIn('evidence', pending.values)

            resumed = service.analyze_event_for_company(scope, event_id)
            self.assertEqual(resumed.event_id, event_id)
            self.assertEqual(resumed.assessment.relevance, 'relevant')
            self.assertEqual(model.assessment_attempts, 2)
            self.assertFalse(service.impact_graph.get_state(config).next)
            self.assertIsNotNone(store.get('impact', resumed.impact_id, **scope.db()))
            self.assertEqual(event_record.payload['event_id'], resumed.event_id)


if __name__ == '__main__':
    unittest.main()
