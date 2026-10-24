"""Offline evaluation harness checks against the actual HybridRetriever."""

from datetime import datetime, timezone
import unittest

from orchestrator.analytics.evaluation import compare_pipelines
from orchestrator.analytics.knowledge import HybridRetriever
from orchestrator.analytics.models import (
    CompanyFact, CompanyProfile, Event, KnowledgeEdge, Scope, SourceChunk, SourceDocument,
)
from orchestrator.analytics.store import MemoryStore


AS_OF = datetime(2026, 10, 23, tzinfo=timezone.utc)


class FixtureEmbeddings:
    model_id = 'local-fixture'
    version = 'v1'

    def embed(self, texts):
        return [[1.0, float(len(text) % 7 + 1)] for text in texts]


class PipelineEvaluationTests(unittest.TestCase):
    def test_compare_runs_real_hybrid_retrievers_with_identical_controls(self):
        scope = Scope(tenant_id='eval-tenant', company_id='eval-company')
        store = MemoryStore()
        chunk = SourceChunk(
            chunk_id='contract:r1:chunk-1', document_id='contract', document_revision=1,
            text='Компания закупает упаковку у supplier-x по годовому договору.',
            locator='page:1', start=0, end=60, text_hash='sha256-fixture',
        )
        document = SourceDocument(
            document_id='contract', revision=1, filename='contract.txt', media_type='text/plain',
            text=chunk.text, chunks=[chunk], received_at=AS_OF, status='ready',
        )
        fact = CompanyFact(
            fact_id='supplier-contract', text='Компания закупает упаковку у supplier-x.',
            subject_id=scope.company_id, predicate='buys_from', object_id='supplier-x',
            business_factors=['procurement_cost'], exposure='annual packaging procurement',
            status='known', verification_status='source_supported', source_refs=[chunk.chunk_id],
            source_quote='закупает упаковку у supplier-x',
        )
        company = CompanyProfile(name='Example Co', facts=[fact])
        store.put('company', scope.company_id, company.model_dump(mode='json'), **scope.db())
        store.put('document', document.document_id, {'document': document.model_dump(mode='json')},
                  **scope.db())
        store.put('chunk', chunk.chunk_id, chunk.model_dump(mode='json'), **scope.db())
        store.put('edge', 'edge-1', KnowledgeEdge(
            edge_id='edge-1', subject_id=scope.company_id, predicate='buys_from',
            object_id='supplier-x', evidence_refs=[chunk.chunk_id],
            verification_status='source_supported',
        ).model_dump(mode='json'), **scope.db())
        event = Event(
            event_id='event-1', event_type='supplier_change', action='changes price',
            subject='supplier-x', summary='Supplier changes price', entities=['supplier-x'],
            affected_factors=['procurement_cost'], evidence_quote='supplier-x changes price',
        )
        retrievers = {
            'lexical': HybridRetriever(store, embeddings=FixtureEmbeddings(), use_graph=False),
            'graph': HybridRetriever(store, embeddings=FixtureEmbeddings(), use_graph=True),
        }
        fixture = dict(fixture_id='same-event', expected_fact_ids=['supplier-contract'],
                       expected_label='supported', as_of=AS_OF, context_budget=8192,
                       scope=scope, event=event, news=[])
        observed_controls = []

        def run(retriever):
            def invoke(row, *, as_of, context_budget):
                self.assertEqual(context_budget, 8192)
                pack = retriever.retrieve(row['scope'], row['event'], row['news'], as_of)
                observed_controls.append((as_of, context_budget))
                return dict(fact_ids=[fact.fact_id for fact in pack.company_facts],
                            label='supported' if pack.company_facts else 'unknown',
                            tokens=123, calls=1, channels=pack.retrieval['channels'])
            return invoke

        results = compare_pipelines([fixture],
                                    {name: run(retriever) for name, retriever in retrievers.items()})

        self.assertEqual(results['lexical']['evaluation_scope'], 'synthetic_fixtures_only')
        self.assertEqual(results['lexical']['recall'], 1.0)
        self.assertEqual(results['graph']['label_accuracy'], 1.0)
        self.assertEqual(results['graph']['calls'], 1)
        self.assertEqual(results['graph']['tokens'], 123)
        self.assertGreaterEqual(results['graph']['latency_seconds'], 0)
        self.assertEqual(observed_controls, [(AS_OF, 8192), (AS_OF, 8192)])
        # Graph channel presence proves the graph-enabled real retriever path ran.
        graph_pack = retrievers['graph'].retrieve(scope, event, [], AS_OF)
        self.assertIn('graph', graph_pack.retrieval['channels'])
        self.assertNotIn('graph', retrievers['lexical'].retrieve(scope, event, [], AS_OF).retrieval['channels'])

    def test_requires_shared_budget_and_as_of_on_every_fixture(self):
        with self.assertRaises(ValueError):
            compare_pipelines([{'expected_fact_ids': []}], {'noop': lambda *_args, **_kwargs: {}})


if __name__ == '__main__':
    unittest.main()
