"""The public Go wire contract reaches the real analytics service without a live model."""

import unittest
import base64
from unittest.mock import patch

from fastapi.testclient import TestClient

from orchestrator.analytics.models import CompanyFact, CompanyProfile, Scope
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import MemoryStore
from orchestrator.analytics.tests.test_service import FakeModel, NOW


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store, self.model = MemoryStore(), FakeModel()
        self.service = AnalyticsService(self.store, self.model, clock=lambda: NOW, debounce_seconds=0)
        self.headers = {'Authorization': 'Bearer test-service', 'X-User-ID': '7',
                        'X-Company-ID': '42', 'X-Role': 'procurement', 'X-Tenant-ID': 'alpha'}
        self.request = {
            'company': {'id': 42, 'inn': '1234567890', 'name': 'Завод',
                        'profile': {'Б1': 'supplier floating price'}},
            'roles': ['procurement'],
            'news': {'id': 99, 'revision': 1, 'sourceId': 'manual', 'title': 'Изменение цены',
                     'summary': '', 'body': 'Поставщик изменил прайс.', 'url': 'https://example.com/news',
                     'publishedAt': NOW.isoformat()},
        }

    def app(self):
        from orchestrator.analytics.app import create_app
        return create_app(service=self.service, service_token='test-service')

    def test_rank_builds_scoped_issue_and_reading_does_not_call_model(self):
        with TestClient(self.app()) as client:
            response = client.post('/rank', headers=self.headers, json=self.request)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()[0]['role'], 'procurement')
            self.assertEqual(response.json()[0]['kind'], 'risk')
            count = len(self.model.calls)
            self.assertEqual(client.post('/rank', headers=self.headers, json=self.request).status_code, 200)
            issues = client.get('/v1/analytics/issues', headers=self.headers).json()
            self.assertEqual(len(issues), 1)
            response = client.get('/v1/analytics/situation', headers=self.headers)
            self.assertTrue(response.json()['current'])
            self.assertEqual(len(self.model.calls), count)
            other = dict(self.headers, **{'X-Company-ID': '43'})
            self.assertEqual(client.get('/v1/analytics/issues/' + issues[0]['issue_id'], headers=other).status_code, 404)

    def test_service_token_and_scope_required_and_health_open(self):
        with TestClient(self.app()) as client:
            self.assertEqual(client.get('/healthz').status_code, 200)
            self.assertEqual(client.post('/rank', json=self.request).status_code, 401)
            self.assertEqual(client.get('/v1/analytics/issues', headers={'Authorization': 'Bearer test-service'}).status_code, 403)
            forged = dict(self.headers, **{'X-Tenant-ID': 'other'})
            self.assertEqual(client.get('/v1/analytics/issues', headers=forged).status_code, 403)
            self.assertEqual(self.model.calls, [])

    def test_revision_correction_and_same_revision_conflict(self):
        with TestClient(self.app()) as client:
            self.assertEqual(client.post('/rank', headers=self.headers, json=self.request).status_code, 200)
            self.request['news']['body'] = 'Поставщик исправил прайс.'
            self.assertEqual(client.post('/rank', headers=self.headers, json=self.request).status_code, 409)
            self.request['news']['revision'] = 2
            self.assertEqual(client.post('/rank', headers=self.headers, json=self.request).status_code, 200)
            self.assertEqual(len(self.store.list('article')), 2)

    def test_profile_sync_retains_document_facts_and_removes_old_profile_values(self):
        from orchestrator.analytics.integration import sync_company
        scope = Scope(tenant_id='alpha', company_id='42')
        sync_company(self.service, self.request['company'])
        company = CompanyProfile.model_validate(self.store.get('company', '42', **scope.db()).payload)
        company.facts.append(CompanyFact(fact_id='document-fact', text='supplier fixed price',
                                        subject_id='42', predicate='buys_from', object_id='supplier',
                                        verification_status='user_asserted'))
        self.service.update_company_profile(scope, company)
        self.request['company']['profile'] = {'Б2': 'new profile'}
        sync_company(self.service, self.request['company'])
        result = self.store.get('company', '42', **scope.db()).payload
        self.assertIn('document-fact', [f['fact_id'] for f in result['facts']])
        self.assertFalse(any('floating price' in f['text'] for f in result['facts']))
        version = self.store.get('company', '42', **scope.db()).version
        sync_company(self.service, self.request['company'])
        self.assertEqual(self.store.get('company', '42', **scope.db()).version, version)

    def test_invalid_body_does_not_echo_secrets_and_is_bounded(self):
        with TestClient(self.app()) as client:
            response = client.post('/rank', headers=self.headers, json={'secret': 'do-not-echo'})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('do-not-echo', response.text)
            response = client.post('/rank', headers=self.headers, content=b'x' * (2 * 1024 * 1024 + 1))
            self.assertEqual(response.status_code, 413)

    def test_document_boundary_accepts_files_larger_than_rank_payloads(self):
        content = b'a' * (3 * 1024 * 1024)
        with (TestClient(self.app()) as client,
              patch('orchestrator.analytics.router.parse_document', return_value='parsed'),
              patch.object(self.service, 'ingest_company_document', return_value={'status': 'ready'}) as ingest):
            response = client.post('/v1/analytics/documents', headers=self.headers, json={
                'document_id': 'large', 'revision': 1, 'filename': 'report.txt',
                'media_type': 'text/plain', 'content_base64': base64.b64encode(content).decode(),
            })
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(ingest.call_args.kwargs['original'], content)


if __name__ == '__main__':
    unittest.main()
