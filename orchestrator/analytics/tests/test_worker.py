import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from orchestrator.analytics.knowledge import KnowledgeService
from orchestrator.analytics.models import Scope
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import MemoryStore
from orchestrator.analytics.tests.test_service import FakeModel, NOW
from orchestrator.analytics.tests.test_knowledge import FixtureLLM


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.store, self.model = MemoryStore(), FakeModel()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.knowledge_model = FixtureLLM({'facts': [], 'edges': []})
        knowledge = KnowledgeService(self.store, self.knowledge_model, object_dir=Path(self.temp.name))
        self.service = AnalyticsService(self.store, self.model, knowledge=knowledge, clock=lambda: NOW, debounce_seconds=0)
        self.scope = Scope(tenant_id='alpha', company_id='1')
        self.backend = Mock()
        self.backend.companies.return_value = [{'id': 1, 'name': 'Компания', 'inn': '1234567890',
                                                'profile': {'Б1': 'supplier floating price'}, 'roles': ['procurement']}]
        self.backend.files.return_value = [{'id': 3, 'company_id': 1, 'filename': 'contract.txt',
                                           'content_type': 'text/plain', 'size_bytes': 8, 'object_key': 'company/1/file'}]

    def test_document_sync_and_restart_do_not_extract_or_download_twice(self):
        from orchestrator.analytics.worker import run_once
        requests = []
        def transport(request):
            requests.append(request)
            self.assertEqual(request.url.path, '/api/v1/internal/files/3/content')
            self.assertEqual(request.headers['Authorization'], 'Bearer internal-test')
            return httpx.Response(200, content=b'contract')
        with httpx.Client(base_url='http://backend.test', transport=httpx.MockTransport(transport)) as client:
            run_once(self.service, self.backend, client, internal_token='internal-test')
            run_once(self.service, self.backend, client, internal_token='internal-test')
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.knowledge_model.calls, 1)
        record = self.store.get('integration_file', '3', **self.scope.db())
        self.assertEqual(record.payload['status'], 'ready')
        self.assertTrue(Path(self.store.get('document', 'backend-file:3', **self.scope.db()).payload['document']['original_path']).is_file())
        self.assertTrue(self.service.get_company_situation(self.scope.model_copy(update={'role': 'procurement'}))['current'])

    def test_document_failure_is_persisted_and_other_companies_can_progress(self):
        from orchestrator.analytics.worker import run_once
        with httpx.Client(base_url='http://backend.test', transport=httpx.MockTransport(
                lambda request: httpx.Response(503))) as client:
            result = run_once(self.service, self.backend, client, internal_token='internal-test')
        record = self.store.get('integration_file', '3', **self.scope.db())
        self.assertEqual(record.payload['status'], 'queued')
        self.assertEqual(record.payload['attempts'], 1)
        self.assertEqual(result['companies'], 1)
        self.assertEqual(self.knowledge_model.calls, 0)

    def test_oversized_file_never_downloaded(self):
        from orchestrator.analytics.worker import run_once
        self.backend.files.return_value[0]['size_bytes'] = 100 * 1024 * 1024
        with httpx.Client(base_url='http://backend.test', transport=httpx.MockTransport(
                lambda request: self.fail('oversized file was downloaded'))) as client:
            run_once(self.service, self.backend, client, internal_token='internal-test')
        self.assertEqual(self.store.get('integration_file', '3', **self.scope.db()).payload['status'], 'failed')

    def test_document_status_and_explicit_refresh_retry(self):
        from orchestrator.analytics.worker import run_once
        from orchestrator.analytics.app import create_app
        self.backend.files.return_value[0]['size_bytes'] = 100 * 1024 * 1024
        with httpx.Client(base_url='http://backend.test', transport=httpx.MockTransport(
                lambda request: self.fail('unexpected download'))) as client:
            run_once(self.service, self.backend, client, internal_token='internal-test')
        headers = {'Authorization': 'Bearer test-service', 'X-User-ID': '1', 'X-Company-ID': '1',
                   'X-Role': 'procurement', 'X-Tenant-ID': 'alpha'}
        with TestClient(create_app(service=self.service, service_token='test-service')) as client:
            response = client.get('/v1/analytics/documents', headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()[0]['status'], 'failed')
            self.assertNotIn('fingerprint', response.text)
            response = client.post('/v1/analytics/refresh', headers=headers, json={'retry_failed': True})
            self.assertEqual(response.status_code, 202)
        self.assertEqual(self.store.get('integration_file', '3', **self.scope.db()).payload['status'], 'queued')

    def test_missing_model_key_pauses_jobs_without_exhausting_attempts(self):
        from orchestrator.analytics.runtime import UnconfiguredModel
        from orchestrator.config import Settings
        from orchestrator.analytics.tests.test_service import ServiceTests
        from orchestrator.analytics.integration import sync_company
        sync_company(self.service, self.backend.companies.return_value[0])
        self.service.ingest_news(ServiceTests.article(self))
        self.service.llm = UnconfiguredModel(Settings())
        self.service.reprocess_company(self.scope, reason='missing-key')
        result = self.service.process_jobs(self.scope)
        self.assertEqual(result[-1]['status'], 'queued')
        self.assertEqual(result[-1]['attempts'], 0)

    def test_retry_document_lock_contention_returns_controlled_busy(self):
        from orchestrator.analytics.app import create_app
        from orchestrator.analytics.store import StoreBusy
        self.store.put('integration_file', '3', {'status': 'failed'}, **self.scope.db())
        headers = {'Authorization': 'Bearer test-service', 'X-User-ID': '1', 'X-Company-ID': '1',
                   'X-Role': 'procurement', 'X-Tenant-ID': 'alpha'}
        with (TestClient(create_app(service=self.service, service_token='test-service')) as client,
              patch.object(self.store, 'lock', side_effect=StoreBusy('occupied'))):
            response = client.post('/v1/analytics/refresh', headers=headers, json={'retry_failed': True})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['detail']['code'], 'busy')


if __name__ == '__main__':
    unittest.main()
