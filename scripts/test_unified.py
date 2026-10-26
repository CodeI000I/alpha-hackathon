"""Offline end-to-end smoke through Go HTTP, PostgreSQL and Python analytics.

The only external-looking adapters are local: an in-process S3-compatible test
fixture and an httpx MockTransport synthetic model gateway. No Docker, cloud
service, real model key or live source is used. The test creates and drops one
uniquely named child database under an explicitly loopback analytics_test_* DB.
"""

from __future__ import annotations

import hashlib
import json
import os
from email.utils import formatdate
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import uuid4
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr
import uvicorn

from orchestrator.analytics.app import create_app
from orchestrator.analytics.demo import SyntheticGateway
from orchestrator.analytics.knowledge import KnowledgeService
from orchestrator.analytics.migrate import apply_migrations
from orchestrator.analytics.service import AnalyticsService
from orchestrator.analytics.store import PostgresStore
from orchestrator.analytics.worker import BackendRepository, run_once
from orchestrator.config import Settings
from orchestrator.llm import LLMClient


TEST_DSN = os.environ.get('UNIFIED_TEST_DATABASE_URL')
SERVICE_TOKEN = 'unified-smoke-service-token'
INTERNAL_TOKEN = 'unified-smoke-internal-token'
PASSWORD = 'unified-smoke-password'
GO_PATH = os.environ.get('GO')


class UnifiedGateway(SyntheticGateway):
    """Reuse the repository's synthetic responses for numeric backend news IDs."""

    def respond(self, name, context):
        if name == 'EventDraft':
            context = json.loads(json.dumps(context))
            context['article']['news_id'] = 'logistics'
        return super().respond(name, context)


class S3Fixture:
    """Tiny, loopback-only S3 adapter for exercising Go's real MinIO client."""

    def __init__(self):
        self.bucket = None
        self.objects = {}
        self.gets = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                return

            def _parts(self):
                parts = [unquote(part) for part in self.path.split('?', 1)[0].split('/') if part]
                return (parts[0], '/'.join(parts[1:])) if parts else ('', '')

            def _empty(self, status):
                self.send_response(status)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_HEAD(self):
                bucket, key = self._parts()
                if key:
                    item = owner.objects.get((bucket, key))
                    if item is None:
                        self._empty(404)
                        return
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(item)))
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('ETag', f'"{hashlib.md5(item).hexdigest()}"')
                    self.send_header('Last-Modified', formatdate(usegmt=True))
                    self.end_headers()
                else:
                    self._empty(200 if owner.bucket == bucket else 404)

            def do_PUT(self):
                bucket, key = self._parts()
                size = int(self.headers.get('Content-Length', '0'))
                body = self.rfile.read(size) if size else b''
                if b';chunk-signature=' in body[:160]:
                    decoded, offset = bytearray(), 0
                    while offset < len(body):
                        line_end = body.find(b'\r\n', offset)
                        if line_end < 0:
                            break
                        chunk_size = int(body[offset:line_end].split(b';', 1)[0], 16)
                        offset = line_end + 2
                        if chunk_size == 0:
                            break
                        decoded.extend(body[offset:offset + chunk_size])
                        offset += chunk_size + 2  # chunk payload and its CRLF
                    body = bytes(decoded)
                if not key:
                    owner.bucket = bucket
                    self._empty(200)
                    return
                if owner.bucket != bucket:
                    self._empty(404)
                    return
                owner.objects[(bucket, key)] = body
                etag = hashlib.md5(body).hexdigest()
                self.send_response(200)
                self.send_header('ETag', f'"{etag}"')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_GET(self):
                bucket, key = self._parts()
                body = owner.objects.get((bucket, key))
                if body is None:
                    self._empty(404)
                    return
                owner.gets.append((bucket, key))
                range_header = self.headers.get('Range', '')
                start, end = 0, len(body) - 1
                if range_header.startswith('bytes=') and '-' in range_header:
                    first, last = range_header[6:].split('-', 1)
                    start = int(first or 0)
                    end = min(int(last) if last else end, end)
                payload = body[start:end + 1]
                self.send_response(206 if range_header else 200)
                self.send_header('ETag', f'"{hashlib.md5(body).hexdigest()}"')
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Last-Modified', formatdate(usegmt=True))
                self.send_header('Content-Length', str(len(payload)))
                if range_header:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{len(body)}')
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f'127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class RunningAPI:
    def __init__(self, service, backend, port):
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(service=service, service_token=SERVICE_TOKEN, backend=backend),
            host='127.0.0.1', port=port, log_level='error', access_log=False,
        ))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{port}'

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError('analytics API did not stop cleanly')


def _test_dsn_parts(dsn):
    parsed = urlsplit(dsn)
    if parsed.scheme not in {'postgres', 'postgresql'}:
        raise RuntimeError('UNIFIED_TEST_DATABASE_URL must be a PostgreSQL URL')
    try:
        connection = conninfo_to_dict(dsn)
    except (psycopg.Error, ValueError):
        raise RuntimeError('UNIFIED_TEST_DATABASE_URL is invalid') from None
    host = connection.get('host')
    if host not in {'127.0.0.1', 'localhost', '::1'}:
        raise RuntimeError('UNIFIED_TEST_DATABASE_URL must use a literal loopback PostgreSQL host')
    hostaddr = connection.get('hostaddr')
    if hostaddr and hostaddr not in {'127.0.0.1', '::1'}:
        raise RuntimeError('UNIFIED_TEST_DATABASE_URL hostaddr must be loopback')
    if connection.get('service'):
        raise RuntimeError('UNIFIED_TEST_DATABASE_URL must not use a libpq service')
    if not parsed.port or not connection.get('dbname', '').startswith('analytics_test_'):
        raise RuntimeError('UNIFIED_TEST_DATABASE_URL must target a named analytics_test_* database')
    overrides = {'host', 'hostaddr', 'service', 'dbname'}
    if any(key.lower() in overrides for key, _value in parse_qsl(parsed.query, keep_blank_values=True)):
        raise RuntimeError('libpq host and database overrides are not allowed for the smoke database')
    return connection


def _self_check_test_dsn_guard():
    valid = 'postgresql://127.0.0.1:5432/analytics_test_guard'
    _test_dsn_parts(valid)
    child = conninfo_to_dict(make_conninfo(valid, dbname='analytics_test_child', hostaddr='127.0.0.1'))
    if child.get('dbname') != 'analytics_test_child' or child.get('hostaddr') != '127.0.0.1':
        raise AssertionError('child DSN must explicitly target its generated test database on loopback')
    unsafe = (
        'postgresql://127.0.0.1:5432/analytics_test_guard?%68ost=remote.example',
        'postgresql://127.0.0.1:5432/analytics_test_guard?%68ostaddr=203.0.113.8',
        'postgresql://127.0.0.1:5432/analytics_test_guard?%73ervice=remote',
        'postgresql://127.0.0.1:5432/analytics_test_guard?%64bname=production',
    )
    for dsn in unsafe:
        try:
            _test_dsn_parts(dsn)
        except RuntimeError:
            continue
        raise AssertionError(f'test DSN guard accepted an unsafe override: {dsn}')


def _create_child_database(base_dsn):
    connection = _test_dsn_parts(base_dsn)
    base_name = connection['dbname']
    child = f'{base_name[:40]}_{os.getpid()}_{uuid4().hex[:8]}'
    base_created = False
    hostaddr = '::1' if connection['host'] == '::1' else '127.0.0.1'
    maintenance = make_conninfo(base_dsn, dbname='postgres', hostaddr=hostaddr)
    try:
        with psycopg.connect(make_conninfo(base_dsn, dbname=base_name, hostaddr=hostaddr)):
            pass
    except psycopg.errors.InvalidCatalogName:
        with psycopg.connect(maintenance, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(base_name)))
        base_created = True
    with psycopg.connect(maintenance, autocommit=True) as db:
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(child)))
    return make_conninfo(base_dsn, dbname=child, hostaddr=hostaddr), maintenance, child, base_name, base_created


def _drop_child_database(maintenance_dsn, child, base_name, base_created):
    with psycopg.connect(maintenance_dsn, autocommit=True) as db:
        db.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',
                   (child,))
        db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(child)))
        if base_created:
            db.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',
                       (base_name,))
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(base_name)))


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_http(url, process=None, log_path=None, timeout=45):
    deadline = time.monotonic() + timeout
    with httpx.Client(trust_env=False, timeout=1) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                excerpt = Path(log_path).read_text(errors='replace')[-8000:] if log_path else ''
                raise RuntimeError(f'process exited with {process.returncode}: {excerpt}')
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.15)
    excerpt = Path(log_path).read_text(errors='replace')[-8000:] if log_path else ''
    raise RuntimeError(f'timed out waiting for {url}: {excerpt}')


def _start_process(command, env, cwd, log_path):
    log = open(log_path, 'ab', buffering=0)
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    process._smoke_log = log
    return process


def _stop_process(process):
    if process is None:
        return
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    log = getattr(process, '_smoke_log', None)
    if log is not None:
        log.close()


def _new_analytics_service(dsn, object_dir):
    store = PostgresStore(dsn, connect_timeout=5, statement_timeout_ms=10000)
    gateway = UnifiedGateway()
    transport = httpx.Client(transport=httpx.MockTransport(gateway), follow_redirects=False)
    settings = Settings(api_key=SecretStr('unified-synthetic-test-key'), max_retries=0,
                        requests_per_minute=120, max_input_chars=100000)
    llm = LLMClient(settings, store, http_client=transport)
    knowledge = KnowledgeService(store, llm, object_dir=object_dir)
    service = AnalyticsService(store, llm, knowledge=knowledge, debounce_seconds=0)
    return service, llm, gateway


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _onboard(client, base_url, label, role):
    seed = uuid4().hex
    response = client.post(base_url + '/api/v1/onboarding',
                          headers={'Idempotency-Key': 'unified-' + seed, 'Origin': base_url},
                          json={'company': {'inn': str(10_000_000_000 + int(seed[:8], 16) % 900_000_000),
                                            'name': f'Унифицированная компания {label}'},
                                'user': {'email': f'unified-{label}-{seed}@example.test',
                                         'fullName': f'Пользователь {label}', 'password': PASSWORD,
                                         'roles': [role]}})
    _assert(response.status_code == 201, f'onboarding {label}: {response.status_code} {response.text}')
    value = response.json()
    return value['company']['id'], value['user']['id']


def _upload(client, base_url, company_id, label, content):
    response = client.post(base_url + f'/api/v1/companies/{company_id}/files',
                           headers={'Origin': base_url},
                           files={'file': (f'{label}-contract.txt', content, 'text/plain')})
    _assert(response.status_code == 201, f'upload {label}: {response.status_code} {response.text}')
    return response.json()


def _wait_for_feed(client, base_url, user_id, role, timeout=75):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(base_url + f'/api/v1/users/{user_id}/feed', params={'role': role})
        if response.status_code != 200:
            raise AssertionError(f'feed request failed: {response.status_code} {response.text}')
        last = response.json()
        if last:
            return last
        time.sleep(0.25)
    raise AssertionError(f'Go worker did not deliver the imported news; last feed={last!r}')


def _tail(path):
    try:
        return Path(path).read_text(errors='replace')[-6000:]
    except OSError:
        return ''


def main():
    _self_check_test_dsn_guard()
    if not TEST_DSN:
        raise RuntimeError('Set UNIFIED_TEST_DATABASE_URL to an explicitly loopback analytics_test_* database')
    child_dsn, maintenance_dsn, child_name, base_name, base_created = _create_child_database(TEST_DSN)
    temp = tempfile.TemporaryDirectory(prefix='alpha-unified-smoke-')
    temp_path = Path(temp.name)
    fixture = S3Fixture()
    analytics = None
    service = llm = None
    server_proc = worker_proc = None
    anonymous = client_a = client_b = None
    server_log, worker_log = temp_path / 'go-server.log', temp_path / 'go-worker.log'
    try:
        apply_migrations(child_dsn, connect_timeout=5, statement_timeout_ms=10000)
        go_root = Path(__file__).resolve().parents[1] / 'backend'
        go_binary = Path(GO_PATH) if GO_PATH else Path(shutil.which('go') or '')
        if not go_binary.is_file():
            raise RuntimeError('Go compiler not found; set GO or install Go')
        env = os.environ.copy()
        env['HTTP_PROXY'] = env['HTTPS_PROXY'] = env['ALL_PROXY'] = ''
        env['NO_PROXY'] = env['no_proxy'] = '127.0.0.1,localhost,::1'
        server_binary, worker_binary = temp_path / 'server', temp_path / 'worker'
        subprocess.run([str(go_binary), 'build', '-o', str(server_binary), './cmd/server'],
                       cwd=go_root, env=env, check=True, timeout=180)
        subprocess.run([str(go_binary), 'build', '-o', str(worker_binary), './cmd/worker'],
                       cwd=go_root, env=env, check=True, timeout=180)

        go_port, analytics_port = _free_port(), _free_port()
        while analytics_port == go_port:
            analytics_port = _free_port()
        go_url = f'http://127.0.0.1:{go_port}'
        analytics_url = f'http://127.0.0.1:{analytics_port}'
        # pgx does not implement libpq's hostaddr option. The host is already a
        # validated literal loopback; keep the extra libpq pin only for Python.
        go_connection = conninfo_to_dict(child_dsn)
        go_connection.pop('hostaddr', None)
        env.update({
            'DATABASE_URL': make_conninfo(**go_connection),
            'HTTP_ADDR': f'127.0.0.1:{go_port}',
            'SESSION_COOKIE_SECURE': 'false',
            'ORCHESTRATOR_URL': analytics_url,
            'ORCHESTRATOR_TOKEN': SERVICE_TOKEN,
            'AI_SERVICE_TOKEN': SERVICE_TOKEN,
            'INTERNAL_API_TOKEN': INTERNAL_TOKEN,
            'ORCHESTRATOR_TIMEOUT': '45s',
            'INGEST_PERIOD': '1h',
            'NEWS_COLDSTART_ENABLED': 'false',  # Offline smoke owns its synthetic corpus.
            'RANK_MAX_PER_RUN': '100',
            'S3_ENDPOINT': fixture.endpoint,
            'S3_ACCESS_KEY': 'loopback-fixture',
            'S3_SECRET_KEY': 'loopback-fixture-secret',
            'S3_BUCKET': 'unified-smoke-files',
            'S3_USE_SSL': 'false',
        })
        env.pop('STATIC_DIR', None)
        server_proc = _start_process([str(server_binary)], env, go_root, server_log)
        _wait_http(go_url + '/readyz', server_proc, server_log)

        # This disposable DB is the only source registry the Go worker sees.
        with psycopg.connect(child_dsn) as db:
            db.execute('UPDATE sources SET enabled=false')

        service, llm, gateway = _new_analytics_service(child_dsn, temp_path / 'documents')
        backend = BackendRepository(child_dsn)
        analytics = RunningAPI(service, backend, analytics_port)
        _wait_http(analytics.url + '/readyz', log_path=None)

        anonymous = httpx.Client(base_url=go_url, follow_redirects=False, trust_env=False)
        response = anonymous.get('/api/v1/auth/me')
        _assert(response.status_code == 401, f'auth denial expected 401, got {response.status_code}')

        # Learn a seeded role through the real public catalog; choose deterministically.
        roles_response = anonymous.get('/api/v1/roles')
        _assert(roles_response.status_code == 200, f'roles catalog failed: {roles_response.text}')
        role_codes = {entry['code'] for entry in roles_response.json()}
        role = 'procurement' if 'procurement' in role_codes else sorted(role_codes)[0]
        client_a = httpx.Client(base_url=go_url, follow_redirects=False, trust_env=False, timeout=20)
        client_b = httpx.Client(base_url=go_url, follow_redirects=False, trust_env=False, timeout=20)
        company_a, user_a = _onboard(client_a, go_url, 'a', role)
        company_b, user_b = _onboard(client_b, go_url, 'b', role)

        document_a = 'Компания закупает детали у supplier_x. Цена для ноябрьского заказа фиксирована.'.encode()
        document_b = 'Компания закупает детали у supplier_y. Условия поставки проверяются.'.encode()
        file_a = _upload(client_a, go_url, company_a, 'a', document_a)
        file_b = _upload(client_b, go_url, company_b, 'b', document_b)
        _assert(anonymous.get(f'/api/v1/companies/{company_a}/files').status_code == 401,
                'company files must require a session')
        cross_files = client_a.get(f'/api/v1/companies/{company_b}/files')
        _assert(cross_files.status_code == 403, f'cross-company file access returned {cross_files.status_code}')
        _assert(client_b.get(f'/api/v1/companies/{company_b}/files').status_code == 200,
                'the owning company could not list its files')

        server_proc._smoke_log.flush()
        worker_proc = _start_process([str(worker_binary)], env, go_root, worker_log)

        # Run the production analytics worker against the real Go content route.
        internal_client = httpx.Client(base_url=go_url, follow_redirects=False, trust_env=False, timeout=20)
        wrong_token = internal_client.get(f'/api/v1/internal/files/{file_a["id"]}/content',
                                          headers={'Authorization': 'Bearer wrong'})
        _assert(wrong_token.status_code == 401, 'internal file bridge accepted a wrong token')
        downloaded = internal_client.get(f'/api/v1/internal/files/{file_a["id"]}/content',
                                         headers={'Authorization': 'Bearer ' + INTERNAL_TOKEN})
        _assert(downloaded.status_code == 200,
                'internal file bridge did not return the uploaded document')
        _assert(downloaded.content == document_a,
                f'internal file bridge content differed: {downloaded.content!r} != {document_a!r}; '
                f'fixture objects={[(key, len(value)) for key, value in fixture.objects.items()]!r}; '
                f'GETs={fixture.gets!r}; Go log={_tail(server_log)}')
        internal_client.close()
        downloads_before_worker = len(fixture.gets)

        with httpx.Client(base_url=go_url, follow_redirects=False, trust_env=False, timeout=30) as backend_client:
            first_sync = run_once(service, backend, backend_client, internal_token=INTERNAL_TOKEN)
            downloads_after_first_sync = len(fixture.gets)
            second_sync = run_once(service, backend, backend_client, internal_token=INTERNAL_TOKEN)
        _assert(first_sync['documents_ready'] >= 2, f'analytics worker did not ingest both files: {first_sync}')
        _assert(second_sync['documents_ready'] >= 2, f'analytics worker repeat lost document state: {second_sync}')
        _assert(downloads_after_first_sync - downloads_before_worker == 2 and len(fixture.gets) == 3,
                f'worker repeated object downloads: {fixture.gets!r}')

        direct = httpx.Client(base_url=analytics_url, follow_redirects=False, trust_env=False)
        _assert(direct.get('/v1/analytics/issues').status_code == 401,
                'private analytics API accepted an unauthenticated request')
        direct.close()

        news_payload = [{
            'sourceId': 'manual', 'externalId': 'unified-' + uuid4().hex,
            'url': 'https://example.test/unified-news',
            'title': 'Стоимость морской логистики вырастет',
            'summary': 'Поставки станут дороже.',
            'body': 'С ноября стоимость морской логистики для поставок вырастет.',
            'publishedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }]
        imported = anonymous.post(go_url + '/api/v1/internal/news', json=news_payload,
                                  headers={'Authorization': 'Bearer ' + INTERNAL_TOKEN})
        _assert(imported.status_code == 200, f'news import failed: {imported.status_code} {imported.text}')
        _wait_for_feed(client_a, go_url, user_a, role)
        feed_b = _wait_for_feed(client_b, go_url, user_b, role)

        situation = client_a.get(go_url + '/api/v1/analytics/situation', params={'role': role})
        _assert(situation.status_code == 200, f'Go analytics proxy failed: {situation.status_code} {situation.text}')
        _assert(situation.json().get('snapshot') is not None, 'analytics worker did not persist a situation snapshot')
        issues_a = client_a.get(go_url + '/api/v1/analytics/issues', params={'role': role})
        issues_b = client_b.get(go_url + '/api/v1/analytics/issues', params={'role': role})
        _assert(issues_a.status_code == 200 and issues_b.status_code == 200,
                f'issues proxy failed: A={issues_a.status_code}, B={issues_b.status_code}')
        _assert(issues_a.json() and issues_b.json(), 'Go worker news delivery did not create scoped issues')
        issue_a, issue_b = issues_a.json()[0], issues_b.json()[0]

        evidence = client_a.get(go_url + f'/api/v1/analytics/issues/{issue_a["issue_id"]}/evidence',
                                params={'role': role})
        _assert(evidence.status_code == 200 and evidence.json(),
                f'evidence route failed: {evidence.status_code} {evidence.text}')
        state = client_a.patch(go_url + f'/api/v1/analytics/issues/{issue_a["issue_id"]}/state',
                               params={'role': role}, headers={'Origin': go_url},
                               json={'workflow': 'watching', 'pinned': True, 'mark_read': True})
        _assert(state.status_code == 200 and state.json().get('workflow') == 'watching',
                f'issue state update failed: {state.status_code} {state.text}')
        state_read = client_a.get(go_url + f'/api/v1/analytics/issues/{issue_a["issue_id"]}/state',
                                  params={'role': role})
        _assert(state_read.status_code == 200 and state_read.json().get('pinned') is True,
                'issue state did not persist')

        question = client_a.post(go_url + f'/api/v1/analytics/issues/{issue_a["issue_id"]}/questions',
                                 params={'role': role}, headers={'Origin': go_url},
                                 json={'question': 'Как это влияет на поставку?',
                                       'conversation_id': 'unified-dialogue', 'request_id': 'question-1'})
        _assert(question.status_code == 200, f'chat question failed: {question.status_code} {question.text}')
        conversation = client_a.get(go_url + '/api/v1/analytics/conversations/unified-dialogue',
                                    params={'role': role})
        _assert(conversation.status_code == 200, f'conversation read failed: {conversation.status_code}')

        other_issue = client_a.get(go_url + f'/api/v1/analytics/issues/{issue_b["issue_id"]}',
                                   params={'role': role})
        _assert(other_issue.status_code == 404,
                f'cross-company issue access was not isolated: {other_issue.status_code}')
        documents = client_a.get(go_url + '/api/v1/analytics/documents', params={'role': role})
        _assert(documents.status_code == 200 and any(row['file_id'] == file_a['id'] and row['status'] == 'ready'
                                                     for row in documents.json()),
                f'original document was not processed by analytics worker: {documents.text}')
        _assert(any(row['file_id'] == file_b['id'] and row['status'] == 'ready'
                    for row in client_b.get(go_url + '/api/v1/analytics/documents', params={'role': role}).json()),
                'second company document was not processed')

        # Restart analytics runtime and Go server/worker; persisted docs, feed and session must stay stable.
        issue_count_a = len(issues_a.json())
        feed_ids_a = [row['id'] for row in client_a.get(go_url + f'/api/v1/users/{user_a}/feed',
                                                       params={'role': role}).json()]
        synthetic_calls_before_restart = len(gateway.calls)
        docs_history = service.store.history('document', 'backend-file:' + str(file_a['id']),
                                             tenant_id='alpha', company_id=str(company_a))
        _assert(len(docs_history) == 2,
                f'one document ingestion should have received/ready records, got {len(docs_history)}')

        analytics.close()
        analytics = None
        llm.close()
        service, llm, gateway = _new_analytics_service(child_dsn, temp_path / 'documents')
        analytics = RunningAPI(service, backend, analytics_port)
        _wait_http(analytics.url + '/readyz')
        with httpx.Client(base_url=go_url, follow_redirects=False, trust_env=False, timeout=30) as backend_client:
            run_once(service, backend, backend_client, internal_token=INTERNAL_TOKEN)
        docs_history_after = service.store.history('document', 'backend-file:' + str(file_a['id']),
                                                   tenant_id='alpha', company_id=str(company_a))
        _assert(len(docs_history_after) == 2 and len(fixture.gets) == 3,
                'analytics worker restart duplicated document ingestion or object downloads')
        calls_before_read_checks = len(gateway.calls)

        _stop_process(worker_proc)
        worker_proc = None
        _stop_process(server_proc)
        server_proc = None
        server_proc = _start_process([str(server_binary)], env, go_root, server_log)
        _wait_http(go_url + '/readyz', server_proc, server_log)
        worker_proc = _start_process([str(worker_binary)], env, go_root, worker_log)
        _wait_for_feed(client_a, go_url, user_a, role)
        time.sleep(1)
        reloaded = client_a.get(go_url + f'/api/v1/users/{user_a}/feed', params={'role': role})
        _assert(reloaded.status_code == 200, f'Go API restart lost the session: {reloaded.status_code}')
        _assert([row['id'] for row in reloaded.json()] == feed_ids_a,
                f'Go worker restart duplicated or removed feed rows: {feed_ids_a} -> '
                f'{[row["id"] for row in reloaded.json()]}')
        final_issues = client_a.get(go_url + '/api/v1/analytics/issues', params={'role': role})
        _assert(final_issues.status_code == 200 and len(final_issues.json()) == issue_count_a,
                'analytics restart changed persisted issue count')
        _assert(len(gateway.calls) == calls_before_read_checks,
                'read-only API checks after restart triggered synthetic model calls')
        _assert(synthetic_calls_before_restart > 0,
                'synthetic LLM gateway was never exercised')
        print(json.dumps({
            'status': 'passed', 'database': child_name,
            'companies': [company_a, company_b], 'news_feed_rows': len(feed_ids_a),
            'internal_file_reads': 1,
            'worker_file_downloads': downloads_after_first_sync - downloads_before_worker,
            'synthetic_model_calls': synthetic_calls_before_restart + len(gateway.calls),
            'read_only_model_calls_after_restart': len(gateway.calls) - calls_before_read_checks,
            'analytics_worker_mode': 'single-pass run_once smoke adapter',
            'cross_company_issue_status': other_issue.status_code,
        }, ensure_ascii=False))

        anonymous.close()
        client_a.close()
        client_b.close()
    finally:
        if analytics is not None:
            analytics.close()
        if llm is not None:
            llm.close()
        _stop_process(worker_proc)
        _stop_process(server_proc)
        fixture.close()
        temp.cleanup()
        for client in (anonymous, client_a, client_b):
            if client is not None:
                client.close()
        _drop_child_database(maintenance_dsn, child_name, base_name, base_created)


if __name__ == '__main__':
    main()
