-- Idempotency records for the atomic company + first-user onboarding request.
CREATE TABLE onboarding_requests (
    idempotency_key TEXT PRIMARY KEY,
    request_hash    TEXT NOT NULL CHECK (length(request_hash) = 64),
    company_id      BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
