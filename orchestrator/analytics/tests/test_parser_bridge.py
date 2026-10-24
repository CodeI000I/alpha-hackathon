import unittest

from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import MemoryStore
from orchestrator.analytics.tests.test_service import FakeModel, NOW


class ParserBridgeTests(unittest.TestCase):
    def setUp(self):
        self.service = AnalyticsService(MemoryStore(), FakeModel(), clock=lambda: NOW)
        self.item = {
            'url': 'https://www.cbr.ru/press/news/?file=one', 'title': 'Новость',
            'published_at': NOW.isoformat(), 'published_date': None, 'date_precision': 'second',
            'published_at_source': 'rss:pubDate', 'content_text': 'Поставщик изменил прайс.',
            'content_status': 'full', 'extraction_method': 'cbr_html', 'fetched_at': NOW.isoformat(),
            'provenance': {'source_id': 'cbr_press', 'discovery_method': 'rss',
                           'discovery_url': 'https://www.cbr.ru/rss/RssPress', 'policy_version': 'cbr-prototype-v1'},
        }

    def ingest(self, job='j1', item=None):
        from orchestrator.analytics.parser_bridge import import_result
        return import_result(self.service, {'job_id': job, 'result_status': 'complete', 'items': [item or self.item]})

    def test_complete_result_idempotence_and_corrected_revision(self):
        self.assertEqual(self.ingest()['imported'], 1)
        calls = len(self.service.llm.calls)
        self.assertEqual(self.ingest()['imported'], 1)
        self.ingest('j2')
        self.assertEqual(len(self.service.llm.calls), calls)
        self.assertEqual(len(self.service.store.list('article')), 1)
        self.item['content_text'] = 'Поставщик исправил прайс.'
        self.ingest('j3')
        articles = self.service.store.list('article')
        self.assertEqual(sorted(r.payload['article']['revision'] for r in articles), [1, 2])
        self.assertEqual(articles[-1].payload['article']['source'], 'cbr_press')

    def test_day_precision_is_held_without_invented_time(self):
        self.item.update(published_at=None, published_date='2026-10-23', date_precision='day')
        result = self.ingest()
        self.assertEqual(result['held'][0]['reason'], 'publication_time_required')
        self.assertEqual(self.service.store.list('article'), [])
        self.assertEqual(self.service.llm.calls, [])

    def test_older_snapshot_cannot_revert_a_corrected_article(self):
        from datetime import timedelta
        self.ingest()
        self.item['fetched_at'] = (NOW - timedelta(hours=1)).isoformat()
        self.item['content_text'] = 'Старый прайс.'
        self.assertEqual(self.ingest('late-result')['held'][0]['reason'], 'older_snapshot')
        self.assertEqual(len(self.service.store.list('article')), 1)

    def test_partial_body_is_held_and_untrusted_invalid_result_rejected(self):
        self.item['content_status'] = 'partial'
        self.assertEqual(self.ingest()['held'][0]['reason'], 'complete_content_required')
        self.item['date_precision'] = 'invented'
        with self.assertRaises(ValueError):
            self.ingest('bad')


if __name__ == '__main__':
    unittest.main()
