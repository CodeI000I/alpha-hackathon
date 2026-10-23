"""Tenant-scoped versioned records backed by PostgreSQL or an in-memory test store."""

from __future__ import annotations

import copy
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import threading
import time
from typing import Any, Iterator

from ..models import canonical, digest


GLOBAL_KINDS = frozenset({'article', 'event', 'entity'})


class ScopeRequired(ValueError):
    """A private record operation omitted tenant or company scope."""


class RevisionConflict(RuntimeError):
    """The requested write was based on a stale record version."""


@dataclass(frozen=True)
class Record:
    key: str
    version: int
    payload: dict[str, Any]
    created_at: datetime


def _scope(kind: str, tenant_id: str, company_id: str) -> tuple[str, str]:
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError('kind must not be blank')
    if not isinstance(tenant_id, str) or not isinstance(company_id, str):
        raise TypeError('tenant_id and company_id must be strings')
    if kind in GLOBAL_KINDS:
        if tenant_id or company_id:
            raise ValueError('global records cannot have tenant or company scope')
        return '', ''
    if not tenant_id.strip() or not company_id.strip():
        raise ScopeRequired(f'{kind} records require tenant_id and company_id')
    return tenant_id, company_id


def _key(kind: str, tenant_id: str, company_id: str, key: str) -> tuple[str, str, str, str]:
    if not isinstance(key, str) or not key.strip():
        raise ValueError('key must not be blank')
    tenant_id, company_id = _scope(kind, tenant_id, company_id)
    return kind, tenant_id, company_id, key


def _json_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(payload, dict):
        raise TypeError('payload must be a dict')
    encoded = canonical(payload)
    return json.loads(encoded), encoded


def _copy_record(record: Record) -> Record:
    return Record(record.key, record.version, json.loads(canonical(record.payload)), record.created_at)


def _vector(values: list[float] | tuple[float, ...] | None) -> list[float] | None:
    if values is None:
        return None
    if not values or any(not math.isfinite(float(value)) for value in values):
        raise ValueError('vector must contain finite values')
    result = [float(value) for value in values]
    if not any(result):
        raise ValueError('vector must have nonzero magnitude')
    return result


class MemoryStore:
    """Thread-safe in-memory adapter for offline unit tests."""

    def __init__(self):
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str, str, str], list[Record]] = defaultdict(list)
        self._documents: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._embedding_dimensions: dict[tuple[str, str], int] = {}
        self._cache: dict[str, Any] = {}
        self._cache_updated_at: dict[str, datetime] = {}
        self._budget: dict[str, float] = {}
        self._calls: dict[int, dict[str, Any]] = {}
        self._next_call_id = 1
        self._key_locks: dict[str, threading.RLock] = {}

    @contextmanager
    def transaction(self):
        """Group writes atomically; nested use is safe because the lock is reentrant."""
        with self._lock:
            state = copy.deepcopy((self._records, self._documents, self._embedding_dimensions,
                                   self._cache, self._cache_updated_at, self._budget, self._calls,
                                   self._next_call_id))
            try:
                yield self
            except BaseException:
                (self._records, self._documents, self._embedding_dimensions, self._cache,
                 self._cache_updated_at, self._budget, self._calls, self._next_call_id) = state
                raise

    def put(self, kind, key, payload, *, tenant_id='', company_id='', expected_version=None) -> Record:
        identity = _key(kind, tenant_id, company_id, key)
        value, encoded = _json_payload(payload)
        if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
            raise ValueError('expected_version must be a non-negative integer')
        with self._lock:
            history = self._records[identity]
            current = history[-1] if history else None
            current_version = current.version if current else 0
            if expected_version is not None and expected_version != current_version:
                raise RevisionConflict(f'expected version {expected_version}, found {current_version}')
            if current is not None and canonical(current.payload) == encoded:
                return _copy_record(current)
            record = Record(key, current_version + 1, value, datetime.now(timezone.utc))
            history.append(record)
            return _copy_record(record)

    def get(self, kind, key, *, tenant_id='', company_id='', version=None) -> Record | None:
        identity = _key(kind, tenant_id, company_id, key)
        if version is not None and (type(version) is not int or version <= 0):
            raise ValueError('version must be a positive integer')
        with self._lock:
            history = self._records.get(identity, ())
            if version is None:
                return _copy_record(history[-1]) if history else None
            record = next((record for record in history if record.version == version), None)
            return _copy_record(record) if record else None

    def list(self, kind, *, tenant_id='', company_id='') -> list[Record]:
        tenant_id, company_id = _scope(kind, tenant_id, company_id)
        with self._lock:
            return [_copy_record(items[-1]) for identity, items in self._records.items()
                    if identity[:3] == (kind, tenant_id, company_id) and items]

    def history(self, kind, key, *, tenant_id='', company_id='') -> list[Record]:
        identity = _key(kind, tenant_id, company_id, key)
        with self._lock:
            return [_copy_record(record) for record in self._records.get(identity, ())]

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        if not key:
            raise ValueError('lock key must not be blank')
        with self._lock:
            lock = self._key_locks.setdefault(key, threading.RLock())
        with lock:
            yield

    def index_text(self, kind, key, text, *, tenant_id='', company_id='', vector=None,
                   model_id='', model_version='', text_version='') -> None:
        identity = _key(kind, tenant_id, company_id, key)
        if not isinstance(text, str):
            raise TypeError('text must be a string')
        embedding = _vector(vector)
        if embedding is not None and (not model_id or not model_version or not text_version):
            raise ValueError('vector entries require model_id, model_version and text_version')
        with self._lock:
            if embedding is not None:
                model = (model_id, model_version)
                dimension = self._embedding_dimensions.setdefault(model, len(embedding))
                if dimension != len(embedding):
                    raise ValueError('embedding dimension changed for the same model version')
            self._documents[identity] = dict(text=text, vector=embedding, model_id=model_id,
                                             model_version=model_version, text_version=text_version)

    def search(self, query, *, tenant_id, company_id, query_vector=None, model_id='',
               model_version='', limit=20) -> list[dict[str, Any]]:
        if not tenant_id or not company_id:
            raise ScopeRequired('search requires tenant_id and company_id')
        if not isinstance(query, str) or type(limit) is not int or limit <= 0:
            raise ValueError('query must be a string and limit must be positive')
        query_vector = _vector(query_vector)
        if query_vector is not None and (not model_id or not model_version):
            raise ValueError('vector search requires model_id and model_version')
        query_terms = set(re.findall(r'[\w]+', query.lower().replace('ё', 'е')))
        found = {}
        with self._lock:
            if query_vector is not None:
                dimension = self._embedding_dimensions.get((model_id, model_version))
                if dimension is not None and dimension != len(query_vector):
                    raise ValueError('query vector dimension does not match the model version')
            documents = list(self._documents.items())
        for (kind, doc_tenant, doc_company, key), document in documents:
            if (doc_tenant, doc_company) not in {('', ''), (tenant_id, company_id)}:
                continue
            channels = []
            score = 0.0
            document_terms = set(re.findall(r'[\w]+', document['text'].lower().replace('ё', 'е')))
            overlap = query_terms & document_terms
            if overlap:
                channels.append('fts')
                score = float(len(overlap))
            vector = document['vector']
            if (query_vector is not None and vector is not None and len(query_vector) == len(vector)
                    and document['model_id'] == model_id and document['model_version'] == model_version):
                dot = sum(left * right for left, right in zip(query_vector, vector))
                norm = math.sqrt(sum(value * value for value in query_vector) * sum(value * value for value in vector))
                if norm:
                    channels.append('vector')
                    score = max(score, dot / norm)
            if channels:
                found[(kind, key)] = dict(kind=kind, key=key, score=score,
                                          channel='+'.join(channels))
        return sorted(found.values(), key=lambda row: (-row['score'], row['kind'], row['key']))[:limit]

    def cache_get(self, key):
        with self._lock:
            value = self._cache.get(key)
            return json.loads(canonical(value)) if value is not None else None

    def cache_put(self, key, value):
        with self._lock:
            self._cache[key] = json.loads(canonical(value))
            self._cache_updated_at[key] = datetime.now(timezone.utc)

    def blocked_until(self, account):
        with self._lock:
            return self._budget.get(account, 0)

    def block_budget(self, account, until):
        with self._lock:
            self._budget[account] = until

    def reserve_call(self, account, stage, model, rpm, now):
        if type(rpm) is not int or rpm <= 0:
            raise ValueError('rpm must be a positive integer')
        with self._lock:
            recent = [row['at'] for row in self._calls.values()
                      if row['account'] == account and row['at'] > now - 60]
            if len(recent) >= rpm:
                return None, min(recent) + 60
            call_id = self._next_call_id
            self._next_call_id += 1
            self._calls[call_id] = dict(account=account, stage=stage, model=model, at=now,
                                        status='started', prompt_tokens=None, completion_tokens=None,
                                        finished_at=None, latency_ms=None)
            return call_id, 0

    def record_call(self, call_id, status, usage=None):
        with self._lock:
            row = self._calls.get(call_id)
            if row is None:
                return
            row.update(status=status, finished_at=time.time(),
                       prompt_tokens=getattr(usage, 'prompt_tokens', None),
                       completion_tokens=getattr(usage, 'completion_tokens', None))
            row['latency_ms'] = max(0, round((row['finished_at'] - row['at']) * 1000))

    def metrics(self):
        with self._lock:
            groups = {}
            for row in self._calls.values():
                key = row['stage'], row['status'], row['model']
                group = groups.setdefault(key, dict(stage=key[0], status=key[1], model=key[2], calls=0,
                                                     prompt_tokens=0, completion_tokens=0,
                                                     latency_ms=0, estimated_cost=None))
                group['calls'] += 1
                group['prompt_tokens'] += row['prompt_tokens'] or 0
                group['completion_tokens'] += row['completion_tokens'] or 0
                group['latency_ms'] += row['latency_ms'] or 0
            return list(groups.values())

    def cleanup_operational(self, before: datetime, *, checkpoints: bool = True) -> dict[str, int]:
        """Delete expired operational data while retaining all business records."""
        if not isinstance(before, datetime) or before.tzinfo is None or before.utcoffset() is None:
            raise ValueError('before must be a timezone-aware datetime')
        cutoff = before.astimezone(timezone.utc)
        cutoff_epoch = cutoff.timestamp()
        with self._lock:
            stale_cache = [key for key, updated_at in self._cache_updated_at.items()
                           if updated_at < cutoff]
            for key in stale_cache:
                self._cache.pop(key, None)
                self._cache_updated_at.pop(key, None)
            stale_calls = [call_id for call_id, row in self._calls.items()
                           if row['finished_at'] is not None and row['finished_at'] < cutoff_epoch]
            for call_id in stale_calls:
                del self._calls[call_id]
            stale_budgets = [account for account, blocked_until in self._budget.items()
                             if blocked_until < cutoff_epoch]
            for account in stale_budgets:
                del self._budget[account]
            return dict(cache=len(stale_cache), calls=len(stale_calls), budgets=len(stale_budgets),
                        checkpoints=0)


class PostgresStore:
    """Psycopg 3 store; no PostgreSQL driver is imported until the adapter is used."""

    def __init__(self, dsn: str, *, connect_timeout: int = 5, statement_timeout_ms: int = 5000):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError('dsn is required')
        if type(connect_timeout) is not int or connect_timeout <= 0:
            raise ValueError('connect_timeout must be a positive integer')
        if type(statement_timeout_ms) is not int or statement_timeout_ms <= 0:
            raise ValueError('statement_timeout_ms must be a positive integer')
        self._dsn = dsn
        self._connect_timeout = connect_timeout
        self._statement_timeout_ms = statement_timeout_ms
        self._local = threading.local()

    @contextmanager
    def _connect(self):
        existing = getattr(self._local, 'connection', None)
        if existing is not None:
            yield existing
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('PostgreSQLStore requires psycopg 3') from exc
        connection = psycopg.connect(self._dsn, connect_timeout=self._connect_timeout,
                                     options=f'-c statement_timeout={self._statement_timeout_ms}',
                                     row_factory=dict_row)
        try:
            with connection:
                self._local.connection = connection
                yield connection
        finally:
            self._local.connection = None
            connection.close()

    @contextmanager
    def transaction(self):
        """Run multiple store methods on one transaction and connection."""
        existing = getattr(self._local, 'connection', None)
        if existing is not None:
            with existing.transaction():
                yield self
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('PostgreSQLStore requires psycopg 3') from exc
        connection = psycopg.connect(self._dsn, connect_timeout=self._connect_timeout,
                                     options=f'-c statement_timeout={self._statement_timeout_ms}',
                                     row_factory=dict_row)
        try:
            with connection:
                self._local.connection = connection
                yield self
        finally:
            self._local.connection = None
            connection.close()

    @staticmethod
    def _identity(kind, key, tenant_id, company_id):
        return _key(kind, tenant_id, company_id, key)

    @staticmethod
    def _record(row) -> Record:
        return Record(key=row['record_key'], version=row['version'], payload=row['payload'],
                      created_at=row['created_at'])

    def put(self, kind, key, payload, *, tenant_id='', company_id='', expected_version=None) -> Record:
        identity = self._identity(kind, key, tenant_id, company_id)
        value, encoded = _json_payload(payload)
        from psycopg.types.json import Jsonb
        if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
            raise ValueError('expected_version must be a non-negative integer')

        query_key = '\x1f'.join(identity)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (query_key,))
                cursor.execute('''
                    SELECT r.* FROM analytics.record_heads h
                    JOIN analytics.records r USING (kind, tenant_id, company_id, record_key, version)
                    WHERE h.kind=%s AND h.tenant_id=%s AND h.company_id=%s AND h.record_key=%s
                    FOR UPDATE OF h
                ''', identity)
                row = cursor.fetchone()
                current_version = row['version'] if row else 0
                if expected_version is not None and expected_version != current_version:
                    raise RevisionConflict(f'expected version {expected_version}, found {current_version}')
                if row is not None and canonical(row['payload']) == encoded:
                    return self._record(row)
                version = current_version + 1
                cursor.execute('''
                    INSERT INTO analytics.records (kind, tenant_id, company_id, record_key, version, payload)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
                ''', (*identity, version, Jsonb(value)))
                record = self._record(cursor.fetchone())
                cursor.execute('''
                    INSERT INTO analytics.record_heads (kind, tenant_id, company_id, record_key, version)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (kind, tenant_id, company_id, record_key)
                    DO UPDATE SET version=EXCLUDED.version
                ''', (*identity, version))
        return record

    def get(self, kind, key, *, tenant_id='', company_id='', version=None) -> Record | None:
        identity = self._identity(kind, key, tenant_id, company_id)
        if version is None:
            query = '''SELECT r.* FROM analytics.record_heads h JOIN analytics.records r
                USING (kind, tenant_id, company_id, record_key, version)
                WHERE h.kind=%s AND h.tenant_id=%s AND h.company_id=%s AND h.record_key=%s'''
            params = identity
        else:
            if type(version) is not int or version <= 0:
                raise ValueError('version must be a positive integer')
            query = '''SELECT * FROM analytics.records WHERE kind=%s AND tenant_id=%s AND company_id=%s
                AND record_key=%s AND version=%s'''
            params = (*identity, version)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return self._record(row) if row else None

    def list(self, kind, *, tenant_id='', company_id='') -> list[Record]:
        tenant_id, company_id = _scope(kind, tenant_id, company_id)
        with self._connect() as connection:
            rows = connection.execute('''
                SELECT r.* FROM analytics.record_heads h JOIN analytics.records r
                USING (kind, tenant_id, company_id, record_key, version)
                WHERE h.kind=%s AND h.tenant_id=%s AND h.company_id=%s
                ORDER BY h.record_key
            ''', (kind, tenant_id, company_id)).fetchall()
        return [self._record(row) for row in rows]

    def history(self, kind, key, *, tenant_id='', company_id='') -> list[Record]:
        identity = self._identity(kind, key, tenant_id, company_id)
        with self._connect() as connection:
            rows = connection.execute('''
                SELECT * FROM analytics.records WHERE kind=%s AND tenant_id=%s AND company_id=%s
                    AND record_key=%s ORDER BY version
            ''', identity).fetchall()
        return [self._record(row) for row in rows]

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        if not key:
            raise ValueError('lock key must not be blank')
        locks = getattr(self._local, 'locks', None)
        if locks is None:
            locks = self._local.locks = {}
        held = locks.get(key)
        if held is not None:
            connection, depth = held
            locks[key] = (connection, depth + 1)
            try:
                yield
            finally:
                locks[key] = (connection, depth)
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('PostgreSQLStore requires psycopg 3') from exc
        connection = psycopg.connect(self._dsn, connect_timeout=self._connect_timeout,
                                     options=f'-c statement_timeout={self._statement_timeout_ms}',
                                     row_factory=dict_row, autocommit=True)
        locks[key] = (connection, 1)
        try:
            connection.execute('SELECT pg_advisory_lock(hashtextextended(%s, 0))', (key,))
            try:
                yield
            finally:
                connection.execute('SELECT pg_advisory_unlock(hashtextextended(%s, 0))', (key,))
        finally:
            locks.pop(key, None)
            connection.close()

    def index_text(self, kind, key, text, *, tenant_id='', company_id='', vector=None,
                   model_id='', model_version='', text_version='') -> None:
        identity = self._identity(kind, key, tenant_id, company_id)
        if not isinstance(text, str):
            raise TypeError('text must be a string')
        vector = _vector(vector)
        if vector is not None and (not model_id or not model_version or not text_version):
            raise ValueError('vector entries require model_id, model_version and text_version')
        vector_text = '[' + ','.join(format(value, '.17g') for value in vector) + ']' if vector else None
        with self._connect() as connection:
            if vector is not None:
                connection.execute('''INSERT INTO analytics.embedding_models(model_id,model_version,dimension)
                    VALUES (%s,%s,%s) ON CONFLICT(model_id,model_version) DO NOTHING''',
                                   (model_id, model_version, len(vector)))
                dimension = connection.execute('''SELECT dimension FROM analytics.embedding_models
                    WHERE model_id=%s AND model_version=%s''', (model_id, model_version)).fetchone()['dimension']
                if dimension != len(vector):
                    raise ValueError('embedding dimension changed for the same model version')
            connection.execute('''
                INSERT INTO analytics.search_documents
                    (kind, tenant_id, company_id, record_key, text, embedding, model_id, model_version,
                     dimension, text_version)
                VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s)
                ON CONFLICT (kind, tenant_id, company_id, record_key) DO UPDATE SET
                    text=EXCLUDED.text, embedding=EXCLUDED.embedding, model_id=EXCLUDED.model_id,
                    model_version=EXCLUDED.model_version, dimension=EXCLUDED.dimension,
                    text_version=EXCLUDED.text_version, updated_at=clock_timestamp()
            ''', (*identity, text, vector_text, model_id, model_version, len(vector) if vector else None,
                  text_version))

    def search(self, query, *, tenant_id, company_id, query_vector=None, model_id='',
               model_version='', limit=20) -> list[dict[str, Any]]:
        if not tenant_id or not company_id:
            raise ScopeRequired('search requires tenant_id and company_id')
        if not isinstance(query, str) or type(limit) is not int or limit <= 0:
            raise ValueError('query must be a string and limit must be positive')
        query_vector = _vector(query_vector)
        if query_vector is not None and (not model_id or not model_version):
            raise ValueError('vector search requires model_id and model_version')
        vector_text = '[' + ','.join(format(value, '.17g') for value in query_vector) + ']' if query_vector else None
        if query_vector is not None:
            with self._connect() as connection:
                row = connection.execute('''SELECT dimension FROM analytics.embedding_models
                    WHERE model_id=%s AND model_version=%s''', (model_id, model_version)).fetchone()
            if row is not None and row['dimension'] != len(query_vector):
                raise ValueError('query vector dimension does not match the model version')
        vector_cte = ''
        params: list[Any] = [query, tenant_id, company_id]
        if vector_text is not None:
            vector_cte = '''
                UNION ALL
                SELECT d.kind, d.record_key AS key, 1 - (d.embedding <=> %s::vector) AS score, 'vector' AS channel
                FROM analytics.search_documents d
                WHERE d.embedding IS NOT NULL AND d.dimension=%s AND d.model_id=%s AND d.model_version=%s
                  AND ((d.tenant_id='' AND d.company_id='') OR (d.tenant_id=%s AND d.company_id=%s))
            '''
            params.extend([vector_text, len(query_vector), model_id, model_version, tenant_id, company_id])
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(f'''
                WITH ts AS (SELECT plainto_tsquery('russian', %s) AS query), matches AS (
                    SELECT d.kind, d.record_key AS key,
                           ts_rank_cd(d.search_vector, ts.query) AS score, 'fts' AS channel
                    FROM analytics.search_documents d CROSS JOIN ts
                    WHERE d.search_vector @@ ts.query
                      AND ((d.tenant_id='' AND d.company_id='') OR (d.tenant_id=%s AND d.company_id=%s))
                    {vector_cte}
                )
                SELECT kind, key, max(score)::double precision AS score,
                       string_agg(DISTINCT channel, '+' ORDER BY channel) AS channel
                FROM matches GROUP BY kind, key ORDER BY score DESC, kind, key LIMIT %s
            ''', params).fetchall()
        return [dict(row) for row in rows]

    def cache_get(self, key):
        with self._connect() as connection:
            row = connection.execute('SELECT payload FROM analytics.cache WHERE cache_key=%s', (key,)).fetchone()
        return row['payload'] if row else None

    def cache_put(self, key, value):
        from psycopg.types.json import Jsonb
        payload, _ = _json_payload(value)
        with self._connect() as connection:
            connection.execute('''INSERT INTO analytics.cache(cache_key,payload) VALUES (%s,%s)
                ON CONFLICT(cache_key) DO UPDATE SET payload=EXCLUDED.payload, updated_at=clock_timestamp()''',
                               (key, Jsonb(payload)))

    def blocked_until(self, account):
        with self._connect() as connection:
            row = connection.execute('SELECT blocked_until FROM analytics.budgets WHERE account=%s',
                                     (account,)).fetchone()
        return row['blocked_until'].timestamp() if row else 0

    def block_budget(self, account, until):
        from datetime import datetime
        with self._connect() as connection:
            connection.execute('''INSERT INTO analytics.budgets(account,blocked_until) VALUES (%s,%s)
                ON CONFLICT(account) DO UPDATE SET blocked_until=EXCLUDED.blocked_until''',
                               (account, datetime.fromtimestamp(until, timezone.utc)))

    def reserve_call(self, account, stage, model, rpm, now):
        if type(rpm) is not int or rpm <= 0:
            raise ValueError('rpm must be a positive integer')
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('analytics-calls:' + account,))
                cursor.execute('''SELECT started_at FROM analytics.calls WHERE account=%s
                    AND started_at > to_timestamp(%s) - interval '60 seconds' ORDER BY started_at''', (account, now))
                recent = cursor.fetchall()
                if len(recent) >= rpm:
                    return None, recent[0]['started_at'].timestamp() + 60
                cursor.execute('''INSERT INTO analytics.calls(account,stage,model,started_at,status)
                    VALUES (%s,%s,%s,to_timestamp(%s),'started') RETURNING id''', (account, stage, model, now))
                return cursor.fetchone()['id'], 0

    def record_call(self, call_id, status, usage=None):
        with self._connect() as connection:
            connection.execute('''UPDATE analytics.calls SET status=%s, finished_at=clock_timestamp(),
                prompt_tokens=%s, completion_tokens=%s,
                latency_ms=greatest(0, round(extract(epoch FROM (clock_timestamp()-started_at))*1000)::integer)
                WHERE id=%s''', (status, getattr(usage, 'prompt_tokens', None),
                                 getattr(usage, 'completion_tokens', None), call_id))

    def metrics(self):
        with self._connect() as connection:
            rows = connection.execute('''SELECT stage, status, model, count(*) AS calls,
                coalesce(sum(prompt_tokens), 0) AS prompt_tokens,
                coalesce(sum(completion_tokens), 0) AS completion_tokens,
                coalesce(sum(latency_ms), 0) AS latency_ms
                FROM analytics.calls GROUP BY stage, status, model ORDER BY stage, status, model''').fetchall()
        return [dict(row, estimated_cost=None) for row in rows]

    def cleanup_operational(self, before: datetime, *, checkpoints: bool = True) -> dict[str, int]:
        """Retain business history; purge expired operations and completed impact checkpoints.

        Checkpoint candidates are selected only from the latest completed run records
        older than the cutoff, then deleted through LangGraph's supported API using
        the exact ``impact:`` thread prefix. Run records themselves are never deleted.
        """
        if not isinstance(before, datetime) or before.tzinfo is None or before.utcoffset() is None:
            raise ValueError('before must be a timezone-aware datetime')
        cutoff = before.astimezone(timezone.utc)

        # LangGraph's API deletes a whole thread, so derive candidates from latest
        # run heads and keep the namespace narrow. The first query is only a hint:
        # recheck each run under the same company lock used by the worker before
        # calling delete_thread, closing the select/delete race.
        with self._connect() as connection:
            has_checkpoint_tables = connection.execute(
                "SELECT to_regclass('public.checkpoints') IS NOT NULL AS present").fetchone()['present']
            if checkpoints and has_checkpoint_tables:
                rows = connection.execute('''
                    SELECT r.record_key, r.tenant_id, r.company_id FROM analytics.record_heads h
                    JOIN analytics.records r USING (kind, tenant_id, company_id, record_key, version)
                    WHERE h.kind='run' AND r.payload->>'status'='completed' AND r.created_at < %s
                    ORDER BY r.tenant_id, r.company_id, r.record_key
                ''', (cutoff,)).fetchall()
            else:
                rows = []
        checkpoint_count = 0
        if rows:
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
            except ImportError as exc:
                raise RuntimeError('LangGraph PostgresSaver is required to clean impact checkpoints') from exc
            with PostgresSaver.from_conn_string(self._dsn) as saver:
                for candidate in rows:
                    scope = dict(tenant_id=candidate['tenant_id'], company_id=candidate['company_id'])
                    lock_key = 'company:' + digest(scope)
                    with self.lock(lock_key):
                        with self._connect() as connection:
                            current = connection.execute('''
                                SELECT r.record_key FROM analytics.record_heads h
                                JOIN analytics.records r USING (kind, tenant_id, company_id, record_key, version)
                                WHERE h.kind='run' AND h.tenant_id=%s AND h.company_id=%s
                                  AND h.record_key=%s AND r.payload->>'status'='completed'
                                  AND r.created_at < %s
                            ''', (scope['tenant_id'], scope['company_id'], candidate['record_key'], cutoff)).fetchone()
                        if current is None:
                            continue
                        saver.delete_thread('impact:' + current['record_key'])
                        checkpoint_count += 1

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM analytics.cache WHERE updated_at < %s', (cutoff,))
                cache_count = cursor.rowcount
                cursor.execute('''DELETE FROM analytics.calls
                    WHERE finished_at IS NOT NULL AND finished_at < %s''', (cutoff,))
                calls_count = cursor.rowcount
                cursor.execute('DELETE FROM analytics.budgets WHERE blocked_until < %s', (cutoff,))
                budgets_count = cursor.rowcount
        return dict(cache=cache_count, calls=calls_count, budgets=budgets_count,
                    checkpoints=checkpoint_count)

    def close(self):
        """Present for parity with connection-owning stores; connections are operation-scoped."""
