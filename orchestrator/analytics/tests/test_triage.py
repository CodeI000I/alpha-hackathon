import unittest
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from orchestrator.config import Settings
from orchestrator.decision import build_decision_router, LLMRoutingDecisionProvider
from orchestrator.llm import AIError
from orchestrator.llm import LLMClient
from orchestrator.analytics.models import CompanyProfile, NewsArticle, Scope
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import MemoryStore
from orchestrator.analytics.tests.test_service import FakeModel, NOW, profile


class TriageModel(FakeModel):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.contexts = []
        self.fail_assessment = False

    def structured(self, stage, instruction, context, schema, validate=None):
        self.contexts.append(context)
        if schema.__name__ == 'RoutingDecision':
            self.calls.append(schema.__name__)
            return schema(relevance='relevant', kind='risk', priority='high')
        if schema.__name__ == 'ImpactAssessment' and self.fail_assessment:
            raise AIError('unavailable', 'synthetic outage')
        return super().structured(stage, instruction, context, schema, validate)


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.settings = Settings(api_key=SecretStr('test-only'), systemone_url='https://triage.test')
        self.model = TriageModel(self.settings)
        self.requests = []
        self.status = 200
        self.scope = Scope(tenant_id='one', company_id='company')

    def response(self, request):
        self.requests.append(request)
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'models': [{'name': self.settings.systemone_model}]})
        return httpx.Response(self.status, json={
            'model': self.settings.systemone_model,
            'answers': {key: {'type': 'choice', 'choice': value} for key, value in
                        dict(relevance='irrelevant', kind='event', priority='high').items()},
            'usage': {'input_tokens': 20, 'output_tokens': 3}})

    def service(self, version=None):
        from orchestrator.analytics.triage import triage_policy
        router = build_decision_router(self.settings, LLMRoutingDecisionProvider(self.model),
            store=self.store, http_client=httpx.Client(transport=httpx.MockTransport(self.response)))
        self.addCleanup(router.close)
        return AnalyticsService(self.store, self.model, clock=lambda: NOW, decision_router=router,
                                triage_version=version or triage_policy(self.settings))

    def prepare(self, service):
        service.update_company_profile(self.scope, profile())
        return service.ingest_news(NewsArticle(news_id='one', title='Цена', content='Поставщик изменил прайс.',
            published_at=NOW, received_at=NOW))['event_id']

    def test_irrelevant_triage_cannot_drop_grounded_news_and_reads_are_cached(self):
        service = self.service()
        event = self.prepare(service)
        impact = service.analyze_event_for_company(self.scope, event)
        service.refresh_snapshot(self.scope)
        self.assertEqual(impact.route, 'accepted')
        self.assertEqual(impact.triage.decision.relevance, 'irrelevant')
        self.assertEqual(impact.triage.provider, 'systemone')
        self.assertEqual(impact.assessment.urgency, 'monitor')
        self.assertEqual(len(impact.evidence.news), 1)
        self.assertTrue(any('preliminary_triage' in context for context in self.model.contexts))
        before = (len(self.requests), len(self.model.calls))
        self.assertEqual(service.analyze_event_for_company(self.scope, event), impact)
        self.assertTrue(service.get_company_situation(self.scope)['current'])
        self.assertEqual((len(self.requests), len(self.model.calls)), before)
        metric = next(row for row in self.store.metrics() if row['stage'] == 'systemone')
        self.assertEqual((metric['calls'], metric['prompt_tokens'], metric['completion_tokens']), (1, 20, 3))

    def test_outage_uses_existing_llm_and_records_actual_provider(self):
        self.status = 503
        service = self.service()
        impact = service.analyze_event_for_company(self.scope, self.prepare(service))
        self.assertEqual(impact.triage.provider, 'llm')
        self.assertEqual(impact.route, 'accepted')
        self.assertIn('RoutingDecision', self.model.calls)

    def test_failed_assessment_reuses_persisted_triage_after_restart(self):
        service = self.service()
        event = self.prepare(service)
        self.model.fail_assessment = True
        with self.assertRaises(AIError):
            service.analyze_event_for_company(self.scope, event)
        self.model.fail_assessment = False
        service = self.service()
        impact = service.analyze_event_for_company(self.scope, event)
        self.assertEqual(impact.route, 'accepted')
        self.assertEqual(sum(r.method == 'POST' for r in self.requests), 1)

    def test_triage_cache_is_scoped_and_invalidated_by_policy_change(self):
        service = self.service()
        event = self.prepare(service)
        service.analyze_event_for_company(self.scope, event)
        service.refresh_snapshot(self.scope)
        other = Scope(tenant_id='two', company_id='company')
        service.update_company_profile(other, profile(True))
        service.analyze_event_for_company(other, event)
        changed = self.service(version='new-model-policy')
        self.assertFalse(changed.get_company_situation(self.scope)['current'])
        changed.analyze_event_for_company(self.scope, event)
        self.assertEqual(sum(r.method == 'POST' for r in self.requests), 3)
        self.assertEqual(len(self.store.list('triage', **other.db())), 1)
        self.assertEqual(len(self.store.list('triage', **self.scope.db())), 2)

    def test_missing_facts_and_inactive_events_skip_triage(self):
        service = self.service()
        event = self.prepare(service)
        empty = Scope(tenant_id='empty', company_id='company')
        service.update_company_profile(empty, CompanyProfile(name='Empty'))
        self.assertIsNone(service.analyze_event_for_company(empty, event).triage)
        record = self.store.get('event', event)
        self.store.put('event', event, dict(record.payload, status='cancelled'))
        self.assertIsNone(service.analyze_event_for_company(self.scope, event).triage)
        self.assertEqual(self.requests, [])

    def test_oversize_triage_defers_to_grounded_assessment_input_limit(self):
        self.settings = self.settings.model_copy(update={'max_input_chars': 6000})
        self.model.settings = self.settings
        service = self.service()
        event = self.prepare(service)
        company = profile()
        company.facts[0].text = 'supplier floating price ' + 'x' * 5700
        service.update_company_profile(self.scope, company)
        def unexpected_http(_request):
            self.fail('Oversized input must fail before HTTP')
        client = LLMClient(self.settings, self.store,
                           http_client=httpx.Client(transport=httpx.MockTransport(unexpected_http)))
        self.addCleanup(client.close)
        service.llm = client
        with self.assertRaises(AIError) as error:
            service.analyze_event_for_company(self.scope, event)
        self.assertEqual(error.exception.code, 'input_limit')
        triage = self.store.list('triage', **self.scope.db())[0].payload
        self.assertEqual(triage['status'], 'skipped_input_limit')
        self.assertIsNone(triage['decision'])
        self.assertEqual(self.requests, [])

    def test_policy_tracks_model_endpoint_and_questions_without_credentials(self):
        from orchestrator.analytics.triage import triage_policy
        original = triage_policy(self.settings)
        for change in ({'systemone_model': 'clef'}, {'systemone_url': 'https://another.test'},
                       {'decision_model': 'different'}, {'systemone_timeout_seconds': 1},
                       {'systemone_cooldown_seconds': 120}):
            with self.subTest(change=change):
                self.assertNotEqual(original, triage_policy(self.settings.model_copy(update=change)))
        self.assertEqual(original, triage_policy(self.settings.model_copy(
            update={'systemone_api_key': SecretStr('another-secret')})))
        with patch('orchestrator.analytics.triage.FALLBACK_INSTRUCTION', 'New criteria'):
            self.assertNotEqual(original, triage_policy(self.settings))


if __name__ == '__main__':
    unittest.main()
