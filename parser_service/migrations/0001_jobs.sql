BEGIN;

CREATE SCHEMA IF NOT EXISTS parser;

CREATE TABLE IF NOT EXISTS parser.jobs (
    job_id      TEXT PRIMARY KEY,
    request     JSONB NOT NULL CHECK (jsonb_typeof(request) = 'object'),
    status      TEXT NOT NULL DEFAULT 'queued' CHECK (status = 'queued'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (request->>'job_id' IS NOT NULL AND request->>'job_id' = job_id)
);

COMMIT;
