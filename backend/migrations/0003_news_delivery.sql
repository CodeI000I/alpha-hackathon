ALTER TABLE news_items
    ADD COLUMN revision BIGINT NOT NULL DEFAULT 1;

ALTER TABLE feed_items
    ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE news_deliveries (
    id BIGSERIAL PRIMARY KEY,
    news_id BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'done', 'failed', 'superseded')),
    attempts INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    claim_token BIGINT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (news_id, revision, user_id)
);

CREATE INDEX news_deliveries_claim_idx
    ON news_deliveries (next_attempt_at, id)
    WHERE state IN ('pending', 'running');
