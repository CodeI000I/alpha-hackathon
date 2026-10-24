"""Preserve parser provenance; incomplete material never gains an invented publication time."""

import os
import time
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from orchestrator.models import canonical, digest
from parser_service.result_models import JobResult
from .models import NewsArticle


LEDGER_SCOPE = {'tenant_id': 'alpha', 'company_id': '__parser__'}


def import_result(service, payload):
    result = JobResult.model_validate_json(canonical(payload), strict=True)
    with service.store.lock('parser-import'):
        old = service.store.get('parser_receipt', result.job_id, **LEDGER_SCOPE)
        if old:
            if old.payload['fingerprint'] != digest(payload):
                raise ValueError('parser job changed its immutable result')
            return old.payload
        receipt = dict(job_id=result.job_id, fingerprint=digest(payload), imported=0, held=[])
        for item in result.items:
            reason = ('complete_content_required' if item.content_status != 'full' or not item.title
                      else 'publication_time_required' if item.date_precision != 'second' else None)
            if reason:
                receipt['held'].append({'url': str(item.url), 'reason': reason})
                continue
            identity = digest([item.provenance.source_id, str(item.url)])
            prior = [r.payload['article'] for r in service.store.list('article')
                     if r.payload['article']['source'] == item.provenance.source_id
                     and r.payload['article']['news_id'] == identity]
            latest = max(prior, key=lambda article: article['revision'], default=None)
            if latest and item.fetched_at and item.fetched_at < datetime.fromisoformat(latest['received_at']):
                receipt['held'].append({'url': str(item.url), 'reason': 'older_snapshot'})
                continue
            article = NewsArticle(
                source=item.provenance.source_id, news_id=identity, title=item.title,
                content=item.content_text, source_url=str(item.url), published_at=item.published_at,
                received_at=item.fetched_at or service.clock(), revision=latest['revision'] if latest else 1,
                metadata={'provenance': item.provenance.model_dump(mode='json'),
                          'content_status': item.content_status, 'date_precision': item.date_precision,
                          'published_at_source': item.published_at_source,
                          'attachments': [attachment.model_dump(mode='json') for attachment in item.attachments]},
            )
            if latest:
                compare = lambda value: {k: v for k, v in value.items() if k not in {'revision', 'received_at'}}
                if compare(latest) != compare(article.model_dump(mode='json')):
                    article.revision += 1
            service.ingest_news(article)
            receipt['imported'] += 1
        service.store.put('parser_receipt', result.job_id, receipt, **LEDGER_SCOPE)
        return receipt


def process_parser(service, dsn):
    """Optionally run the existing bounded CBR worker, then import completed snapshots."""
    from parser_service.repository import JobRepository
    if os.environ.get('PARSER_CBR_ALLOW_FETCH', '').lower() == 'true':
        from parser_service.policy import SourcePolicy
        from parser_service.cbr import CbrHandler
        from parser_service.worker import run_once
        from parser_service.config import positive_setting
        policy = SourcePolicy.from_env()
        if not policy.allow_persist:
            raise ValueError('PARSER_CBR_ALLOW_PERSIST must permit the configured source')
        repository = JobRepository(dsn, connect_timeout=5, statement_timeout_ms=10000)
        period = positive_setting('PARSER_POLL_SECONDS')
        repository.submit({'job_id': f'cbr-{int(time.time()) // period}', 'mode': 'discover',
                           'source_id': 'cbr_press', 'requested_level': 'content',
                           'policy_version': policy.version})
        run_once(repository, CbrHandler(policy), lease_seconds=positive_setting('PARSER_LEASE_SECONDS'),
                 max_attempts=positive_setting('PARSER_MAX_ATTEMPTS'), max_items=policy.max_items)
    cursor = service.store.get('parser_cursor', 'results', **LEDGER_SCOPE)
    after = cursor.payload.get('after', '') if cursor else ''
    # Created_at ordering is unnecessary: the cursor scans the stable job_id index,
    # wrapping every pass so a previously running job cannot be lost.
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row,
                         options='-c statement_timeout=10000') as db:
        db.read_only = True
        results = db.execute("SELECT job_id, result FROM parser.jobs WHERE status='succeeded' AND job_id>%s ORDER BY job_id LIMIT 100", (after,)).fetchall()
    for row in results:
        import_result(service, row['result'])
    service.store.put('parser_cursor', 'results',
                      {'after': results[-1]['job_id'] if len(results) == 100 else ''}, **LEDGER_SCOPE)
