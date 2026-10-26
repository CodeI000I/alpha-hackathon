import unittest
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from scripts.prepare_news_coldstart import parse_rss, render_migration


class ColdStartTests(unittest.TestCase):
    def test_window_identity_category_and_metadata_policy(self):
        def item(guid, date, category='Экономика'):
            return f'<item><guid>{guid}</guid><link>https://www.interfax.ru/business/{guid}</link><title>Заголовок</title><description>&lt;b&gt;Описание&lt;/b&gt;</description><pubDate>{date}</pubDate><category>{category}</category></item>'
        xml = '<rss><channel>' + ''.join([
            item('keep', 'Mon, 05 Oct 2026 00:00:00 +0300'),
            item('old', 'Sun, 04 Oct 2026 23:59:59 +0300'),
            item('future', 'Tue, 27 Oct 2026 00:00:00 +0300'),
            item('sport', 'Mon, 12 Oct 2026 12:00:00 +0300', 'Спорт'),
        ]) + '</channel></rss>'
        rows = parse_rss(xml.encode(), 'S136', datetime.fromisoformat('2026-10-05T00:00:00+03:00'), datetime.fromisoformat('2026-10-26T16:00:00+03:00'))
        self.assertEqual([row['external_id'] for row in rows], ['keep'])
        self.assertEqual(rows[0]['summary'], 'Описание')
        self.assertEqual(rows[0]['body'], '')
        self.assertEqual(rows[0]['published_at'], '2026-10-05T00:00:00+03:00')

    def test_rejects_challenge_missing_date_and_foreign_url(self):
        start = datetime(2026, 10, 5, tzinfo=timezone.utc)
        end = datetime(2026, 10, 26, tzinfo=timezone.utc)
        for xml in ['<html><body>challenge</body></html>', '<rss><channel><item><title>x</title></item></channel></rss>',
                    '<rss><channel><item><title>x</title><guid>x</guid><link>https://evil.test/x</link><pubDate>Mon, 12 Oct 2026 12:00:00 +0300</pubDate></item></channel></rss>']:
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                parse_rss(xml.encode(), 'S077', start, end)

    def test_migration_is_insert_only_and_replay_safe(self):
        row = dict(source_id='S077', external_id="a'$coldstart$", url='https://www.cbr.ru/a', title="Банк's", summary='x', body='', published_at='2026-10-12T12:00:00+03:00')
        sql = render_migration([row])
        self.assertIn('ON CONFLICT (source_id, external_id) DO NOTHING', sql)
        self.assertNotIn('DO UPDATE', sql)
        self.assertIn('504 hours', sql)
        self.assertIn("Банк''s", sql)

    def test_checked_in_snapshot_hash_and_window(self):
        directory = Path(__file__).resolve().parents[1] / 'backend/coldstart'
        sql = (directory / '0008_news_coldstart.sql').read_text()
        manifest = json.loads((directory / '0008_news_coldstart.manifest.json').read_text())
        self.assertEqual(hashlib.sha256(sql.encode()).hexdigest(), manifest['migration_sha256'])
        payload = sql.split("jsonb_to_recordset('", 1)[1].split("'::jsonb)", 1)[0].replace("''", "'")
        rows = json.loads(payload)
        self.assertEqual(len(rows), manifest['count'])
        self.assertEqual(len({(r['source_id'], r['external_id']) for r in rows}), len(rows))
        start, end = (datetime.fromisoformat(manifest[k]) for k in ('start', 'end'))
        self.assertTrue(all(start <= datetime.fromisoformat(r['published_at']) <= end for r in rows))
        self.assertEqual({s: sum(r['source_id'] == s for r in rows) for s in manifest['counts']}, manifest['counts'])


if __name__ == '__main__':
    unittest.main()
