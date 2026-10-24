CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE analytics.search_documents (
    kind          TEXT NOT NULL CHECK (kind <> ''),
    tenant_id     TEXT NOT NULL DEFAULT '',
    company_id    TEXT NOT NULL DEFAULT '',
    record_key    TEXT NOT NULL CHECK (record_key <> ''),
    text          TEXT NOT NULL,
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian'::regconfig, coalesce(text, ''))) STORED,
    embedding     VECTOR,
    model_id      TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT '',
    dimension     INTEGER CHECK (dimension IS NULL OR dimension > 0),
    text_version  TEXT NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (kind, tenant_id, company_id, record_key),
    CHECK ((kind IN ('article', 'event', 'entity') AND tenant_id='' AND company_id='')
        OR (kind NOT IN ('article', 'event', 'entity') AND tenant_id<>'' AND company_id<>'')),
    CHECK ((embedding IS NULL AND dimension IS NULL) OR (embedding IS NOT NULL AND dimension IS NOT NULL)),
    CHECK (embedding IS NULL OR vector_dims(embedding)=dimension)
);

CREATE INDEX search_documents_fts_idx ON analytics.search_documents USING GIN (search_vector);
CREATE INDEX search_documents_scope_idx ON analytics.search_documents
    (tenant_id, company_id, model_id, model_version, dimension);
