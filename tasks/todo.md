# Analytics implementation checklist

## Main integration (2026-10-24)

- [x] Fetch all remotes and map changes already merged into main.
- [x] Resolve merges without losing audit protections or Signal UI.
- [x] Connect private analytics API and compatible /rank endpoint; contract tests.
- [x] Connect recoverable profile/file/job sync and parser output ingestion; tests.
- [x] Connect server sessions, scoped Go proxy and real Signal analytics views.
- [x] Prepare full Compose/Helm runtime and CI image builds (local Docker unavailable).
- [x] Run full Python/Go/frontend tests and isolated HTTP/DB/browser smoke.
- [x] Review final changes and update architecture/runbook/report for main publication.

Verification: 372 Python tests without skips, full Go race/vet with three isolated
PostgreSQL databases and no skips, 121 frontend unit and 38 browser tests, typecheck,
build, npm audit (zero findings), Helm/actionlint and unified HTTP smoke. Local
Docker build, live model/source calls and cluster rollout are not claimed.
See docs/integration-main-2026-10-24.md.

## Completed prototype

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
