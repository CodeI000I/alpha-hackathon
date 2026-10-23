# Analytics prototype — specification v1

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
