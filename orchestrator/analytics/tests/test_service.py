from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from threading import Event as ThreadingEvent, Thread, current_thread
import unittest
from unittest.mock import patch

from orchestrator.analytics.models import CompanyFact, CompanyProfile, Event, NewsArticle, Scope, digest
from orchestrator.analytics.store import MemoryStore, StoreBusy
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
            summary = ('Зафиксированная цена защищает закупку.' if fixed
                       else 'Прайс может изменить стоимость закупки.')
            value = dict(relevance='relevant', evidence_sufficiency='sufficient',
                         link_type='direct', risk_supported='no' if fixed else 'yes',
                         opportunity_supported='no', impact_magnitude='low' if fixed else 'high',
                         urgency='monitor', impact_horizon='short', business_factors=['procurement_cost'],
                         supporting_fact_ids=[facts[0]['fact_id']], supporting_path_ids=[],
                         causal_chain=[dict(text=summary,
                             evidence_ids=[facts[0]['fact_id'], NewsArticle.model_validate(pack['news'][0]).evidence_id])],
                         missing_factors=[], summary=summary,
                         suggested_action='Проверить ближайшую поставку.', exposure='order-1')
        elif schema.__name__ == 'Answer':
            value = dict(text='Гипотеза не меняет сохранённый договор.',
                         evidence_ids=[context['evidence'][0]['company_facts'][0]['fact_id']], missing_facts=[])
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

    def test_thinking_mode_invalidates_persisted_impact_and_matches_read_only_policy(self):
        from orchestrator.config import Settings
        from orchestrator.analytics.runtime import ReadOnlyModel
        settings = Settings().model_copy(update={'deepseek_thinking_enabled': True})
        enabled_model = FakeModel()
        enabled_model.settings = settings
        enabled = AnalyticsService(self.store, enabled_model, clock=lambda: NOW, debounce_seconds=0)
        event_id = enabled.ingest_news(self.article())['event_id']
        first = enabled.analyze_event_for_company(self.scope, event_id)

        disabled_model = FakeModel()
        disabled_model.settings = settings.model_copy(update={'deepseek_thinking_enabled': False})
        disabled = AnalyticsService(self.store, disabled_model, clock=lambda: NOW, debounce_seconds=0)
        self.assertNotEqual(enabled.policy, disabled.policy)
        second = disabled.analyze_event_for_company(self.scope, event_id)
        self.assertEqual(disabled_model.calls.count('ImpactAssessment'), 1)
        self.assertNotEqual(first.context_version, second.context_version)
        self.assertEqual(len(self.store.history('impact', first.impact_id, **self.scope.db())), 2)
        reader = AnalyticsService(self.store, ReadOnlyModel(disabled_model.settings), clock=lambda: NOW)
        self.assertEqual(reader.policy, disabled.policy)

    def test_chat_rejects_answers_without_evidence_or_nonblank_missing_facts(self):
        from orchestrator.models import Answer
        self.service.ingest_news(self.article(), scopes=[self.scope])
        issue = self.service.list_company_issues(self.scope)[0]
        for missing in ([], [''], [' \t']):
            with self.subTest(missing=missing):
                answer = Answer(text='Компания получит 123 миллиона рублей.',
                                evidence_ids=[], missing_facts=missing)
                with patch.object(self.model, 'structured', return_value=answer) as call:
                    with self.assertRaises(ValueError):
                        self.service.ask_about_issue(self.scope, issue.issue_id, 'Каков эффект?',
                            conversation_id='unsupported', request_id='q1')
                self.assertEqual(call.call_count, 1)
                with self.assertRaises(KeyError):
                    self.service.get_conversation(self.scope, 'unsupported')

    def test_chat_preserves_explicit_insufficiency_and_rejects_foreign_citations(self):
        from orchestrator.models import Answer
        self.service.ingest_news(self.article(), scopes=[self.scope])
        issue = self.service.list_company_issues(self.scope)[0]
        answer = Answer(text='Недостаточно сведений о размере закупки.', evidence_ids=[],
                        missing_facts=['Размер закупки'])
        with patch.object(self.model, 'structured', return_value=answer):
            reply = self.service.ask_about_issue(self.scope, issue.issue_id, 'Каков эффект?',
                conversation_id='insufficient', request_id='q1')
        self.assertEqual(reply['answer']['missing_facts'], ['Размер закупки'])
        with patch.object(self.model, 'structured', return_value=answer.model_copy(
                update={'evidence_ids': ['foreign']})):
            with self.assertRaises(ValueError):
                self.service.ask_about_issue(self.scope, issue.issue_id, 'Каков эффект?',
                    conversation_id='foreign', request_id='q1')

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

    def test_oversized_assessment_preserves_facts_and_requests_context_without_llm(self):
        company = profile()
        company.facts = [company.facts[0].model_copy(update={
            'fact_id': f'contract-{number}',
            'text': 'supplier price ' + ('x' * 4000),
        }) for number in range(12)]
        self.service.update_company_profile(self.scope, company)
        event_id = self.service.ingest_news(self.article())['event_id']

        impact = self.service.analyze_event_for_company(self.scope, event_id)

        self.assertEqual(impact.route, 'needs_context')
        self.assertIn('context_limit', impact.assessment.missing_factors)
        self.assertEqual(len(impact.evidence.company_facts), 12)
        self.assertEqual(impact.assessment.risk_supported, 'unknown')
        self.assertEqual(self.model.calls.count('ImpactAssessment'), 0)
        self.assertEqual(self.service.list_company_issues(self.scope), [])
        self.assertTrue(all(record.payload['status'] == 'completed'
                            for record in self.store.list('run', **self.scope.db())))

    def test_changed_retrieved_chunks_invalidate_impact_without_company_revision_change(self):
        from orchestrator.analytics.knowledge import parse_document
        original_retrieve = self.service.retriever.retrieve
        content = ['supplier contract first edition']

        def retrieve(*args):
            pack = original_retrieve(*args)
            pack.chunks = parse_document('retrieved', 1, 'retrieved.txt',
                                         content[0].encode(), 'text/plain').chunks
            return pack

        self.service.retriever.retrieve = retrieve
        event_id = self.service.ingest_news(self.article())['event_id']
        first = self.service.analyze_event_for_company(self.scope, event_id)
        content[0] = 'supplier contract with newly available exception'
        second = self.service.analyze_event_for_company(self.scope, event_id)

        self.assertEqual(first.company_knowledge_revision, second.company_knowledge_revision)
        self.assertNotEqual(first.context_version, second.context_version)
        self.assertEqual(second.evidence.chunks[0].text, content[0])
        self.assertEqual(self.model.calls.count('ImpactAssessment'), 2)
        self.service.analyze_event_for_company(self.scope, event_id)
        self.assertEqual(self.model.calls.count('ImpactAssessment'), 2)

    def test_optional_triage_does_not_displace_primary_evidence_at_input_boundary(self):
        from orchestrator.llm import structured_messages
        from orchestrator.models import canonical
        from orchestrator.analytics.models import ImpactAssessment
        from orchestrator.analytics.service import DATA_INSTRUCTION, IMPACT_PROMPT

        event_id = self.service.ingest_news(self.article())['event_id']
        state = self.service._retrieve({'scope': self.scope.model_dump(), 'event_id': event_id})
        context = {'evidence': state['evidence']}
        self.service.max_input_chars = len(canonical(structured_messages(
            DATA_INSTRUCTION + IMPACT_PROMPT, context, ImpactAssessment)))
        state['triage'] = {'decision': {'relevance': 'relevant', 'kind': 'risk', 'priority': 'high'}}

        with patch.object(self.model, 'structured', wraps=self.model.structured) as call:
            result = self.service._assess(state)

        self.assertEqual(result['route'], 'accepted')
        self.assertEqual(call.call_args.args[2], context)
        self.assertNotIn('preliminary_triage', call.call_args.args[2])

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

    def test_profile_and_reprocess_job_publish_atomically(self):
        self.store.put('event', 'existing-event', {'revision': 1, 'source_news_ids': []})
        changed = profile(True)
        original_put = self.store.put
        def fail_job_write(kind, key, payload, **kwargs):
            if kind == 'job':
                raise RuntimeError('simulated job publication failure')
            return original_put(kind, key, payload, **kwargs)
        self.store.put = fail_job_write
        try:
            with self.assertRaisesRegex(RuntimeError, 'publication'):
                self.service.update_company_profile(self.scope, changed)
        finally:
            self.store.put = original_put

        company = self.store.get('company', self.scope.company_id, **self.scope.db())
        self.assertEqual(company.version, 1)
        self.assertFalse(self.store.list('job', **self.scope.db()))

        retried = self.service.update_company_profile(self.scope, changed)
        self.assertIn('job_id', retried)
        self.assertEqual(self.store.get('company', self.scope.company_id, **self.scope.db()).version, 2)
        self.assertEqual(len(self.store.list('job', **self.scope.db())), 1)

    def test_retry_failed_rechecks_job_after_worker_lock(self):
        job = self.service.reprocess_company(self.scope, reason='manual')
        self.store.put('job', job['job_id'], dict(job, status='failed', attempts=3), **self.scope.db())
        lock_key = 'job:' + digest([self.scope.db(), job['job_id']])
        lock_held = ThreadingEvent()
        release_lock = ThreadingEvent()

        def finish_as_worker():
            with self.store.lock(lock_key):
                lock_held.set()
                release_lock.wait(3)
                current = self.store.get('job', job['job_id'], **self.scope.db()).payload
                self.store.put('job', job['job_id'], dict(current, status='completed', attempts=1),
                               **self.scope.db())

        worker = Thread(target=finish_as_worker)
        worker.start()
        self.assertTrue(lock_held.wait(3))
        retry_lock_requested = ThreadingEvent()
        original_lock = self.store.lock
        def track_retry_lock(key):
            if key == lock_key:
                retry_lock_requested.set()
            return original_lock(key)
        self.store.lock = track_retry_lock
        result = {}
        retry = Thread(target=lambda: result.setdefault('job', self.service.reprocess_company(
            self.scope, reason='manual', retry_failed=True)))
        retry.start()
        self.assertTrue(retry_lock_requested.wait(3))
        release_lock.set()
        worker.join(3)
        retry.join(3)
        self.store.lock = original_lock
        self.assertFalse(worker.is_alive())
        self.assertFalse(retry.is_alive())
        self.assertEqual(result['job']['status'], 'completed')
        self.assertEqual(self.store.get('job', job['job_id'], **self.scope.db()).payload['status'], 'completed')

    def test_concurrent_job_creation_does_not_overwrite_completed_job(self):
        original_get = self.store.get
        first_read_done = ThreadingEvent()
        allow_first_read = ThreadingEvent()

        def pause_first_creator(kind, key, **kwargs):
            record = original_get(kind, key, **kwargs)
            if kind == 'job' and current_thread().name == 'late-job-creator':
                first_read_done.set()
                allow_first_read.wait(3)
            return record

        self.store.get = pause_first_creator
        result = {}
        creator = Thread(name='late-job-creator', target=lambda: result.setdefault(
            'job', self.service.reprocess_company(self.scope, reason='creation-race')))
        creator.start()
        self.assertTrue(first_read_done.wait(3))
        self.store.get = original_get
        winner = self.service.reprocess_company(self.scope, reason='creation-race')
        self.store.put('job', winner['job_id'], dict(winner, status='completed', attempts=1), **self.scope.db())
        allow_first_read.set()
        creator.join(3)
        self.store.get = original_get

        self.assertFalse(creator.is_alive())
        self.assertEqual(result['job']['status'], 'completed')
        self.assertEqual(self.store.get('job', winner['job_id'], **self.scope.db()).payload['status'], 'completed')

    def test_store_lock_contention_requeues_job_without_consuming_attempt(self):
        self.store.put('event', 'busy-event', {'revision': 1, 'source_news_ids': []})
        job = self.service.reprocess_company(self.scope, reason='busy-test')
        original_lock = self.store.lock

        @contextmanager
        def busy_company_lock(key):
            if key.startswith('company:'):
                raise StoreBusy('synthetic lock timeout')
            with original_lock(key):
                yield

        self.store.lock = busy_company_lock
        try:
            result = self.service.process_jobs(self.scope)
        finally:
            self.store.lock = original_lock
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['status'], result[0]['attempts'], result[0]['error']),
                         ('queued', 0, 'busy'))
        self.assertIsNotNone(result[0]['due_at'])

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

    def test_snapshot_refresh_advances_watermark_without_model_call_when_issues_are_unchanged(self):
        active_article = self.article().model_copy(update={'news_id': 'watermark-active'})
        self.service.ingest_news(active_article, scopes=[self.scope])
        previous = self.service.get_company_situation(self.scope)['snapshot']
        previous_record = self.store.get('snapshot', digest(self.scope.role), **self.scope.db())
        later = NOW + timedelta(days=1)
        article = NewsArticle(news_id='watermark-cancelled', title='Отмена изменения цены',
            content='Поставщик отменил изменение цены.', published_at=later, received_at=later)
        self.store.put('article', article.evidence_id,
                       dict(article=article.model_dump(mode='json'), status='ready', event_id='event-cancelled'))
        event = Event(event_type='price', action='price_change', subject='parts', modality='announcement',
            summary='Отменённое изменение цены', entities=['supplier'], affected_factors=['procurement_cost'],
            event_time=NOW, evidence_quote=article.content, status='cancelled', event_id='event-cancelled',
            source_news_ids=[article.evidence_id])
        self.store.put('event', event.event_id, event.model_dump(mode='json'))
        self.service.clock = lambda: later + timedelta(days=1)
        self.service.analyze_event_for_company(self.scope, event.event_id)
        calls = len(self.model.calls)

        refreshed = self.service.refresh_snapshot(self.scope, force=True)
        situation = self.service.get_company_situation(self.scope)
        self.assertEqual(refreshed.news_processed_through, later)
        self.assertEqual(refreshed.as_of, later + timedelta(days=1))
        self.assertEqual(refreshed.snapshot_version, previous['snapshot_version'])
        self.assertGreater(self.store.get('snapshot', digest(self.scope.role), **self.scope.db()).version,
                           previous_record.version)
        self.assertEqual(len(self.model.calls), calls)
        self.assertTrue(situation['current'])

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
