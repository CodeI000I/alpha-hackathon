import json
import os
import tempfile
import unittest
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


if __name__ == '__main__':
    unittest.main()
