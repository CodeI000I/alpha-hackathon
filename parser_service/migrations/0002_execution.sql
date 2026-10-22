ALTER TABLE parser.jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE parser.jobs ADD CONSTRAINT jobs_status_check
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed'));

ALTER TABLE parser.jobs
    ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    ADD COLUMN lease_token UUID,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN started_at TIMESTAMPTZ,
    ADD COLUMN finished_at TIMESTAMPTZ,
    ADD COLUMN result JSONB,
    ADD COLUMN error JSONB;

ALTER TABLE parser.jobs ADD CONSTRAINT jobs_execution_state_check CHECK (
    (status = 'queued' AND attempt = 0 AND started_at IS NULL AND finished_at IS NULL
        AND lease_token IS NULL AND lease_expires_at IS NULL
        AND result IS NULL AND error IS NULL)
    OR
    (status = 'running' AND attempt > 0 AND started_at IS NOT NULL AND finished_at IS NULL
        AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL
        AND result IS NULL AND error IS NULL)
    OR
    (status = 'succeeded' AND attempt > 0 AND started_at IS NOT NULL AND finished_at IS NOT NULL
        AND lease_token IS NULL AND lease_expires_at IS NULL
        AND result IS NOT NULL AND error IS NULL)
    OR
    (status = 'failed' AND attempt > 0 AND started_at IS NOT NULL AND finished_at IS NOT NULL
        AND lease_token IS NULL AND lease_expires_at IS NULL
        AND result IS NULL AND error IS NOT NULL)
);

ALTER TABLE parser.jobs ADD CONSTRAINT jobs_result_check CHECK (
    result IS NULL OR (
        jsonb_typeof(result) = 'object'
        AND result ? 'job_id' AND result->>'job_id' = job_id
    )
);

ALTER TABLE parser.jobs ADD CONSTRAINT jobs_error_check CHECK (
    error IS NULL OR (
        jsonb_typeof(error) = 'object'
        AND error ?& ARRAY['code', 'message', 'retryable']
        AND jsonb_typeof(error->'code') = 'string'
        AND jsonb_typeof(error->'message') = 'string'
        AND jsonb_typeof(error->'retryable') = 'boolean'
    )
);

CREATE INDEX jobs_claim_idx ON parser.jobs (created_at, job_id)
    WHERE status IN ('queued', 'running');
