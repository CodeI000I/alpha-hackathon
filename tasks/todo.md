# Analytics implementation checklist

## Frontend interactions follow-up (2026-10-24)

- [x] Fetch branches and retain current main deployment tags.
- [x] Merge two frontend commits without regressing auth or live analytics.
- [x] Review and pass frontend unit/type/build/browser checks.
- [x] Update integration report and publish the ordinary merge to main.

Verification: 154 unit tests, TypeScript, production build and 55 Playwright
scenarios (27 demo + 28 API) passed. A targeted mutation reproduced a regression;
the original implementation was restored before final checks. Backend code and
dependency locks are unchanged; remote CI/deploy is not confirmed locally.

## Frontend follow-up integration (2026-10-24)

- [x] Fetch remote branches; retain successful CI tags from `origin/main`.
- [x] Merge three frontend commits, preserving auth and live analytics behavior.
- [x] Review API shapes, role/score semantics, feed states and focus behavior.
- [x] Pass frontend unit/type/build/browser checks and isolated unified HTTP/DB smoke.
- [x] Review, update the report, commit and push the complete integration to main.

Verification for this follow-up: 148 frontend unit tests, TypeScript, production
build, 46 Playwright scenarios (23 demo + 23 API), unified HTTP/PostgreSQL smoke.
Backend/Python code and dependency locks are unchanged; full historical audit
counts below are not a new rerun. Remote CI/deploy for this merge is separate.

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
