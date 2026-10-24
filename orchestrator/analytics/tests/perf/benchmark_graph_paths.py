"""Manual in-memory benchmark for graph path traversal (no timing assertions).

Run from the repository root with:
    .venv/bin/python -m orchestrator.analytics.tests.perf.benchmark_graph_paths
"""

from datetime import datetime, timezone
from time import perf_counter

from orchestrator.analytics.knowledge import HybridRetriever, parse_document
from orchestrator.analytics.models import Event, KnowledgeEdge, Scope
from orchestrator.analytics.store import MemoryStore


def run(size: int) -> tuple[int, float]:
    scope = Scope(tenant_id='benchmark', company_id='company-a')
    store = MemoryStore()
    chunk = parse_document('benchmark-source', 1, 'benchmark.txt', b'benchmark evidence',
                           'text/plain').chunks[0]
    for index in range(size):
        middle = f'supplier_{index}'
        for edge in (
            KnowledgeEdge(edge_id=f'root-{index}', subject_id='company-a',
                          predicate='supplies_to', object_id=middle,
                          evidence_refs=[chunk.chunk_id], verification_status='source_supported'),
            KnowledgeEdge(edge_id=f'target-{index}', subject_id=middle,
                          predicate='produces', object_id='target_factory',
                          evidence_refs=[chunk.chunk_id], verification_status='source_supported'),
        ):
            store.put('edge', edge.edge_id, edge.model_dump(mode='json'), **scope.db())
    event = Event(event_id='benchmark', event_type='test', action='factory change',
                  subject='target_factory', summary='factory change', entities=['target_factory'],
                  evidence_quote='factory change')
    start = perf_counter()
    paths = HybridRetriever(store, max_depth=2)._paths(scope, event, datetime.now(timezone.utc), [chunk])
    return len(paths), perf_counter() - start


if __name__ == '__main__':
    for fanout in (500, 1000, 2500):
        path_count, elapsed = run(fanout)
        print(f'fanout={fanout} edges={2 * fanout} paths={path_count} seconds={elapsed:.4f}')
