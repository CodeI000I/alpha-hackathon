from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch

from orchestrator.analytics.models import CompanyFact, CompanyProfile, NewsArticle, Scope
from orchestrator.analytics.store import MemoryStore
from orchestrator.analytics.service import AnalyticsService


NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


class FakeModel:
    """Synthetic model boundary, never a substitute for the production model adapter."""
    def __init__(self):
        self.calls = []

    def structured(self, stage, instruction, context, schema, validate=None):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'EventDraft':
            article = context['article']
            value = dict(event_type='price', action='price_change', subject='components',
                         modality='announcement', summary=article['title'], entities=['supplier'],
                         affected_factors=['procurement_cost'], event_time=NOW.isoformat(),
                         evidence_quote=article['content'])
        elif schema.__name__ == 'ImpactAssessment':
            pack = context['evidence']
            facts = pack['company_facts']
            fixed = any('fixed' in f['text'] for f in facts)
            value = dict(relevance='relevant', evidence_sufficiency='sufficient',
                         link_type='direct', risk_supported='no' if fixed else 'yes',
                         opportunity_supported='no', impact_magnitude='low' if fixed else 'high',
                         urgency='monitor', impact_horizon='short', business_factors=['procurement_cost'],
                         supporting_fact_ids=[facts[0]['fact_id']], supporting_path_ids=[],
                         missing_factors=[], summary='Зафиксированная цена защищает закупку.' if fixed else 'Прайс может изменить стоимость закупки.',
                         suggested_action='Проверить ближайшую поставку.', exposure='order-1')
        elif schema.__name__ == 'Answer':
            value = dict(text='Гипотеза не меняет сохранённый договор.', evidence_ids=[], missing_facts=[])
        else:
            raise AssertionError(schema.__name__)
        result = schema.model_validate(value)
        if validate:
            validate(result)
        return result


def profile(fixed=False):
    return CompanyProfile(name='Завод', facts=[CompanyFact(
        fact_id='contract', text='fixed supplier price' if fixed else 'supplier floating price',
        subject_id='company', predicate='buys_from', object_id='supplier',
        exposure='order-1', business_factors=['procurement_cost'], verification_status='user_asserted')])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.store, self.model = MemoryStore(), FakeModel()
        self.service = AnalyticsService(self.store, self.model, clock=lambda: NOW, debounce_seconds=0)
        self.scope = Scope(tenant_id='tenant', company_id='company', user_id='alice')
        self.service.update_company_profile(self.scope, profile())

    def article(self, **kwargs):
        return NewsArticle(news_id='n1', title='Изменение цены', content='Поставщик изменил прайс.',
                           published_at=NOW, received_at=NOW, **kwargs)

    def test_duplicate_ingestion_and_reads_do_not_call_model(self):
        first = self.service.ingest_news(self.article(), scopes=[self.scope])
        count = len(self.model.calls)
        second = self.service.ingest_news(self.article(), scopes=[self.scope])
        situation = self.service.get_company_situation(self.scope)
        issues = self.service.list_company_issues(self.scope)
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertEqual(len(issues), 1)
        self.assertTrue(situation['current'])
        self.assertEqual(len(self.model.calls), count)

    def test_same_event_different_company_contract(self):
        other = Scope(tenant_id='another', company_id='company')
        self.service.update_company_profile(other, profile(True))
        result = self.service.ingest_news(self.article(), scopes=[self.scope, other])
        left = self.service.analyze_event_for_company(self.scope, result['event_id'])
        right = self.service.analyze_event_for_company(other, result['event_id'])
        self.assertEqual(left.assessment.risk_supported, 'yes')
        self.assertEqual(right.assessment.risk_supported, 'no')
        self.assertEqual(self.model.calls.count('EventDraft'), 1)

    def test_chat_is_pinned_and_does_not_change_facts(self):
        self.service.ingest_news(self.article(), scopes=[self.scope])
        issue = self.service.list_company_issues(self.scope)[0]
        before = self.store.get('company', self.scope.company_id, **self.scope.db())
        reply = self.service.ask_about_issue(self.scope, issue.issue_id, 'Что если цена фиксирована?',
                                             conversation_id='c1', request_id='q1')
        self.assertEqual(reply['issue_version'], issue.version)
        self.assertEqual(before, self.store.get('company', self.scope.company_id, **self.scope.db()))
        with self.assertRaises(KeyError):
            self.service.get_issue(Scope(tenant_id='foreign', company_id='company'), issue.issue_id)

    def test_unknown_company_facts_do_not_become_negative_effect(self):
        scope = Scope(tenant_id='empty', company_id='empty')
        self.service.update_company_profile(scope, CompanyProfile(name='Без документов'))
        result = self.service.ingest_news(self.article(), scopes=[scope])
        impact = self.service.analyze_event_for_company(scope, result['event_id'])
        self.assertEqual(impact.route, 'needs_context')
        self.assertEqual(impact.assessment.risk_supported, 'unknown')
        self.assertEqual(self.service.list_company_issues(scope), [])

    def test_profile_change_queues_reprocessing_without_external_scheduler(self):
        self.service.ingest_news(self.article(), scopes=[self.scope])
        result = self.service.update_company_profile(self.scope, profile(True))
        self.assertIn('job_id', result)
        self.assertFalse(self.service.get_company_situation(self.scope)['current'])
        self.service.process_jobs(self.scope)
        self.assertTrue(self.service.get_company_situation(self.scope)['current'])
        self.assertEqual(self.service.list_company_issues(self.scope)[0].overall_effect, 'neutral')

    def test_future_fact_activation_invalidates_snapshot_without_writing_on_read(self):
        now = [NOW]
        self.service.clock = lambda: now[0]
        company = profile()
        future = company.facts[0].model_copy(update={'fact_id': 'future', 'text': 'fixed supplier price',
                                                   'valid_from': NOW + timedelta(days=1)})
        company.facts.append(future)
        self.service.update_company_profile(self.scope, company)
        self.service.ingest_news(self.article(), scopes=[self.scope])
        self.assertTrue(self.service.get_company_situation(self.scope)['current'])
        now[0] += timedelta(days=2)
        calls = len(self.model.calls)
        self.assertFalse(self.service.get_company_situation(self.scope)['current'])
        self.assertEqual(len(self.model.calls), calls)

    def test_corrected_source_invalidates_impact_even_when_event_identity_is_unchanged(self):
        first = self.service.ingest_news(self.article(), scopes=[self.scope])
        before = self.service.analyze_event_for_company(self.scope, first['event_id'])
        revised = self.article(revision=2).model_copy(update={'content': 'Поставщик изменил прайс. Есть исключение для старых заказов.'})
        self.service.ingest_news(revised)
        self.assertFalse(self.service.get_company_situation(self.scope)['current'])
        after = self.service.analyze_event_for_company(self.scope, first['event_id'])
        self.assertEqual(after.event_revision, before.event_revision)
        self.assertNotEqual(after.context_version, before.context_version)
        self.assertEqual([news.revision for news in after.evidence.news], [2])

    def test_explicit_retry_requeues_failed_job_with_bounded_new_attempts(self):
        job = self.service.reprocess_company(self.scope, reason='manual')
        self.store.put('job', job['job_id'], dict(job, status='failed', attempts=3), **self.scope.db())
        self.assertEqual(self.service.reprocess_company(self.scope, reason='manual')['status'], 'failed')
        retried = self.service.reprocess_company(self.scope, reason='manual', retry_failed=True)
        self.assertEqual((retried['status'], retried['attempts']), ('queued', 0))

    def test_conversation_and_read_state_are_user_scoped(self):
        self.service.ingest_news(self.article(), scopes=[self.scope])
        issue = self.service.list_company_issues(self.scope)[0]
        self.service.ask_about_issue(self.scope, issue.issue_id, 'Что проверить?', conversation_id='chat', request_id='1')
        self.service.set_user_state(self.scope, issue.issue_id, mark_read=True, pinned=True)
        calls = len(self.model.calls)
        self.assertEqual(len(self.service.get_conversation(self.scope, 'chat')['replies']), 1)
        self.assertFalse(self.service.get_user_state(self.scope, issue.issue_id)['unread'])
        colleague = self.scope.model_copy(update={'user_id': 'bob'})
        self.assertTrue(self.service.get_user_state(colleague, issue.issue_id)['unread'])
        with self.assertRaises(KeyError):
            self.service.get_conversation(colleague, 'chat')
        self.assertEqual(len(self.model.calls), calls)

    def test_repeated_undated_headline_on_another_day_is_not_merged_by_text(self):
        original = self.model.structured
        def undated(stage, instruction, context, schema, validate=None):
            result = original(stage, instruction, context, schema, validate)
            return result.model_copy(update={'event_time': None}) if schema.__name__ == 'EventDraft' else result
        self.model.structured = undated
        first = self.service.ingest_news(self.article())
        later = self.article().model_copy(update={'news_id': 'next-month', 'published_at': NOW + timedelta(days=30)})
        second = self.service.ingest_news(later)
        self.assertNotEqual(first['event_id'], second['event_id'])

    def test_prompt_and_configured_policy_changes_invalidate_saved_outputs(self):
        from orchestrator.config import Settings
        self.model.settings = Settings()
        service = AnalyticsService(self.store, self.model, clock=lambda: NOW, debounce_seconds=0)
        service.ingest_news(self.article(), scopes=[self.scope])
        self.assertTrue(service.get_company_situation(self.scope)['current'])
        self.model.settings = Settings(policy_version='next-policy')
        changed = AnalyticsService(self.store, self.model, clock=lambda: NOW)
        self.assertFalse(changed.get_company_situation(self.scope)['current'])
        self.model.settings = Settings()
        with patch('orchestrator.analytics.service.IMPACT_PROMPT', 'Updated prompt'):
            changed = AnalyticsService(self.store, self.model, clock=lambda: NOW)
        self.assertFalse(changed.get_company_situation(self.scope)['current'])


if __name__ == '__main__':
    unittest.main()
