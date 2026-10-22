import copy
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from orchestrator.api import create_app
from orchestrator.config import ConfigurationError, Settings, load_settings
from orchestrator.demo import ASSESSMENT, REPORT, REQUEST, completion, mock_response
from orchestrator.llm import AIError, LLMClient, next_reset
from orchestrator.models import CaseStatePatch, Company, Evidence, News, RankRequest
from orchestrator.pipeline import Pipeline, Principal
from orchestrator.retrieval import Retriever
from orchestrator.storage import Store


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(api_key=SecretStr('sk-test-secret'), service_token=SecretStr('internal'),
                                 db_path=Path(self.temp.name) / 'test.sqlite3', requests_per_minute=120)
        self.store = Store(self.settings.db_path)
        self.requests = []
        self.replies = []
        self.delays = []
        self.now = datetime(2026, 10, 20, 10, tzinfo=timezone.utc).timestamp()
        self.client = self.make_client()
        self.pipeline = Pipeline(self.settings, self.store, self.client)
        self.request = RankRequest.model_validate(REQUEST)
        self.principal = Principal('user-1', frozenset({1}))

    def make_client(self, settings=None):
        def handler(request):
            self.requests.append(request)
            if self.replies:
                reply = self.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return reply
            return mock_response(request)
        client = LLMClient(settings or self.settings, self.store,
                           http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                           sleep=self.delays.append, clock=lambda: self.now)
        self.addCleanup(client.close)
        return client

    def complete(self, client=None):
        return (client or self.client).complete('decision', [{'role': 'user', 'content': 'test'}])

    def test_complete_pipeline_is_cached_and_open_is_free(self):
        matches = self.pipeline.rank(self.request)
        self.assertEqual(matches[0]['role'], 'procurement')
        self.assertEqual(matches[0]['kind'], 'risk')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.pipeline.rank(self.request), matches)
        job_id = self.pipeline.submit(self.request)[0]
        report = self.pipeline.read(job_id, self.principal)
        self.assertEqual(report['status'], 'ready')
        self.assertTrue(report['current'])
        self.assertEqual(report['result']['report']['summary'], REPORT['summary'])
        self.assertTrue(report['result']['evidence'])
        self.assertEqual(len(self.requests), 2)
        body = json.loads(self.requests[0].content)
        self.assertEqual(body['model'], 'deepseek/deepseek-v4.1-flash')
        self.assertNotIn('response_format', body)
        self.assertNotIn('tools', body)
        self.assertNotIn('sk-test-secret', json.dumps(report))
        self.assertNotIn('company_context', report['result'])
        self.assertNotIn('event', report['result'])
        self.assertNotIn('task_id', report['result'])

    def test_restart_preserves_results(self):
        self.pipeline.rank(self.request)
        other = Pipeline(self.settings, Store(self.settings.db_path), self.client)
        other.rank(self.request)
        self.assertEqual(len(self.requests), 2)

    def test_budget_429_is_not_retried_and_survives_restart(self):
        self.replies = [httpx.Response(429, json={'error': {'message': 'Budget has been exceeded'}})]
        for client in [self.client, self.make_client()]:
            with self.assertRaises(AIError) as caught:
                self.complete(client)
            self.assertEqual(caught.exception.code, 'budget_exceeded')
            self.assertEqual(caught.exception.retry_at, next_reset(self.now))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delays, [])

    def test_budget_400_and_200_are_recognized(self):
        for status in (400, 200):
            self.store.block_budget(self.client.account, 0)
            self.replies = [httpx.Response(status, json={'error': {'message': 'Budget has been exceeded'}})]
            with self.assertRaises(AIError) as caught:
                self.complete()
            self.assertEqual(caught.exception.code, 'budget_exceeded')

    def test_reset_boundary_uses_moscow(self):
        before = datetime.fromisoformat('2026-10-20T02:59:59+03:00').timestamp()
        exact = datetime.fromisoformat('2026-10-20T03:00:00+03:00').timestamp()
        self.assertEqual(next_reset(before), exact)
        self.assertEqual(next_reset(exact), exact + 86400)
        self.store.block_budget(self.client.account, self.now)
        self.complete()
        self.assertEqual(len(self.requests), 1)

    def test_transient_retry_count_has_no_sdk_multiplication(self):
        self.replies = [httpx.Response(503, json={'error': 'temporary'}) for _ in range(3)]
        with self.assertRaises(AIError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'unavailable')
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len(self.delays), 2)

    def test_retry_after_respected(self):
        self.replies = [httpx.Response(429, headers={'Retry-After': '4'}, json={'error': 'rate limit'})]
        self.complete()
        self.assertEqual(self.delays, [4])
        self.assertEqual(len(self.requests), 2)

    def test_long_retry_after_defers_without_sleeping(self):
        self.replies = [httpx.Response(429, headers={'Retry-After': '120'}, json={'error': 'rate limit'})]
        with self.assertRaises(AIError) as caught:
            self.complete()
        self.assertEqual(caught.exception.retry_at, self.now + 120)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delays, [])

    def test_timeout_is_bounded(self):
        self.replies = [httpx.ReadTimeout('secret never printed') for _ in range(3)]
        with self.assertRaises(AIError) as caught:
            self.complete()
        self.assertEqual(caught.exception.code, 'timeout')
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(len(self.requests), 3)

    def test_authentication_does_not_retry_or_echo_response(self):
        self.replies = [httpx.Response(401, json={'error': 'sk-test-secret'})]
        with self.assertRaises(AIError) as caught:
            self.complete()
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('sk-test-secret', str(caught.exception))

    def test_local_rate_limit_shared_between_clients(self):
        settings = self.settings.model_copy(update={'requests_per_minute': 1})
        self.complete(self.make_client(settings))
        with self.assertRaises(AIError) as caught:
            self.complete(self.make_client(settings))
        self.assertEqual(caught.exception.code, 'rate_limited')
        self.assertEqual(len(self.requests), 1)

    def test_invalid_json_does_not_publish_or_retry(self):
        self.replies = [completion('not a JSON object')]
        job_id = self.pipeline.submit(self.request)[0]
        result = self.pipeline.run_job(job_id)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['code'], 'invalid_response')
        self.assertEqual(len(self.requests), 1)
        self.assertIsNone(result['result'])

    def test_unknown_citations_rejected(self):
        invalid = {**ASSESSMENT, 'evidence_ids': ['other-company-secret']}
        self.replies = [completion(invalid)]
        job = self.pipeline.run_job(self.pipeline.submit(self.request)[0])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(len(self.requests), 1)

    def test_report_failure_preserves_cached_assessment_for_retry(self):
        self.replies = [completion(ASSESSMENT), completion({'bad': 'report'})]
        job_id = self.pipeline.submit(self.request)[0]
        self.assertEqual(self.pipeline.run_job(job_id)['status'], 'failed')
        self.assertTrue(self.store.retry(job_id))
        self.assertEqual(self.pipeline.run_job(job_id)['status'], 'ready')
        self.assertEqual(len(self.requests), 3)

    def test_missing_context_makes_no_paid_calls(self):
        data = copy.deepcopy(REQUEST)
        data['company'].update(name='Компания', inn='', profile={})
        request = RankRequest.model_validate(data)
        self.assertEqual(self.pipeline.rank(request), [])
        job = self.store.get_job(self.pipeline.submit(request)[0])
        self.assertEqual(job['status'], 'uncertain')
        self.assertEqual(len(self.requests), 0)

    def test_irrelevant_does_not_generate_report(self):
        self.replies = [completion({**ASSESSMENT, 'score': 0.1, 'relevance': 'irrelevant',
                                    'relation_kind': 'not_established', 'risk_supported': False,
                                    'causal_chain': [], 'strongest_candidate_link': 'none'})]
        self.assertEqual(self.pipeline.rank(self.request), [])
        self.assertEqual(len(self.requests), 1)

    def test_uncertainty_without_new_evidence_does_not_repeat(self):
        self.replies = [completion({**ASSESSMENT, 'score': 0.5})]
        self.assertEqual(self.pipeline.rank(self.request), [])
        self.assertEqual(len(self.requests), 1)

    def test_news_and_company_versions_retain_history(self):
        first_id = self.pipeline.submit(self.request)[0]
        self.pipeline.run_job(first_id)
        data = copy.deepcopy(REQUEST)
        data['news']['summary'] += ' Обновление: срок перенесён.'
        second = RankRequest.model_validate(data)
        second_id = self.pipeline.submit(second)[0]
        self.pipeline.run_job(second_id)
        self.assertNotEqual(first_id, second_id)
        self.assertFalse(self.pipeline.read(first_id, self.principal)['current'])
        self.assertEqual(len(self.pipeline.read(second_id, self.principal)['history']), 2)
        # Late redelivery of a known old version must not roll back the current pointer.
        self.pipeline.submit(self.request)
        self.assertTrue(self.pipeline.read(second_id, self.principal)['current'])
        data['company']['profile']['Б2'] = 'Новый договор перевозки'
        new_ids = self.pipeline.refresh_company(Company.model_validate(data['company']), ['procurement'])
        self.assertEqual(len(new_ids), 1)
        self.assertNotEqual(new_ids[0], second_id)
        self.assertFalse(self.pipeline.read(second_id, self.principal)['current'])

    def test_situation_update_marks_old_article_stale(self):
        data = copy.deepcopy(REQUEST)
        data['news']['situationId'] = 'transport-change'
        first_id = self.pipeline.submit(RankRequest.model_validate(data))[0]
        data['news']['id'] = 2
        second_id = self.pipeline.submit(RankRequest.model_validate(data))[0]
        self.assertFalse(self.store.current(self.store.get_job(first_id)))
        self.assertTrue(self.store.current(self.store.get_job(second_id)))
        self.assertEqual(len(self.store.history(self.store.get_job(second_id))), 2)

    def test_chat_is_on_demand_and_does_not_overwrite_report(self):
        job_id = self.pipeline.submit(self.request)[0]
        self.pipeline.run_job(job_id)
        before = self.store.get_job(job_id)['result']
        answer = self.pipeline.chat(job_id, self.principal, 'conversation-1', 'Что уточнить?')
        self.assertEqual(answer['report_version'], job_id)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.store.get_job(job_id)['result'], before)
        with self.assertRaises(PermissionError):
            self.pipeline.chat(job_id, Principal('other-user', frozenset({1})), 'conversation-1', 'Чужой чат')
        self.assertEqual(len(self.requests), 3)

    def test_cross_company_denied_before_llm(self):
        job_id = self.pipeline.submit(self.request)[0]
        for method, args in [(self.pipeline.read, ()), (self.pipeline.chat, ('chat', 'question'))]:
            with self.assertRaises(PermissionError):
                method(job_id, Principal('user', frozenset({99})), *args)
        self.assertEqual(len(self.requests), 0)

    def test_atomic_job_claim(self):
        job_id = self.pipeline.submit(self.request)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.store.claim(job_id), range(4)))
        self.assertEqual(sum(claims), 1)

    def test_crashed_lease_can_be_recovered_but_retries_bounded(self):
        job_id = self.pipeline.submit(self.request)[0]
        for _ in range(3):
            self.assertTrue(self.store.claim(job_id))
            with self.store.connect() as db:
                db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (job_id,))
        self.assertFalse(self.store.claim(job_id))
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.get_job(job_id)['status'], 'failed')

    def test_http_contract_and_safe_validation(self):
        with TestClient(create_app(self.pipeline)) as api:
            self.assertEqual(api.post('/rank', json=REQUEST).status_code, 401)
            headers = {'Authorization': 'Bearer internal'}
            response = api.post('/rank', json=REQUEST, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()[0]), {'role', 'kind', 'score', 'insight', 'elements'})
            response = api.post('/v1/jobs', json=REQUEST, headers=headers)
            self.assertEqual(response.status_code, 202)
            job_id = response.json()['job_ids'][0]
            headers.update({'X-User-ID': 'user-1', 'X-Company-ID': '1'})
            self.assertEqual(api.get('/v1/jobs/' + job_id, headers=headers).json()['status'], 'ready')
            headers['X-Company-ID'] = '99'
            self.assertEqual(api.get('/v1/jobs/' + job_id, headers=headers).status_code, 404)
            response = api.post('/rank', json={'secret': 'sensitive'}, headers=headers)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('sensitive', response.text)

    def test_api_budget_is_error_not_empty_matches(self):
        self.replies = [httpx.Response(429, json={'error': {'message': 'Budget has been exceeded'}})]
        with TestClient(create_app(self.pipeline)) as api:
            response = api.post('/rank', json=REQUEST, headers={'Authorization': 'Bearer internal'})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['error']['code'], 'budget_exceeded')

    def test_expired_fact_excluded_and_russian_stems_match(self):
        data = copy.deepcopy(REQUEST)
        data['company']['profile'] = {}
        data['company']['facts'] = [
            {'id': 'old', 'text': 'Оплата перевозки металла', 'source': 'contract-1', 'sourceVersion': 'v1',
             'validTo': '2025-01-01T00:00:00Z'},
            {'id': 'active', 'text': 'Перевозками металлов занимается поставщик', 'source': 'contract-2', 'sourceVersion': 'v2'},
        ]
        request = RankRequest.model_validate(data)
        evidence = Retriever().retrieve(request.news, request.company, 8)
        ids = [e.id for e in evidence.evidence]
        self.assertNotIn('fact:1:old', ids)
        self.assertIn('fact:1:active', ids)

    def test_input_limit_does_not_make_request(self):
        with self.assertRaises(AIError) as caught:
            self.client.complete('decision', [{'role': 'user', 'content': 'x' * 50000}])
        self.assertEqual(caught.exception.code, 'input_limit')
        self.assertEqual(self.requests, [])

    def test_extra_evidence_allows_only_one_secondary_assessment(self):
        class ExpandedRetriever(Retriever):
            def retrieve(inner, news, company, top_k):
                evidence = super().retrieve(news, company, top_k)
                if top_k > 8:
                    evidence.evidence.append(Evidence(id='fact:1:extra', kind='company', text='Дополнительные условия договора',
                                                      source='contract', version='1'))
                else:
                    evidence.dropped_fact_count = 1
                    evidence.truncated = True
                return evidence
        pipeline = Pipeline(self.settings, self.store, self.client, ExpandedRetriever())
        self.replies = [completion({**ASSESSMENT, 'score': 0.5}),
                        completion(ASSESSMENT), completion(REPORT)]
        self.assertEqual(len(pipeline.rank(self.request)), 1)
        self.assertEqual(len(self.requests), 3)
        report_context = json.loads(json.loads(self.requests[2].content)['messages'][1]['content'])
        self.assertIn('fact:1:extra', [e['id'] for e in report_context['evidence']])

    def test_expired_worker_cannot_overwrite_new_claim(self):
        job_id = self.pipeline.submit(self.request)[0]
        self.assertTrue(self.store.claim(job_id))
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (job_id,))
        self.assertTrue(self.store.claim(job_id))
        self.assertFalse(self.store.finish(job_id, 'ready', attempt=1))
        self.assertEqual(self.store.get_job(job_id)['status'], 'running')
        self.assertTrue(self.store.finish(job_id, 'uncertain', attempt=2))

    def test_superseded_pending_job_does_not_spend_budget(self):
        old_id = self.pipeline.submit(self.request)[0]
        data = copy.deepcopy(REQUEST)
        data['news']['summary'] += ' Обновление условий.'
        self.pipeline.submit(RankRequest.model_validate(data))
        self.assertEqual(self.pipeline.run_job(old_id)['status'], 'superseded')
        self.assertEqual(self.requests, [])

    def test_read_pending_does_not_trigger_generation(self):
        job_id = self.pipeline.submit(self.request)[0]
        self.assertEqual(self.pipeline.read(job_id, self.principal)['status'], 'pending')
        self.assertEqual(self.requests, [])

    def test_concurrent_requests_are_limited(self):
        lock = threading.Lock()
        active = 0
        peak = 0
        def respond(request):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return completion('ok')
        client = LLMClient(self.settings, self.store, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        self.addCleanup(client.close)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.complete(client), range(4)))
        self.assertEqual(peak, 2)

    def test_malformed_or_truncated_success_is_rejected(self):
        malformed = httpx.Response(200, json={'choices': [{'index': 0, 'message': None}]})
        truncated = completion(REPORT)
        data = truncated.json()
        data['choices'][0]['finish_reason'] = 'length'
        for response in (malformed, httpx.Response(200, json=data)):
            self.replies = [response]
            with self.assertRaises(AIError):
                self.complete()

    def test_conditional_report_is_ready_before_click(self):
        missing = ['Зафиксирована ли стоимость следующей перевозки?']
        self.replies = [completion({**ASSESSMENT, 'link_evidence_status': 'missing', 'missing_facts': missing}),
                        completion({**REPORT, 'summary': 'Если цена не зафиксирована, доставка может подорожать.',
                                    'missing_facts': missing, 'clarification_question': missing[0]})]
        self.assertEqual(len(self.pipeline.rank(self.request)), 1)
        job_id = self.pipeline.submit(self.request)[0]
        result = self.pipeline.read(job_id, self.principal)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['result']['publication'], 'conditional')
        self.assertEqual(result['result']['report']['clarification_question'], missing[0])
        self.assertEqual(len(self.requests), 2)

    def test_missing_nonessential_number_does_not_hide_ready_analysis(self):
        self.replies = [completion({**ASSESSMENT, 'missing_facts': ['Нет доли доставки в себестоимости.']})]
        self.assertEqual(len(self.pipeline.rank(self.request)), 1)
        self.assertEqual(len(self.requests), 2)

    def test_conflicting_evidence_is_not_published(self):
        self.replies = [completion({**ASSESSMENT, 'link_evidence_status': 'conflicting'})]
        self.assertEqual(self.pipeline.rank(self.request), [])
        self.assertEqual(len(self.requests), 1)

    def test_no_keyword_match_keeps_business_context(self):
        data = copy.deepcopy(REQUEST)
        data['company']['name'] = 'Предприятие'
        data['company']['profile'] = {'Б1': 'Производим промышленное оборудование.'}
        request = RankRequest.model_validate(data)
        result = Retriever().retrieve(request.news, request.company, 8)
        self.assertEqual(result.lexical_matches, 0)
        self.assertIn('profile:1:Б1:0', [e.id for e in result.evidence])
        self.pipeline.rank(request)
        self.assertEqual(len(self.requests), 2)

    def test_future_fact_excluded_and_complete_news_preserved(self):
        data = copy.deepcopy(REQUEST)
        data['news']['body'] = 'Полный текст. ' * 1500
        data['company']['facts'] = [{'id': 'future', 'text': 'Перевозка металла подешевела.',
                                     'source': 'contract', 'sourceVersion': '2', 'observedAt': '2026-11-01T00:00:00Z'}]
        request = RankRequest.model_validate(data)
        result = Retriever().retrieve(request.news, request.company, 8)
        self.assertNotIn('fact:1:future', [e.id for e in result.evidence])
        self.assertEqual(result.evidence[0].text, request.news.text)

    def test_closed_state_survives_new_version_and_is_personal(self):
        old_id = self.pipeline.submit(self.request)[0]
        self.pipeline.run_job(old_id)
        self.pipeline.update_case(old_id, self.principal, CaseStatePatch(workflow='closed', pinned=True, mark_read=True))
        data = copy.deepcopy(REQUEST)
        data['company']['profile']['Б1'] += ' Есть новый договор.'
        new_id = self.pipeline.submit(RankRequest.model_validate(data))[0]
        self.pipeline.run_job(new_id)
        result = self.pipeline.read(new_id, self.principal)
        self.assertEqual(result['user_state']['workflow'], 'closed')
        self.assertTrue(result['user_state']['pinned'])
        self.assertTrue(result['user_state']['has_update'])
        self.assertEqual(result['changes']['changed_facts'], ['profile:Б1'])
        self.assertEqual(result['changes']['previous_version'], old_id)
        other = Principal('user-2', frozenset({1}))
        self.assertEqual(self.pipeline.read(new_id, other)['user_state']['workflow'], 'open')
        with self.assertRaises(PermissionError):
            self.pipeline.update_case(new_id, Principal('outsider', frozenset({9})), CaseStatePatch(pinned=True))

    def test_scenario_chat_does_not_change_company_and_preserves_citations(self):
        job_id = self.pipeline.submit(self.request)[0]
        self.pipeline.run_job(job_id)
        payload = self.store.get_job(job_id)['payload']
        answer = self.pipeline.chat(job_id, self.principal, 'scenario', 'А если цена была бы зафиксирована?')
        self.assertTrue(answer['evidence'])
        self.assertEqual(self.store.get_job(job_id)['payload'], payload)

    def test_http_case_state(self):
        with TestClient(create_app(self.pipeline)) as api:
            job_id = self.pipeline.submit(self.request)[0]
            headers = {'Authorization': 'Bearer internal', 'X-User-ID': 'user-1', 'X-Company-ID': '1'}
            response = api.patch('/v1/jobs/' + job_id + '/state', headers=headers,
                                 json={'workflow': 'watching', 'pinned': True, 'mark_read': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['workflow'], 'watching')

    def test_demo_does_not_read_local_credentials(self):
        from orchestrator.__main__ import main
        with patch('orchestrator.__main__.load_settings', side_effect=AssertionError('Unexpected secret read')):
            with patch('builtins.print'):
                self.assertEqual(main(['demo']), 0)

    def test_saved_chat_can_be_read_without_generation(self):
        job_id = self.pipeline.submit(self.request)[0]
        self.pipeline.run_job(job_id)
        self.pipeline.chat(job_id, self.principal, 'saved-chat', 'Что уточнить?')
        with TestClient(create_app(self.pipeline)) as api:
            headers = {'Authorization': 'Bearer internal', 'X-User-ID': 'user-1', 'X-Company-ID': '1'}
            response = api.get('/v1/conversations', headers=headers)
            self.assertEqual(response.json()[0]['id'], 'saved-chat')
            response = api.get('/v1/conversations/saved-chat', headers=headers)
            self.assertEqual(len(response.json()['messages']), 2)
            headers['X-User-ID'] = 'different-user'
            self.assertEqual(api.get('/v1/conversations/saved-chat', headers=headers).status_code, 404)
        self.assertEqual(len(self.requests), 3)


class ConfigTests(unittest.TestCase):
    def test_env_file_and_process_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env.local'
            path.write_text('AI_API_KEY=sk-test\nAI_DEFAULT_MODEL=moonshotai/kimi-k2.6\nAI_CHAT_MODEL=\n')
            with patch.dict(os.environ, {'AI_DEFAULT_MODEL': 'z-ai/glm-5.3-flash'}, clear=True):
                settings = load_settings(path)
            self.assertEqual(settings.model_for('chat'), 'z-ai/glm-5.3-flash')
            self.assertNotIn('sk-test', repr(settings))

    def test_missing_key_fails_without_network(self):
        with self.assertRaises(ConfigurationError):
            Settings().require_key()

    def test_invalid_model_error_never_echoes_secret(self):
        with patch.dict(os.environ, {'AI_DEFAULT_MODEL': 'sk-accidental-secret'}, clear=True):
            with self.assertRaises(ConfigurationError) as caught:
                load_settings(Path('/does-not-exist'))
        self.assertNotIn('sk-accidental-secret', str(caught.exception))

    def test_all_six_model_ids_accepted(self):
        models = ['google/gemma-4-26b-a4b-it', 'z-ai/glm-5.3-flash', 'qwen/qwen3.6-35b-a3b',
                  'deepseek/deepseek-v4.1-flash', 'qwen/qwen3-vl-30b-a3b-instruct', 'moonshotai/kimi-k2.6']
        for model in models:
            self.assertEqual(Settings(default_model=model).model_for('decision'), model)


if __name__ == '__main__':
    unittest.main()
