CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE analytics.records (
    kind        TEXT NOT NULL CHECK (kind <> ''),
    tenant_id   TEXT NOT NULL DEFAULT '',
    company_id  TEXT NOT NULL DEFAULT '',
    record_key  TEXT NOT NULL CHECK (record_key <> ''),
    version     INTEGER NOT NULL CHECK (version > 0),
    payload     JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((kind IN ('article', 'event', 'entity') AND tenant_id='' AND company_id='')
        OR (kind NOT IN ('article', 'event', 'entity') AND tenant_id<>'' AND company_id<>'')),
    PRIMARY KEY (kind, tenant_id, company_id, record_key, version)
);

CREATE TABLE analytics.record_heads (
    kind        TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    company_id  TEXT NOT NULL,
    record_key  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    PRIMARY KEY (kind, tenant_id, company_id, record_key),
    FOREIGN KEY (kind, tenant_id, company_id, record_key, version)
        REFERENCES analytics.records(kind, tenant_id, company_id, record_key, version)
);

CREATE INDEX records_scope_created_idx ON analytics.records
    (kind, tenant_id, company_id, created_at DESC);

CREATE TABLE analytics.cache (
    cache_key   TEXT PRIMARY KEY,
    payload     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE analytics.budgets (
    account       TEXT PRIMARY KEY,
    blocked_until TIMESTAMPTZ NOT NULL
);

CREATE TABLE analytics.calls (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account           TEXT NOT NULL,
    stage             TEXT NOT NULL,
    model             TEXT NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        INTEGER
);

CREATE INDEX calls_account_started_idx ON analytics.calls (account, started_at DESC);
