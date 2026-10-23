# Analytics implementation checklist

- [x] Inspect repository, update branch, map reusable code and differences.
- [x] Reproduce and fix legacy policy freshness and exhausted budget jobs (64 tests).
- [x] Strict domain contracts and invalid-input tests.
- [x] Versioned tenant-scoped PostgreSQL repository and real pgvector/FTS tests.
- [x] Documents → structural chunks → supported facts/edges, revision invalidation.
- [x] Retrieval with temporal/tenant filters, exact/FTS/vector/graph channels.
- [x] Idempotent news revisions and event normalization, global archive and backfill.
- [x] Evidence-grounded impacts, routing, versioned issues and precomputed snapshots.
- [x] Pinned conversations, user state/history, scheduling/recovery and run metrics.
- [x] Unregistered router plus disposable harness and acceptance scenarios.
- [x] Full verification, demo, implementation/limitations report and review.

Verification: 82 orchestrator tests + 73 analytics tests (including actual PostgreSQL,
pgvector and checkpoint recovery) + 120 parser tests passed. Offline and PostgreSQL
demos passed, including repeated PostgreSQL runs. Local semantic embeddings and
Russian OCR smoke checks passed. See docs/analytics-prototype-report.md for limits.
