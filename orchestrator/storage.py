"""Durable single-host storage. SQLite transactions also coordinate local workers."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .models import canonical, digest


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS snapshots (
                    kind TEXT, entity TEXT, version TEXT, payload TEXT NOT NULL,
                    PRIMARY KEY(kind, entity, version));
                CREATE TABLE IF NOT EXISTS latest (
                    kind TEXT, entity TEXT, version TEXT NOT NULL, PRIMARY KEY(kind, entity));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, company_id INTEGER, event_id INTEGER, role TEXT,
                    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL DEFAULT 0,
                    result TEXT, error TEXT, retry_at REAL DEFAULT 0, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS budget (key TEXT PRIMARY KEY, blocked_until REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY, account TEXT, stage TEXT, model TEXT, at REAL,
                    status TEXT, prompt_tokens INTEGER, completion_tokens INTEGER);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, owner TEXT, company_id INTEGER, job_id TEXT,
                    messages TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS case_states (
                    owner TEXT, case_id TEXT, workflow TEXT NOT NULL DEFAULT 'open',
                    pinned INTEGER NOT NULL DEFAULT 0, last_read_version TEXT,
                    PRIMARY KEY(owner, case_id));
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put_jobs(self, news, company, roles, policy):
        """Snapshots + durable dispatch are atomic, so redelivery repairs interrupted work."""
        ids = []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for kind, item in [('news', news), ('company', company)]:
                inserted = db.execute('INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?)',
                                      (kind, str(item.id), item.version, canonical(item))).rowcount
                if inserted:
                    # shortcut: unseen revisions follow arrival order; require source revisions for unordered ingestion.
                    db.execute('INSERT OR REPLACE INTO latest VALUES (?, ?, ?)',
                               (kind, str(item.id), item.version))
                    if kind == 'news' and news.situation_id:
                        db.execute('INSERT OR REPLACE INTO latest VALUES (?, ?, ?)',
                                   ('situation', news.situation_id, news.version))
            for role in roles:
                payload = self.job_payload(news, company, role, policy)
                job_id = digest(payload)
                db.execute('''INSERT OR IGNORE INTO jobs
                    (id, company_id, event_id, role, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)''',
                           (job_id, company.id, news.id, role, canonical(payload), time.time()))
                ids.append(job_id)
        return ids

    @staticmethod
    def job_payload(news, company, role, policy):
        return dict(news=news.model_dump(mode='json', by_alias=True),
                    company=company.model_dump(mode='json', by_alias=True), role=role, policy=policy)

    def get_job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for name in ('payload', 'result', 'error'):
            result[name] = json.loads(result[name]) if result[name] else None
        return result

    def current(self, job, policy=None):
        payload = job['payload']
        if policy is not None and payload['policy'] != policy:
            return False
        with self.connect() as db:
            for kind, field in [('news', 'news'), ('company', 'company')]:
                row = db.execute('SELECT version FROM latest WHERE kind=? AND entity=?',
                                 (kind, str(payload[field]['id']))).fetchone()
                if row is None or row[0] != digest(payload[field]):
                    return False
            situation = payload['news'].get('situationId')
            if situation:
                row = db.execute('SELECT version FROM latest WHERE kind=? AND entity=?',
                                 ('situation', situation)).fetchone()
                if row is None or row[0] != digest(payload['news']):
                    return False
        return True

    def history(self, job):
        with self.connect() as db:
            rows = db.execute('SELECT id,event_id,status,created_at,payload FROM jobs WHERE company_id=? AND role=? ORDER BY created_at',
                              (job['company_id'], job['role'])).fetchall()
        situation = job['payload']['news'].get('situationId')
        return [dict(id=r['id'], event_id=r['event_id'], status=r['status'], created_at=r['created_at'])
                for r in rows if r['event_id'] == job['event_id'] or
                (situation and json.loads(r['payload'])['news'].get('situationId') == situation)]

    def changes(self, job):
        previous = None
        for item in self.history(job):
            if item['id'] == job['id']:
                break
            if item['status'] == 'ready':
                previous = self.get_job(item['id'])
        if previous is None:
            return None
        before, after = previous['payload'], job['payload']
        inputs = [name for name in ('news', 'company', 'policy') if before[name] != after[name]]
        fields = []
        for name in ('profile', 'facts'):
            left, right = before['company'][name], after['company'][name]
            if name == 'facts':
                left, right = ({f['id']: f for f in facts} for facts in (left, right))
            fields.extend(f'{name}:{key}' for key in sorted(left.keys() | right.keys())
                          if left.get(key) != right.get(key))
        old_report = (previous['result'] or {}).get('report')
        new_report = (job['result'] or {}).get('report')
        return dict(previous_version=previous['id'], changed_inputs=inputs, changed_facts=fields,
                    analysis_changed=None if new_report is None else old_report != new_report)

    def user_state(self, job, owner, patch=None):
        news = job['payload']['news']
        entity = ('situation', news['situationId']) if news.get('situationId') else ('news', news['id'])
        case_id = digest([job['company_id'], job['role'], entity])
        with self.connect() as db:
            if patch is not None:
                db.execute('INSERT OR IGNORE INTO case_states(owner,case_id) VALUES(?,?)', (owner, case_id))
                db.execute('''UPDATE case_states SET workflow=COALESCE(?,workflow), pinned=COALESCE(?,pinned),
                    last_read_version=COALESCE(?,last_read_version) WHERE owner=? AND case_id=?''',
                           (patch.workflow, patch.pinned, job['id'] if patch.mark_read else None, owner, case_id))
            row = db.execute('SELECT workflow,pinned,last_read_version FROM case_states WHERE owner=? AND case_id=?',
                             (owner, case_id)).fetchone()
        state = dict(row) if row else dict(workflow='open', pinned=False, last_read_version=None)
        state['pinned'] = bool(state['pinned'])
        state['has_update'] = state['last_read_version'] is not None and state['last_read_version'] != job['id']
        state['unread'] = state['last_read_version'] != job['id']
        return state

    def claim(self, job_id):
        now = time.time()
        with self.connect() as db:
            self._expire_exhausted(db, now)
            # The upper bound exceeds three bounded LLM stages, including retries.
            row = db.execute('''UPDATE jobs SET status='running', attempts=attempts+1, lease_until=?
                WHERE id=? AND attempts < 3 AND (
                    status='pending' OR (status='running' AND lease_until<?)
                    OR (status='budget_exceeded' AND retry_at<=?)) RETURNING id''',
                             (now + 3600, job_id, now, now)).fetchone()
        return row is not None

    @staticmethod
    def _expire_exhausted(db, now):
        db.execute('''UPDATE jobs SET status='failed', error=?, lease_until=0
            WHERE status='running' AND attempts>=3 AND lease_until<?''',
                   (canonical({'code': 'attempts_exhausted', 'message': 'Job recovery limit reached'}), now))

    def finish(self, job_id, status, result=None, error=None, retry_at=0, *, attempt=None):
        if status == 'budget_exceeded' and attempt is not None and attempt >= 3:
            status = 'failed'
        with self.connect() as db:
            query = 'UPDATE jobs SET status=?, result=?, error=?, retry_at=?, lease_until=0 WHERE id=?'
            values = (status, canonical(result) if result is not None else None,
                      canonical(error) if error else None, retry_at, job_id)
            if attempt is not None:
                query += " AND attempts=? AND status='running'"
                values += (attempt,)
            return db.execute(query, values).rowcount == 1

    def pending(self):
        with self.connect() as db:
            self._expire_exhausted(db, time.time())
            return [row[0] for row in db.execute('''SELECT id FROM jobs WHERE attempts < 3 AND (
                status='pending' OR (status='running' AND lease_until<?)
                OR (status='budget_exceeded' AND retry_at<=?)) ORDER BY created_at''',
                                                (time.time(), time.time()))]

    def retry(self, job_id):
        with self.connect() as db:
            return db.execute('''UPDATE jobs SET status='pending' WHERE id=? AND status='failed'
                AND attempts < 3 AND retry_at<=?''', (job_id, time.time())).rowcount == 1

    def latest_news(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('''SELECT s.payload FROM snapshots s
                JOIN latest l USING(kind, entity, version) WHERE s.kind='news' ''')]

    def cache_get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM cache WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?, ?)', (key, canonical(value)))

    def blocked_until(self, account):
        with self.connect() as db:
            row = db.execute('SELECT blocked_until FROM budget WHERE key=?', (account,)).fetchone()
        return row[0] if row else 0

    def block_budget(self, account, until):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO budget VALUES (?, ?)', (account, until))

    def reserve_call(self, account, stage, model, rpm, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            recent = db.execute('SELECT at FROM calls WHERE account=? AND at>? ORDER BY at',
                                (account, now-60)).fetchall()
            if len(recent) >= rpm:
                return None, recent[0][0] + 60
            cursor = db.execute('INSERT INTO calls(account,stage,model,at,status) VALUES(?,?,?,?,?)',
                                (account, stage, model, now, 'started'))
            return cursor.lastrowid, 0

    def record_call(self, call_id, status, usage=None):
        with self.connect() as db:
            db.execute('UPDATE calls SET status=?,prompt_tokens=?,completion_tokens=? WHERE id=?',
                       (status, getattr(usage, 'prompt_tokens', None),
                        getattr(usage, 'completion_tokens', None), call_id))

    def conversation(self, conversation_id, owner, company_id, job_id):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO conversations VALUES (?, ?, ?, ?, ?, 0)',
                       (conversation_id, owner, company_id, job_id, '[]'))
            row = db.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if (row['owner'], row['company_id'], row['job_id']) != (owner, company_id, job_id):
            raise PermissionError('Conversation unavailable')
        return json.loads(row['messages']), row['revision']

    def save_conversation(self, conversation_id, revision, messages):
        with self.connect() as db:
            changed = db.execute('''UPDATE conversations SET messages=?,revision=revision+1
                WHERE id=? AND revision=?''', (canonical(messages), conversation_id, revision)).rowcount
        if not changed:
            raise ValueError('Conversation changed; reload before retrying')

    def conversations(self, owner, company_id, conversation_id=None):
        query = 'SELECT id,job_id,messages,revision FROM conversations WHERE owner=? AND company_id=?'
        params = (owner, company_id)
        if conversation_id is not None:
            query += ' AND id=?'
            params += (conversation_id,)
        with self.connect() as db:
            rows = db.execute(query + ' ORDER BY rowid DESC LIMIT 20', params).fetchall()
        return [dict(id=r['id'], report_version=r['job_id'], revision=r['revision'],
                     messages=json.loads(r['messages']) if conversation_id is not None else None) for r in rows]
