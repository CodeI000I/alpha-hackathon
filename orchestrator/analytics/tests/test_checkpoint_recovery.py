"""Real PostgresSaver resume check; opt-in via ANALYTICS_TEST_DATABASE_URL."""

import os
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone
from uuid import uuid4

from orchestrator.analytics.models import CompanyFact, CompanyProfile, NewsArticle, Scope
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import PostgresStore
from orchestrator.llm import AIError
from orchestrator.decision import DecisionOutcome, RoutingDecision
from orchestrator.analytics.tests.test_service import FakeModel

try:
    import psycopg
    from orchestrator.analytics.migrate import apply_migrations
except ImportError:  # pragma: no cover - PostgreSQL integration dependencies are optional
    psycopg = None
    apply_migrations = None


DSN = os.environ.get('ANALYTICS_TEST_DATABASE_URL')


@unittest.skipUnless(DSN and psycopg and apply_migrations,
                     'set ANALYTICS_TEST_DATABASE_URL and install psycopg for local PostgreSQL recovery')
class CheckpointRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DSN, connect_timeout=3, statement_timeout_ms=5000)

    def test_assessment_resumes_from_postgres_checkpoint_after_transient_failure(self):
        from langgraph.checkpoint.postgres import PostgresSaver

        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        suffix = uuid4().hex
        scope = Scope(tenant_id='checkpoint-' + suffix, company_id='company-' + suffix)
        store = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=5000)
        self.addCleanup(store.close)

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
        primary_triage = Mock()
        primary_triage.decide.return_value = DecisionOutcome(
            RoutingDecision(relevance='irrelevant', kind='event', priority='high'), 'systemone')
        resumed_triage = Mock()
        with PostgresSaver.from_conn_string(DSN) as saver:
            saver.setup()
            service = AnalyticsService(store, model, checkpointer=saver, clock=lambda: now,
                                       debounce_seconds=0, decision_router=primary_triage,
                                       triage_version='test-triage-v1')
            profile = CompanyProfile(name='Checkpoint fixture', knowledge_revision=1, facts=[
                CompanyFact(fact_id='contract-' + suffix, text='supplier floating price',
                    subject_id=scope.company_id, predicate='buys_from', object_id='supplier',
                    exposure='order-1', business_factors=['procurement_cost'],
                    verification_status='user_asserted')
            ])
            # Seed only this fixture's company state; update_company_profile also schedules
            # reprocessing for every global event already present in the shared test database.
            with store.transaction():
                store.put('company', scope.company_id, profile.model_dump(mode='json'), **scope.db())
                for fact in profile.facts:
                    store.index_text('fact', fact.fact_id, fact.text, **scope.db())
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
            self.assertEqual(pending.values['triage']['provider'], 'systemone')
            persisted_triage = store.list('triage', **scope.db())
            self.assertEqual(len(persisted_triage), 1)
            self.assertEqual(persisted_triage[0].payload['provider'], 'systemone')

        # Both durable components are reopened: only PostgreSQL state can resume the run.
        store.close()
        store = PostgresStore(DSN, connect_timeout=3, statement_timeout_ms=5000)
        self.addCleanup(store.close)
        with PostgresSaver.from_conn_string(DSN) as reopened_saver:
            resumed_service = AnalyticsService(store, model, checkpointer=reopened_saver, clock=lambda: now,
                                               debounce_seconds=0, decision_router=resumed_triage,
                                               triage_version='test-triage-v1')
            resumed = resumed_service.analyze_event_for_company(scope, event_id)
            self.assertEqual(resumed.event_id, event_id)
            self.assertEqual(resumed.assessment.relevance, 'relevant')
            self.assertEqual(model.assessment_attempts, 2)
            primary_triage.decide.assert_called_once()
            resumed_triage.decide.assert_not_called()
            self.assertEqual(resumed.triage.decision.relevance, 'irrelevant')
            self.assertFalse(resumed_service.impact_graph.get_state(config).next)
            self.assertIsNotNone(store.get('impact', resumed.impact_id, **scope.db()))
            self.assertEqual(event_record.payload['event_id'], resumed.event_id)


if __name__ == '__main__':
    unittest.main()
