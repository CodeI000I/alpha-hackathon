import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.config import Settings
from orchestrator.demo import REQUEST
from orchestrator.models import RankRequest
from orchestrator.pipeline import Pipeline, Principal
from orchestrator.storage import Store


class OrchestratorRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(db_path=Path(self.temp.name) / 'test.sqlite3')
        self.store = Store(self.settings.db_path)

    def create_job(self, policy='policy-v1'):
        request = RankRequest.model_validate(REQUEST)
        job_id = self.store.put_jobs(request.news, request.company, request.roles, policy)[0]
        return job_id

    def test_ready_report_is_not_current_after_policy_changes(self):
        old_pipeline = Pipeline(self.settings, self.store, llm=None)
        request = RankRequest.model_validate(REQUEST)
        job_id = self.store.put_jobs(request.news, request.company, request.roles,
                                     old_pipeline.policy)[0]
        self.store.finish(job_id, 'ready', result={'report': {'summary': 'old model result'}})

        new_settings = self.settings.model_copy(update={'default_model': 'z-ai/glm-5.3-flash'})
        new_pipeline = Pipeline(new_settings, self.store, llm=None)
        report = new_pipeline.read(job_id, Principal('user-1', frozenset({request.company.id})))

        self.assertFalse(report['current'])
        self.assertEqual(report['result']['report']['summary'], 'old model result')

    def test_third_budget_block_finishes_job_instead_of_leaving_it_stuck(self):
        job_id = self.create_job()

        for _ in range(3):
            self.assertTrue(self.store.claim(job_id))
            attempt = self.store.get_job(job_id)['attempts']
            self.assertTrue(self.store.finish(
                job_id, 'budget_exceeded', error={'code': 'budget_exceeded'}, retry_at=0,
                attempt=attempt))

        job = self.store.get_job(job_id)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['error']['code'], 'budget_exceeded')
        self.assertEqual(self.store.pending(), [])


if __name__ == '__main__':
    unittest.main()
