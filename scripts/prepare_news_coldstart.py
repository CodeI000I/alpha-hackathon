"""Build the deployment seed from saved publisher RSS; performs no network/DB I/O.

Usage: python scripts/prepare_news_coldstart.py --start ISO --end ISO
       --feed S077=/path/cbr.xml --feed S142=/path/frank-page-1.xml
       --output /path/0008_news_coldstart.sql
"""
import argparse
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

HOSTS = {'S077': 'www.cbr.ru', 'S136': 'www.interfax.ru', 'S142': 'frankmedia.ru'}


def clean(value, limit):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', value or '')).split())[:limit]


def parse_rss(content, source, start, end):
    if source not in HOSTS or start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError('expected approved source and explicit timezone-aware window')
    if len(content) > 8 << 20:
        raise ValueError('RSS exceeds 8 MiB')
    root = ET.fromstring(content)
    if root.tag != 'rss':
        raise ValueError('expected RSS, not a challenge/error page')
    rows = []
    for item in root.findall('./channel/item'):
        if source == 'S136' and 'Экономика' not in [c.text for c in item.findall('category')]:
            continue
        try:
            date = parsedate_to_datetime(item.findtext('pubDate', ''))
        except (ValueError, TypeError) as exc:
            raise ValueError('publication timestamp is required') from exc
        if date.tzinfo is None:
            raise ValueError('publication timezone is required')
        if not start <= date <= end:
            continue
        url = item.findtext('link', '').strip()
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != HOSTS[source]
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or '#' in url):
            raise ValueError('article URL is outside the approved publisher')
        title = clean(item.findtext('title'), 1000)
        external_id = item.findtext('guid', '').strip() or url
        if not title or not external_id:
            raise ValueError('title and stable identity are required')
        body = ''
        if source == 'S142':
            body = next((child.text for child in item if child.tag.split('}')[-1] in ('encoded', 'full-text') and child.text), '')
        rows.append(dict(source_id=source, external_id=external_id, url=url, title=title,
                         summary=clean(item.findtext('description'), 30000),
                         body=clean(body, 100000), published_at=date.isoformat()))
    return rows


def render_migration(rows):
    # A regular SQL string literal also handles publisher text containing dollar quotes.
    payload = json.dumps(rows, ensure_ascii=False).replace("'", "''")
    return '''-- Frozen real RSS snapshot; provenance: docs/news-coldstart.md.
-- Insert-only: never roll back a live revision or republish a completed delivery.
INSERT INTO news_items(source_id, external_id, url, title, summary, body, published_at)
SELECT source_id, external_id, url, title, summary, body, published_at
FROM jsonb_to_recordset(''' + "'" + payload + "'" + '''::jsonb)
AS n(source_id text, external_id text, url text, title text, summary text, body text, published_at timestamptz)
ON CONFLICT (source_id, external_id) DO NOTHING;

INSERT INTO news_deliveries(news_id, revision, user_id)
SELECT n.id, n.revision, u.id FROM news_items n CROSS JOIN users u
WHERE n.published_at >= now() - interval '504 hours' AND n.published_at <= now()
  AND u.company_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=u.id)
ON CONFLICT (news_id, revision, user_id) DO NOTHING;
SELECT pg_notify('feed_refresh', '');
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True, type=datetime.fromisoformat)
    parser.add_argument('--end', required=True, type=datetime.fromisoformat)
    parser.add_argument('--feed', action='append', required=True, help='S077=/path/feed.xml (repeatable)')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    rows, inputs = {}, []
    for value in args.feed:
        source, path = value.split('=', 1)
        content = Path(path).read_bytes()
        parsed = parse_rss(content, source, args.start, args.end)
        inputs.append(dict(source_id=source, file=Path(path).name, sha256=hashlib.sha256(content).hexdigest(), accepted=len(parsed)))
        for row in parsed:
            key = row['source_id'], row['external_id']
            if key in rows and rows[key] != row:
                raise ValueError(f'conflicting versions in input: {key}')
            rows[key] = row
    if not rows:
        raise ValueError('no news in the requested window; no migration written')
    ordered = sorted(rows.values(), key=lambda r: (r['published_at'], r['source_id'], r['external_id']))
    sql = render_migration(ordered)
    args.output.write_text(sql, encoding='utf-8')
    manifest = dict(start=args.start.isoformat(), end=args.end.isoformat(), inputs=inputs,
                    count=len(rows), counts={s: sum(r['source_id'] == s for r in ordered) for s in HOSTS},
                    migration_sha256=hashlib.sha256(sql.encode()).hexdigest())
    args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ('count','counts')},ensure_ascii=False))


if __name__ == '__main__':
    main()
