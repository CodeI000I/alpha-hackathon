import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from orchestrator.analytics.models import Scope
from orchestrator.analytics.router import create_router
from orchestrator.analytics.store import StoreBusy
from orchestrator.analytics.tests import test_service as fixtures


class RouterTests(unittest.TestCase):
    def setUp(self):
        fixtures.ServiceTests.setUp(self)
        self.allowed = True
        def authorize():
            if not self.allowed:
                raise HTTPException(403)
            return self.scope
        self.app = FastAPI()
        self.authorize = authorize
        self.app.include_router(create_router(self.service, authorize, authorize_ingestion=authorize))
        self.client = TestClient(self.app)

    def article(self, **kwargs):
        return fixtures.ServiceTests.article(self, **kwargs)

    def test_disposable_router_flow_and_read_without_generation(self):
        response = self.client.post('/v1/analytics/news', json=self.article().model_dump(mode='json'))
        self.assertEqual(response.status_code, 200, response.text)
        calls = len(self.model.calls)
        response = self.client.get('/v1/analytics/situation')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['current'])
        self.assertEqual(calls, len(self.model.calls))
        self.assertEqual(self.client.get('/v1/analytics/issues?limit=0').status_code, 422)
        self.allowed = False
        self.assertEqual(self.client.get('/v1/analytics/issues').status_code, 403)

    def test_body_cannot_override_trusted_tenant(self):
        payload = self.article().model_dump(mode='json') | {'tenant_id': 'victim'}
        self.assertEqual(self.client.post('/v1/analytics/news', json=payload).status_code, 422)

    def test_company_access_does_not_grant_global_ingestion(self):
        app = FastAPI()
        app.include_router(create_router(self.service, self.authorize))
        with TestClient(app) as client:
            response = client.post('/v1/analytics/news', json=self.article().model_dump(mode='json'))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.store.list('event'), [])

    def test_store_contention_returns_controlled_busy_response(self):
        def busy(_scope):
            raise StoreBusy('synthetic lock timeout')
        self.service.get_company_situation = busy
        response = self.client.get('/v1/analytics/situation')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': {'code': 'busy'}})


if __name__ == '__main__':
    unittest.main()
