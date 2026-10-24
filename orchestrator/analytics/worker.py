"""Recoverable backend synchronization and analytics jobs; no in-process fire-and-forget work."""

import argparse
import json
import logging
import os
import signal
import threading

import httpx
import psycopg
from psycopg.rows import dict_row

from orchestrator.llm import AIError
from .integration import sync_company
from .knowledge import DocumentParseError, MAX_DOCUMENT_BYTES, parse_document
from .models import digest
from .store import StoreBusy


LOG = logging.getLogger(__name__)
SYSTEM_SCOPE = {'tenant_id': 'alpha', 'company_id': '__integration__'}
MAX_FILE_BYTES = MAX_DOCUMENT_BYTES


class BackendRepository:
    """Read the existing Go schema, in short read-only transactions, without copying it."""
    def __init__(self, dsn):
        self.dsn = dsn

    def _read(self, query, args=()):
        with psycopg.connect(self.dsn, connect_timeout=5, row_factory=dict_row,
                             options='-c statement_timeout=10000') as db:
            db.read_only = True
            return db.execute(query, args).fetchall()

    def ready(self):
        self._read('SELECT id FROM companies LIMIT 0')

    def company(self, company_id):
        rows = self._read('SELECT id, inn, name, profile FROM companies WHERE id=%s', (company_id,))
        return rows[0] if rows else None

    def companies(self, *, after=0, limit=100):
        return self._read('''SELECT c.id, c.inn, c.name, c.profile,
            ARRAY(SELECT DISTINCT r.code FROM users u JOIN user_roles ur ON ur.user_id=u.id
                  JOIN roles r ON r.id=ur.role_id WHERE u.company_id=c.id ORDER BY r.code) AS roles
            FROM companies c WHERE c.id>%s ORDER BY c.id LIMIT %s''', (after, limit))

    def files(self, company_id):
        return self._read('''SELECT id, company_id, object_key, filename, content_type, size_bytes
            FROM company_files WHERE company_id=%s ORDER BY id''', (company_id,))


def _sync_file(service, scope, row, client, token):
    key = str(row['id'])
    fingerprint = digest(row)
    with service.store.lock('backend-file:' + digest([scope.db(), key])):
        previous = service.store.get('integration_file', key, **scope.db())
        state = previous.payload if previous and previous.payload['fingerprint'] == fingerprint else {
            'file_id': row['id'], 'filename': row['filename'], 'document_id': 'backend-file:' + key,
            'fingerprint': fingerprint, 'status': 'queued', 'attempts': 0, 'error': None, 'retry_at': 0,
        }
        if state['status'] in {'ready', 'failed'} or state['retry_at'] > service.clock().timestamp():
            return state['status']
        try:
            if not 0 < row['size_bytes'] <= MAX_FILE_BYTES:
                raise DocumentParseError('FILE_SIZE_LIMIT')
            if not token:
                raise AIError('integration_not_configured', 'INTERNAL_API_TOKEN is required')
            content = bytearray()
            with client.stream('GET', f'/api/v1/internal/files/{row["id"]}/content',
                               headers={'Authorization': 'Bearer ' + token}) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(65536):
                    if len(content) + len(chunk) > MAX_FILE_BYTES:
                        raise DocumentParseError('FILE_SIZE_LIMIT')
                    content.extend(chunk)
            if len(content) != row['size_bytes']:
                raise ValueError('file size differs from committed metadata')
            document = parse_document(state['document_id'], 1, row['filename'], bytes(content), row['content_type'])
            service.ingest_company_document(scope, document, original=bytes(content))
            state = dict(state, status='ready', error=None, retry_at=0)
        except StoreBusy:
            return 'busy'
        except Exception as exc:
            paused = isinstance(exc, AIError) and exc.code in {
                'budget_exceeded', 'rate_limited', 'busy', 'model_not_configured', 'integration_not_configured'}
            attempts = state['attempts'] + (0 if paused else 1)
            permanent = isinstance(exc, DocumentParseError) or attempts >= 3
            state = dict(state, status='failed' if permanent else 'queued', attempts=attempts,
                         error=getattr(exc, 'code', type(exc).__name__),
                         retry_at=max(service.clock().timestamp() + min(60 * 2 ** attempts, 3600),
                                      getattr(exc, 'retry_at', 0)))
        service.store.put('integration_file', key, state, **scope.db())
        return state['status']


def run_once(service, backend, client, *, internal_token, limit=100):
    cursor = service.store.get('integration_cursor', 'companies', **SYSTEM_SCOPE)
    after = cursor.payload['after'] if cursor else 0
    companies = backend.companies(after=after, limit=limit)
    result = dict(companies=0, documents_ready=0, jobs=0, errors=0)
    for company in companies:
        try:
            scope = sync_company(service, company)
            for row in backend.files(company['id']):
                result['documents_ready'] += _sync_file(service, scope, row, client, internal_token) == 'ready'
            for role in company['roles']:
                role_scope = scope.model_copy(update={'role': role})
                if not service.get_company_situation(role_scope)['current']:
                    service.reprocess_company(role_scope, reason='backend_sync')
                # Explicit daily refresh catches temporal applicability without changing source versions.
                service.reprocess_company(role_scope, reason='schedule:' + service.clock().date().isoformat())
            result['jobs'] += len(service.process_jobs(scope, limit=10))
            result['companies'] += 1
        except Exception as exc:
            result['errors'] += 1
            LOG.warning('company synchronization deferred: company=%s code=%s', company['id'],
                        getattr(exc, 'code', type(exc).__name__))
    service.store.put('integration_cursor', 'companies',
                      {'after': companies[-1]['id'] if len(companies) == limit else 0}, **SYSTEM_SCOPE)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from .runtime import runtime
    dsn = os.environ.get('ANALYTICS_BACKEND_DATABASE_URL', '')
    base_url = os.environ.get('BACKEND_URL', '')
    token = os.environ.get('INTERNAL_API_TOKEN', '')
    interval = float(os.environ.get('ANALYTICS_POLL_SECONDS', '5'))
    if not dsn or not base_url or not 1 <= interval <= 3600:
        parser.error('ANALYTICS_BACKEND_DATABASE_URL, BACKEND_URL and poll interval 1..3600 are required')
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_args: stop.set())
    with runtime(allow_unconfigured=True) as service, httpx.Client(
            base_url=base_url, timeout=30, follow_redirects=False, trust_env=False) as client:
        backend = BackendRepository(dsn)
        while not stop.is_set():
            try:
                parser_dsn = os.environ.get('PARSER_DATABASE_URL')
                if parser_dsn:
                    from .parser_bridge import process_parser
                    try:
                        process_parser(service, parser_dsn)
                    except Exception as exc:
                        LOG.warning('parser integration deferred: code=%s', getattr(exc, 'code', type(exc).__name__))
                result = run_once(service, backend, client, internal_token=token)
                LOG.info('analytics worker %s', json.dumps(result))
                if args.once:
                    return 1 if result['errors'] else 0
            except Exception as exc:
                LOG.warning('analytics worker deferred: code=%s', getattr(exc, 'code', type(exc).__name__))
                if args.once:
                    return 1
            stop.wait(interval)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
