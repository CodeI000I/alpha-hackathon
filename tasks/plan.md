# Unified application — integration into main (2026-10-24)

The user now authorizes merging all remote work into main and connecting the previously
isolated services. This supersedes the earlier isolation boundary below. The previous
prototype checklist is complete; this phase preserves its tests and guarantees.

## Integration decisions

- Merge origin/main (including backend/frontend branches) into ai-orchestrator first;
  review conflicts, then fast-forward main to the tested result. No history rewriting.
- Keep Signal UI and the durable, fenced news delivery queue. The new Python analytics
  service owns model caching and exposes a compatible /rank adapter plus scoped APIs.
- Browser identity comes from an opaque server session, not a localStorage user ID.
  Go checks company ownership and roles, then injects scope behind a service token.
- Reuse existing model clients, analytics router, parser request boundary, PostgreSQL
  storage, Go S3 client and source adapters; do not duplicate extraction algorithms.
- Synchronize company profiles and uploaded files through a recoverable worker. Keep
  source-supported document facts when the ordinary company profile changes.
- Parser output preserves completeness and publication precision. Ineligible material
  is recorded as held, never promoted by inventing a timestamp or a complete body.
- Package Go/React and Python together in Compose/Helm; Python is an internal service.
  PostgreSQL major version stays compatible with existing storage.
- Verify real local HTTP/DB integration with synthetic model responses; do not send
  corporate data or consume paid APIs during automated tests.

## Delivery slices

1. Resolve backend/frontend conflicts and retain both branches' meaningful tests.
2. Register analytics API and /rank adapter; prove retries, revisions, scopes and cache.
3. Connect persistent company/document/job sync and parser-result bridge.
4. Connect authenticated Signal overview, issue evidence/history/state/chat and jobs.
5. Provide full runtime packaging and CI, run isolated end-to-end verification.
6. Review, record actual limitations, commit and push the tested integration to main.

Backend agent owns backend/; frontend agent owns frontend/; packaging agent owns
Compose/Helm/CI/env. Root owns Python integration, cross-component tests, docs and Git.
All coding agents must use Ponytail and Agent Skills.

## Previous completed phase

### Analytics prototype — specification v1

Baseline: `ai-orchestrator`, `b0cb4a4`, fast-forwarded from `a7f4f19` on 2026-10-23.
Implementation lives in this isolated checkout. The user subsequently authorized
committing and pushing it to ai-orchestrator. Live model calls, backend/frontend
changes, and router registration remain outside this task.

## Decisions

- Preserve the old `/rank` contract; add `orchestrator.analytics` service operations.
- Reuse `LLMClient`, canonical hashing, Russian tokenizer, parser HTML extraction and evidence validation.
- PostgreSQL/pgvector is the new source of truth. A memory adapter is for deterministic unit tests only.
- Append-only typed payloads in a compact versioned repository, tenant/company predicates in every private query.
- Require explicit trusted tenant/company scope; integration must map authenticated backend ownership later.
- Event identity uses actors/action/object/time/project, never embedding similarity alone.
- Group issues by exposure, business factor and horizon. Never add probabilities or financial effects.
- Conservative unknown/conditional results, explicit source checks, source text treated as data.
- Semantic embeddings use an optional configured local model; lexical baseline is labelled honestly.
- Graphify remains an opt-in validated import adapter; baseline extraction remains fully usable.
- All verification uses synthetic fixtures, fake gateway and a separate temporary PostgreSQL cluster.

## Work allocation

Root: contracts, orchestration, API boundary, acceptance/demo, integration and review.
Knowledge agent: document parsing/extraction, local embeddings, graph retrieval.
Persistence agent: versioned PG repository, FTS/pgvector, migrations, tests.
Baseline agent: regressions, then synthesis and scenario tests.
Every coding agent reads Ponytail and Agent Skills and applies their verification workflows.

## Existing behavior differences

The original implementation is article/company based, SQLite-backed, lexical-only,
and uses numeric relevance thresholds. The new service adds normalized global events,
explicit tenant boundaries, typed effects, issues and snapshots without changing the
existing wire contract. New decisions route by evidence and invariants, without
claiming empirically calibrated thresholds. New APIs remain unregistered in existing apps.

## Verification

Small increments with unittest; existing orchestrator and parser suites; new contract,
knowledge, storage, tenant, temporal, idempotency and concurrency tests; T01–T20
acceptance matrix; temporary PostgreSQL migrations/search; complete offline demo;
final diff review. Empirical quality and a real gateway test require later real data
and deliberate budget use and will be reported separately from code correctness.
