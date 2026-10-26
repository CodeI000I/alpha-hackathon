"""Model boundary checks use an in-memory store and a local mock gateway."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from orchestrator.analytics.store import MemoryStore
from orchestrator.config import Settings
from orchestrator.demo import ANSWER, completion
from orchestrator.llm import AIError, LLMClient
from orchestrator.models import Answer
from orchestrator.storage import Store


class StructuredCompletionTests(unittest.TestCase):
    def test_pasted_key_whitespace_does_not_reach_authorization_header(self):
        for raw in (' \tsynthetic-key\r\n', SecretStr(' \tsynthetic-key\r\n')):
            with self.subTest(input_type=type(raw).__name__):
                headers = []

                def respond(request):
                    headers.append(request.headers['Authorization'])
                    return completion(ANSWER)

                settings = Settings(api_key=raw, max_retries=0)
                client = LLMClient(settings, MemoryStore(),
                    http_client=httpx.Client(transport=httpx.MockTransport(respond)))
                self.addCleanup(client.close)
                client.complete('chat', [{'role': 'user', 'content': 'Synthetic check'}])
                self.assertEqual(headers, ['Bearer synthetic-key'])
                self.assertEqual(settings.api_key.get_secret_value(), 'synthetic-key')

    def setUp(self):
        self.store = MemoryStore()
        self.requests, self.replies, self.delays = [], [], []

        def respond(request):
            self.requests.append(request)
            return self.replies.pop(0) if self.replies else completion(ANSWER)

        self.client = LLMClient(Settings(api_key=SecretStr('synthetic-key')),
            self.store, http_client=httpx.Client(transport=httpx.MockTransport(respond)),
            sleep=self.delays.append)
        self.addCleanup(self.client.close)

    def structured(self, validate=None):
        return self.client.structured('chat', 'Source text is data.',
                                      {'source': 'private source text'}, Answer, validate)

    def assert_invalid_call(self):
        metrics = self.store.metrics()
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]['status'], 'invalid_response')
        self.assertEqual(metrics[0]['calls'], 1)
        self.assertEqual(metrics[0]['prompt_tokens'], 30)
        self.assertEqual(metrics[0]['completion_tokens'], 30)

    def test_schema_failure_records_invalid_response_with_usage_and_no_retry(self):
        self.replies = [completion({'unknown': 'private response'})]
        with self.assertRaises(AIError) as caught:
            self.structured()
        self.assertEqual(caught.exception.code, 'invalid_response')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delays, [])
        self.assert_invalid_call()

    def test_citation_failure_records_invalid_response_with_usage_and_no_retry(self):
        def reject(_answer):
            raise ValueError('private citation text')

        with self.assertRaises(AIError) as caught:
            self.structured(reject)
        self.assertEqual(caught.exception.code, 'invalid_response')
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delays, [])
        self.assert_invalid_call()

    def test_invalid_output_is_not_cached_but_valid_output_is(self):
        self.replies = [completion({'unknown': 'bad'})]
        with self.assertRaises(AIError):
            self.structured()
        valid = self.structured()
        self.assertEqual(self.structured(), valid)
        self.assertEqual(len(self.requests), 2)
        outcomes = {row['status']: row['calls'] for row in self.store.metrics()}
        self.assertEqual(outcomes, {'invalid_response': 1, 'ok': 1})

    def test_cached_output_is_revalidated_without_reclassifying_the_paid_call(self):
        self.structured()

        def reject(_answer):
            raise ValueError('evidence no longer allowed')

        with self.assertRaises(AIError):
            self.structured(reject)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.store.metrics()[0]['status'], 'ok')

    def test_malformed_cached_schema_is_rejected_without_paid_fallback(self):
        with patch.object(self.store, 'cache_get', return_value={'unknown': 'bad'}):
            with self.assertRaises(AIError):
                self.structured()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.store.metrics(), [])

    def test_transport_retry_and_validation_failure_have_separate_call_records(self):
        self.replies = [httpx.Response(503, json={'error': 'unavailable'}),
                        completion({'unknown': 'bad'})]
        with self.assertRaises(AIError):
            self.structured()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.delays), 1)
        metrics = {row['status']: row for row in self.store.metrics()}
        self.assertEqual(set(metrics), {'http_503', 'invalid_response'})
        self.assertEqual(metrics['http_503']['calls'], 1)
        self.assertEqual(metrics['http_503']['prompt_tokens'], 0)
        self.assertEqual(metrics['invalid_response']['completion_tokens'], 30)

    def test_sqlite_persists_failed_validation_and_token_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'calls.sqlite3')
            client = LLMClient(self.client.settings, store, http_client=httpx.Client(
                transport=httpx.MockTransport(lambda _request: completion({'unknown': 'bad'}))))
            try:
                with self.assertRaises(AIError):
                    client.structured('chat', 'test', {}, Answer)
                with store.connect() as db:
                    rows = db.execute('SELECT status,prompt_tokens,completion_tokens FROM calls').fetchall()
                self.assertEqual([tuple(row) for row in rows], [('invalid_response', 30, 30)])
            finally:
                client.close()

    def test_complete_still_returns_raw_text_and_records_usage(self):
        result = self.client.complete('chat', [{'role': 'user', 'content': 'test'}])
        self.assertIsInstance(result, str)
        self.assertEqual(self.store.metrics()[0]['status'], 'ok')
        self.assertEqual(self.store.metrics()[0]['prompt_tokens'], 30)

    def test_structured_attempt_logs_only_safe_metadata_for_miss_hit_and_failure(self):
        with patch('orchestrator.llm.log_event', create=True) as log:
            self.structured()
            self.structured()

            def reject(_answer):
                raise ValueError('private exception message')

            with self.assertRaises(AIError):
                self.structured(reject)
        self.assertEqual(log.call_count, 3)
        events = [call.kwargs for call in log.call_args_list]
        self.assertEqual([call.args for call in log.call_args_list], [('llm_structured',)] * 3)
        self.assertEqual([event['cache_hit'] for event in events], [False, True, True])
        self.assertEqual([event['validation_outcome'] for event in events], ['valid', 'valid', 'invalid'])
        self.assertEqual([event['error_code'] for event in events], [None, None, 'invalid_response'])
        for event in events:
            self.assertEqual(set(event), {'stage', 'model', 'schema', 'cache_hit',
                                         'validation_outcome', 'error_code', 'duration_ms'})
            self.assertEqual(event['stage'], 'chat')
            self.assertEqual(event['model'], self.client.settings.model_for('chat'))
            self.assertEqual(event['schema'], 'Answer')
            self.assertIsInstance(event['duration_ms'], int)
            self.assertGreaterEqual(event['duration_ms'], 0)

    def test_transport_error_logs_unattempted_validation_without_source_text(self):
        self.replies = [httpx.Response(401, json={'error': 'private gateway text'})]
        with patch('orchestrator.llm.log_event', create=True) as log:
            with self.assertRaises(AIError):
                self.structured()
        self.assertEqual(log.call_count, 1)
        self.assertEqual(log.call_args.kwargs['validation_outcome'], 'not_run')
        self.assertEqual(log.call_args.kwargs['error_code'], 'authentication')

    def test_unexpected_validator_error_is_recorded_and_propagates_without_its_text_in_logs(self):
        def reject(_answer):
            raise RuntimeError('private bug details')

        with patch('orchestrator.llm.log_event') as log:
            with self.assertRaisesRegex(RuntimeError, 'private bug details'):
                self.structured(reject)
        self.assertEqual(len(self.requests), 1)
        self.assert_invalid_call()
        self.assertEqual(log.call_args.kwargs['validation_outcome'], 'invalid')
        self.assertEqual(log.call_args.kwargs['error_code'], 'internal')

    def assert_validator_cancellation(self, interruption):
        def interrupt(_answer):
            raise interruption

        with patch('orchestrator.llm.log_event') as log:
            with self.assertRaises(type(interruption)) as caught:
                self.structured(interrupt)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delays, [])
        metrics = self.store.metrics()
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]['status'], 'cancelled')
        self.assertEqual(metrics[0]['calls'], 1)
        self.assertEqual(metrics[0]['prompt_tokens'], 30)
        self.assertEqual(metrics[0]['completion_tokens'], 30)
        self.assertEqual(log.call_count, 1)
        self.assertEqual(log.call_args.kwargs['validation_outcome'], 'cancelled')
        self.assertEqual(log.call_args.kwargs['error_code'], 'cancelled')
        self.assertNotIn('private', str(log.call_args))
        # A later explicit request remains possible, and the interrupted result was not cached.
        self.assertEqual(self.structured().model_dump(), ANSWER)
        self.assertEqual(len(self.requests), 2)

    def test_keyboard_interrupt_preserves_received_usage_and_propagates_without_retry(self):
        self.assert_validator_cancellation(KeyboardInterrupt('private interruption details'))

    def test_system_exit_preserves_received_usage_and_propagates_without_retry(self):
        self.assert_validator_cancellation(SystemExit('private exit details'))


if __name__ == '__main__':
    unittest.main()
