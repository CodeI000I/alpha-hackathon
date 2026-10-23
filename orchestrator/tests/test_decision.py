import json
import hashlib
import runpy
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from orchestrator.decision import (
    DecisionRouter,
    LLMRoutingDecisionProvider,
    RoutingDecision,
    SystemOneDecisionProvider,
    SystemOneUnavailable,
    build_decision_router,
)
from orchestrator.config import Settings, load_settings
from orchestrator.storage import Store


DECISION = RoutingDecision(relevance='relevant', kind='risk', priority='high')


class SystemOneDecisionProviderTests(unittest.TestCase):
    def test_probe_and_decide_use_systemone_contract_and_bearer_auth(self):
        requests = []

        def respond(request):
            requests.append(request)
            self.assertEqual(request.headers['authorization'], 'Bearer ts-test')
            if request.url.path == '/v1/models':
                return httpx.Response(200, json={'models': [
                    {'name': 'jev-latest', 'description': 'Jev', 'release_date': '2026-09-15'},
                ]})
            body = json.loads(request.content)
            self.assertEqual(body['model'], 'jev-latest')
            self.assertEqual(body['state'], {'news': {'title': 'Рост тарифов'}})
            self.assertEqual(set(body['questions']), {'relevance', 'kind', 'priority'})
            return httpx.Response(200, json={
                'model': 'jev-latest',
                'answers': {
                    'relevance': {'type': 'choice', 'choice': 'relevant', 'confidence': 0.9,
                                  'probabilities': {'relevant': 0.9, 'irrelevant': 0.05, 'unknown': 0.05}},
                    'kind': {'type': 'choice', 'choice': 'risk', 'confidence': 0.8,
                             'probabilities': {'risk': 0.8, 'opportunity': 0.1, 'mixed': 0.05,
                                               'event': 0.04, 'unknown': 0.01}},
                    'priority': {'type': 'choice', 'choice': 'high', 'confidence': 0.7,
                                 'probabilities': {'low': 0.1, 'medium': 0.2,
                                                   'high': 0.7, 'unknown': 0.0}},
                },
                'usage': {'input_tokens': 100, 'output_tokens': 12},
            })

        provider = SystemOneDecisionProvider(
            base_url='https://api.typesafe.ai/', model='jev-latest',
            api_key=SecretStr('ts-test'),
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        self.addCleanup(provider.close)

        provider.probe()
        self.assertEqual(provider.decide({'news': {'title': 'Рост тарифов'}}), DECISION)
        self.assertEqual([request.url.path for request in requests], ['/v1/models', '/v1/systemone'])

    def test_probe_rejects_model_unavailable_to_account(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'models': []})))
        provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                                             SecretStr('ts-test'), http_client=client)
        self.addCleanup(provider.close)

        with self.assertRaises(SystemOneUnavailable) as caught:
            provider.probe()

        self.assertTrue(caught.exception.permanent)
        self.assertEqual(caught.exception.code, 'model_unavailable')

    def test_auth_error_is_permanent_and_does_not_expose_response(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={'detail': 'secret diagnostic'})))
        provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                                             SecretStr('ts-test'), http_client=client)
        self.addCleanup(provider.close)

        with self.assertRaises(SystemOneUnavailable) as caught:
            provider.probe()

        self.assertTrue(caught.exception.permanent)
        self.assertEqual(caught.exception.code, 'authentication')
        self.assertNotIn('secret diagnostic', str(caught.exception))

    def test_transport_and_timeout_status_are_transient(self):
        failures = [
            httpx.RemoteProtocolError('broken response'),
            httpx.Response(408, json={'detail': 'timeout'}),
        ]
        for failure in failures:
            def respond(request, outcome=failure):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            provider = SystemOneDecisionProvider(
                'https://api.typesafe.ai', 'jev-latest', SecretStr('ts-test'),
                http_client=httpx.Client(transport=httpx.MockTransport(respond)))
            self.addCleanup(provider.close)

            with self.subTest(failure=type(failure).__name__):
                with self.assertRaises(SystemOneUnavailable) as caught:
                    provider.probe()
                self.assertEqual(caught.exception.code, 'unavailable')
                self.assertFalse(caught.exception.permanent)

    def test_injected_http_client_still_uses_configured_timeout(self):
        observed = []

        def respond(request):
            observed.append(request.extensions['timeout'])
            return httpx.Response(200, json={'models': [
                {'name': 'jev-latest', 'description': 'Jev', 'release_date': '2026-09-15'},
            ]})

        client = httpx.Client(timeout=None, transport=httpx.MockTransport(respond))
        provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
            SecretStr('ts-test'), timeout_seconds=0.25, http_client=client)
        self.addCleanup(provider.close)

        provider.probe()

        self.assertEqual(observed[0]['read'], 0.25)

    def test_injected_client_cannot_follow_redirect_with_credentials(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(302, headers={'location': 'https://attacker.example/collect'},
                                  json={'models': [{'name': 'jev-latest'}]})

        client = httpx.Client(follow_redirects=True, transport=httpx.MockTransport(respond))
        provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
            SecretStr('ts-test'), http_client=client)
        self.addCleanup(provider.close)

        with self.assertRaises(SystemOneUnavailable) as caught:
            provider.probe()

        self.assertEqual(caught.exception.code, 'invalid_response')
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), 'https://api.typesafe.ai/v1/models')
        self.assertEqual(requests[0].headers['authorization'], 'Bearer ts-test')

    def test_decision_validates_required_usage_and_answer_shape_but_accepts_model_alias_resolution(self):
        good = {
            'model': 'jev-2026-09-15',
            'answers': {
                'relevance': {'type': 'choice', 'choice': 'relevant'},
                'kind': {'type': 'choice', 'choice': 'risk'},
                'priority': {'type': 'choice', 'choice': 'high'},
            },
            'usage': {'input_tokens': 11, 'output_tokens': 3},
        }
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=good)))
        provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                                             SecretStr('ts-test'), http_client=client)
        self.addCleanup(provider.close)
        self.assertEqual(provider.decide({'news': 1}), DECISION)

        for invalid in (
            {**good, 'usage': {'input_tokens': '11', 'output_tokens': 3}},
            {**good, 'usage': {'input_tokens': -1, 'output_tokens': 3}},
            {**good, 'answers': {**good['answers'], 'kind': None}},
            {key: value for key, value in good.items() if key != 'model'},
        ):
            with self.subTest(invalid=invalid):
                bad_client = httpx.Client(transport=httpx.MockTransport(
                    lambda request, body=invalid: httpx.Response(200, json=body)))
                bad_provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                    SecretStr('ts-test'), http_client=bad_client)
                self.addCleanup(bad_provider.close)
                with self.assertRaises(SystemOneUnavailable) as caught:
                    bad_provider.decide({'news': 1})
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_success_records_usage_in_existing_call_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'calls.sqlite3')
            response = {'model': 'jev-2026-09-15', 'answers': {
                'relevance': {'type': 'choice', 'choice': 'relevant'},
                'kind': {'type': 'choice', 'choice': 'risk'},
                'priority': {'type': 'choice', 'choice': 'high'},
            }, 'usage': {'input_tokens': 11, 'output_tokens': 3}}
            client = httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response)))
            provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                SecretStr('ts-test'), http_client=client, store=store, requests_per_minute=5)
            self.addCleanup(provider.close)

            self.assertEqual(provider.decide({'news': 1}), DECISION)

            with store.connect() as db:
                call = db.execute('SELECT account,stage,model,status,prompt_tokens,completion_tokens FROM calls').fetchone()
            self.assertIsNotNone(call)
            self.assertEqual(call['account'], hashlib.sha256(
                b'https://api.typesafe.ai\0ts-test').hexdigest())
            self.assertEqual(tuple(call[name] for name in ('stage', 'model', 'status', 'prompt_tokens',
                                                              'completion_tokens')),
                             ('systemone', 'jev-latest', 'ok', 11, 3))

    def test_rate_limit_skips_decision_post_and_uses_fallback(self):
        class LimitedStore:
            def __init__(self):
                self.reservations = []
                self.recorded = []

            def reserve_call(self, *args):
                self.reservations.append(args)
                return None, 123.0

            def record_call(self, *args):
                self.recorded.append(args)

        requests, store = [], LimitedStore()

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={'models': [
                {'name': 'jev-latest', 'description': 'Jev', 'release_date': '2026-09-15'},
            ]})

        client = httpx.Client(transport=httpx.MockTransport(respond))
        provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
            SecretStr('ts-test'), http_client=client, store=store, requests_per_minute=7)
        self.addCleanup(provider.close)
        fallback = FakeProvider('llm', [DECISION])
        router = DecisionRouter(provider, fallback)

        outcome = router.decide({'news': 1})

        self.assertEqual(outcome.provider, 'llm')
        self.assertEqual([request.url.path for request in requests], ['/v1/models'])
        self.assertEqual(fallback.calls, 1)
        account, stage, model, rpm, now = store.reservations[0]
        self.assertNotIn('ts-test', account)
        self.assertEqual((stage, model, rpm), ('systemone', 'jev-latest', 7))
        self.assertIsInstance(now, float)
        self.assertEqual(store.recorded, [])

    def test_failure_status_is_recorded_without_provider_body_or_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'calls.sqlite3')
            client = httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(503, json={'detail': 'private vendor response'})))
            provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                SecretStr('ts-test'), http_client=client, store=store)
            self.addCleanup(provider.close)

            with self.assertRaises(SystemOneUnavailable) as caught:
                provider.decide({'news': 1})

            self.assertNotIn('private vendor response', str(caught.exception))
            with store.connect() as db:
                call = db.execute('SELECT status FROM calls').fetchone()
            self.assertEqual(call['status'], 'http_503')

    def test_invalid_response_is_recorded_in_existing_call_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'calls.sqlite3')
            client = httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={'model': 'jev-latest', 'answers': {}})))
            provider = SystemOneDecisionProvider('https://api.typesafe.ai', 'jev-latest',
                SecretStr('ts-test'), http_client=client, store=store)
            self.addCleanup(provider.close)

            with self.assertRaises(SystemOneUnavailable) as caught:
                provider.decide({'news': 1})

            self.assertEqual(caught.exception.code, 'invalid_response')
            with store.connect() as db:
                call = db.execute('SELECT status FROM calls').fetchone()
            self.assertEqual(call['status'], 'invalid_response')

    def test_external_endpoint_requires_https_even_without_credentials(self):
        with self.assertRaises(ValueError):
            SystemOneDecisionProvider('http://systemone.internal', 'jev-latest',
                                      SecretStr(''))

    def test_oversized_state_is_rejected_before_network(self):
        requests = []
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(500)))
        provider = SystemOneDecisionProvider(
            'https://api.typesafe.ai', 'jev-latest', SecretStr('ts-test'),
            max_input_chars=10, http_client=client)
        self.addCleanup(provider.close)

        with self.assertRaises(ValueError):
            provider.decide({'news': 'too long'})

        self.assertEqual(requests, [])


class SystemOneConfigTests(unittest.TestCase):
    def test_systemone_settings_load_without_exposing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env.local'
            path.write_text(
                'AI_SYSTEMONE_URL=https://api.typesafe.ai\n'
                'AI_SYSTEMONE_MODEL=jev-latest\n'
                'AI_SYSTEMONE_API_KEY=ts-test-secret\n'
                'AI_SYSTEMONE_TIMEOUT_SECONDS=8\n'
                'AI_SYSTEMONE_COOLDOWN_SECONDS=45\n'
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(path)

        self.assertEqual(settings.systemone_url, 'https://api.typesafe.ai')
        self.assertEqual(settings.systemone_model, 'jev-latest')
        self.assertEqual(settings.systemone_timeout_seconds, 8)
        self.assertEqual(settings.systemone_cooldown_seconds, 45)
        self.assertNotIn('ts-test-secret', repr(settings))

    def test_builder_passes_store_and_systemone_rate_limit_to_primary(self):
        settings = Settings(systemone_url='https://api.typesafe.ai', requests_per_minute=9)
        store, client = object(), object()
        with patch('orchestrator.decision.SystemOneDecisionProvider') as provider_class:
            build_decision_router(settings, FakeProvider('llm', []), store=store,
                                  http_client=client)

        provider_class.assert_called_once_with(settings.systemone_url, settings.systemone_model,
            settings.systemone_api_key, timeout_seconds=settings.systemone_timeout_seconds,
            max_input_chars=settings.max_input_chars, http_client=client, store=store,
            requests_per_minute=9)


class FakeProvider:
    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.probes = 0
        self.calls = 0

    def probe(self):
        self.probes += 1
        outcome = self.outcomes[0]
        if isinstance(outcome, Exception):
            self.outcomes.pop(0)
            raise outcome

    def decide(self, state):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class DecisionRouterTests(unittest.TestCase):
    def test_unconfigured_systemone_uses_llm_without_network(self):
        fallback = FakeProvider('llm', [DECISION])
        router = build_decision_router(Settings(), fallback)

        outcome = router.decide({'news': 1})

        self.assertEqual(outcome.provider, 'llm')
        self.assertEqual(outcome.decision, DECISION)

    def test_router_closes_owned_primary_client(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'models': []})))
        settings = Settings(systemone_url='https://api.typesafe.ai')
        router = build_decision_router(settings, FakeProvider('llm', [DECISION]),
                                       http_client=client)

        router.close()

        self.assertTrue(client.is_closed)

    def test_permanent_primary_failure_uses_fallback_without_reprobing(self):
        now = [100.0]
        primary = FakeProvider('systemone', [
            SystemOneUnavailable('authentication', 'Primary rejected credentials', permanent=True),
        ])
        fallback = FakeProvider('llm', [DECISION, DECISION, DECISION])
        router = DecisionRouter(primary, fallback, cooldown_seconds=30, clock=lambda: now[0])

        first = router.decide({'news': 1})
        second = router.decide({'news': 2})
        now[0] = 1000
        third = router.decide({'news': 3})

        self.assertEqual((first.provider, second.provider, third.provider), ('llm', 'llm', 'llm'))
        self.assertEqual(primary.probes, 1)
        self.assertEqual(primary.calls, 0)
        self.assertEqual(fallback.calls, 3)

    def test_fallback_log_excludes_input_and_secret_details(self):
        primary = FakeProvider('systemone', [
            SystemOneUnavailable('authentication', 'secret detail', permanent=True),
        ])
        fallback = FakeProvider('llm', [DECISION])

        with self.assertLogs('orchestrator.decision', level='WARNING') as logs:
            DecisionRouter(primary, fallback).decide({'title': 'private company news'})

        output = '\n'.join(logs.output)
        self.assertIn('decision_provider_fallback', output)
        self.assertEqual(logs.records[0].provider, 'systemone')
        self.assertEqual(logs.records[0].error_code, 'authentication')
        self.assertTrue(logs.records[0].permanent)
        self.assertNotIn('private company news', output)
        self.assertNotIn('secret detail', output)

    def test_transient_failure_opens_circuit_then_retries_after_cooldown(self):
        now = [100.0]
        primary = FakeProvider('systemone', [
            SystemOneUnavailable('unavailable', 'Temporary failure'), DECISION,
        ])
        fallback = FakeProvider('llm', [DECISION, DECISION])
        router = DecisionRouter(primary, fallback, cooldown_seconds=30, clock=lambda: now[0])

        self.assertEqual(router.decide({}).provider, 'llm')
        now[0] = 120
        self.assertEqual(router.decide({}).provider, 'llm')
        now[0] = 131
        self.assertEqual(router.decide({}).provider, 'systemone')
        self.assertEqual(primary.probes, 2)
        self.assertEqual(primary.calls, 1)

    def test_business_decision_from_primary_is_not_a_fallback_condition(self):
        irrelevant = RoutingDecision(relevance='irrelevant', kind='event', priority='low')
        primary = FakeProvider('systemone', [irrelevant])
        fallback = FakeProvider('llm', [DECISION])

        outcome = DecisionRouter(primary, fallback).decide({})

        self.assertEqual(outcome.decision, irrelevant)
        self.assertEqual(outcome.provider, 'systemone')
        self.assertEqual(fallback.calls, 0)


class LLMRoutingDecisionProviderTests(unittest.TestCase):
    def test_existing_llm_client_is_adapted_to_the_same_schema(self):
        class FakeLLM:
            def structured(inner, stage, instruction, context, schema, validate=None):
                self.assertEqual(stage, 'decision')
                self.assertIs(schema, RoutingDecision)
                self.assertEqual(context, {'news': 1})
                return DECISION

        provider = LLMRoutingDecisionProvider(FakeLLM())

        self.assertEqual(provider.decide({'news': 1}), DECISION)


class DecisionCLITests(unittest.TestCase):
    def test_check_systemone_probes_without_requiring_llm_key(self):
        from orchestrator.__main__ import main

        settings = Settings(systemone_url='https://api.typesafe.ai',
                            systemone_model='jev-latest',
                            systemone_api_key=SecretStr('ts-test-secret'))
        with patch('orchestrator.__main__.load_settings', return_value=settings):
            with patch('orchestrator.__main__.SystemOneDecisionProvider') as provider_class:
                with patch('builtins.print') as output:
                    self.assertEqual(main(['check-systemone']), 0)

        provider_class.return_value.probe.assert_called_once_with()
        provider_class.return_value.close.assert_called_once_with()
        self.assertNotIn('ts-test-secret', str(output.call_args_list))

    def test_check_systemone_failure_is_a_clean_cli_error(self):
        settings = Settings(systemone_url='https://api.typesafe.ai',
                            systemone_model='jev-latest',
                            systemone_api_key=SecretStr('ts-test-secret'))
        stderr = StringIO()
        with patch('orchestrator.config.load_settings', return_value=settings), \
             patch('orchestrator.decision.SystemOneDecisionProvider.probe',
                   side_effect=SystemOneUnavailable('unavailable', 'Safe provider error')), \
             patch.object(sys, 'argv', ['orchestrator', 'check-systemone']), \
             redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_module('orchestrator.__main__', run_name='__main__')

        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(stderr.getvalue().strip(), 'Safe provider error')
        self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
