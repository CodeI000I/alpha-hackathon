import json
from io import BytesIO
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from orchestrator.analytics.knowledge import (
    DocumentParseError,
    HybridRetriever,
    KnowledgeExtractionError,
    KnowledgeService,
    RevisionConflict as KnowledgeRevisionConflict,
    import_graphify_json,
    parse_document,
)
from orchestrator.analytics.models import Event, NewsArticle, Scope
from orchestrator.analytics.store import MemoryStore
from orchestrator.llm import AIError


AS_OF = datetime(2026, 10, 23, tzinfo=timezone.utc)


class FixtureEmbeddings:
    model_id = 'fixture'
    version = 'v1'

    def embed(self, texts):
        return [[1.0, float(len(text) % 7 + 1)] for text in texts]


class FixtureLLM:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error
        self.calls = 0

    def structured(self, stage, instruction, context, schema, validate=None):
        self.calls += 1
        if self.error:
            raise self.error
        result = schema.model_validate(self.payload)
        if validate:
            validate(result)
        return result


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.scope = Scope(tenant_id='tenant-a', company_id='company-a')
        self.store = MemoryStore()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_parse_text_preserves_complete_text_and_revision_locators(self):
        text = 'Компания закупает упаковку у Поставщик-А.\n\nДоговор действует до 2027 года.'
        document = parse_document('doc-1', 2, 'profile.md', text.encode(), 'text/markdown')

        self.assertEqual(document.text, text)
        self.assertTrue(document.chunks)
        self.assertTrue(all(chunk.text == document.text[chunk.start:chunk.end] for chunk in document.chunks))
        self.assertTrue(all(':r2:' in chunk.chunk_id for chunk in document.chunks))

    def test_parse_html_reuses_semantic_cleaner_and_pdf_docx_fail_explicitly_if_missing(self):
        document = parse_document(
            'html-1', 1, 'profile.html',
            '<main><h1>Поставки</h1><p>Поставщик-А.</p></main>'.encode(), 'text/html'
        )
        self.assertIn('Поставщик-А', document.text)
        self.assertIn('html', document.chunks[0].locator)
        with self.assertRaises(DocumentParseError):
            parse_document('bad', 1, 'broken.txt', b'\xff', 'text/plain')

    def test_parse_pdf_and_docx_include_page_body_tables_and_headers(self):
        import pymupdf as fitz
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), 'Supplier-A contract')
        pdf_bytes = pdf.tobytes()
        pdf.close()
        parsed_pdf = parse_document('pdf-1', 1, 'profile.pdf', pdf_bytes, 'application/pdf')
        self.assertIn('Supplier-A', parsed_pdf.text)
        self.assertTrue(parsed_pdf.chunks[0].locator.startswith('pdf:page:1'))

        from docx import Document
        docx = Document()
        docx.sections[0].header.paragraphs[0].text = 'Confidential supplier overview'
        docx.add_paragraph('Company buys packaging from Supplier-A.')
        table = docx.add_table(rows=1, cols=2)
        table.cell(0, 0).text = 'Price terms'
        table.cell(0, 1).text = 'current price at shipment'
        buffer = BytesIO()
        docx.save(buffer)
        parsed_docx = parse_document(
            'docx-1', 1, 'profile.docx', buffer.getvalue(),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertIn('Confidential supplier overview', parsed_docx.text)
        self.assertIn('current price at shipment', parsed_docx.text)

    def test_scanned_pdf_fails_explicitly_when_russian_ocr_data_is_missing(self):
        import pymupdf

        source = pymupdf.open()
        page = source.new_page(width=700, height=180)
        page.insert_text((45, 95), 'Поставщик-А меняет условия договора', fontsize=28,
                         fontname='helv')
        raster = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes('png')
        source.close()
        scanned = pymupdf.open()
        page = scanned.new_page(width=700, height=180)
        page.insert_image(page.rect, stream=raster)
        raw = scanned.tobytes()
        scanned.close()
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'eng.traineddata').write_bytes(b'installed')
            with patch.dict(os.environ, {'TESSDATA_PREFIX': directory}):
                with self.assertRaisesRegex(DocumentParseError, 'OCR_LANG_DATA_MISSING'):
                    parse_document('scan-rus', 1, 'scan.pdf', raw, 'application/pdf')

    def test_scanned_russian_pdf_uses_both_local_ocr_languages(self):
        import pymupdf

        tessdata = Path(__file__).resolve().parents[2] / 'data' / 'tessdata'
        if not all((tessdata / f'{language}.traineddata').is_file() for language in ('eng', 'rus')):
            self.skipTest('Run prepare_assets.py --ocr to install the pinned local OCR models')
        fonts = (
            Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
            Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        )
        font = next((path for path in fonts if path.is_file()), None)
        if font is None:
            self.skipTest('A local Cyrillic font is required for the synthetic scanned page')

        source = pymupdf.open()
        page = source.new_page(width=800, height=160)
        page.insert_text((35, 90), 'Поставщик-А меняет условия договора', fontsize=30,
                         fontfile=str(font), fontname='cyrillic')
        raster = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes('png')
        source.close()
        scanned = pymupdf.open()
        page = scanned.new_page(width=800, height=160)
        page.insert_image(page.rect, stream=raster)
        raw = scanned.tobytes()
        scanned.close()

        with patch.dict(os.environ, {'TESSDATA_PREFIX': str(tessdata)}):
            parsed = parse_document('scan-rus-ok', 1, 'scan.pdf', raw, 'application/pdf')

        self.assertIn('Поставщик', parsed.text)
        self.assertIn('договор', parsed.text)

    def _document_and_fact(self, *, revision=1, fact_id='fact-a', quote='Компания закупает упаковку у Поставщик-А.'):
        document = parse_document(
            'doc-1', revision, 'profile.txt',
            'Компания закупает упаковку у Поставщик-А.\nПоставщик-А поставляет упаковку.'.encode(), 'text/plain'
        ).model_copy(update={'received_at': AS_OF})
        chunk = next(item for item in document.chunks if quote in item.text)
        return document, chunk, {
            'facts': [{
                'fact_id': fact_id,
                'text': 'Компания закупает упаковку у Поставщик-А.',
                'subject_id': 'company-a',
                'predicate': 'buys_from',
                'object_id': 'supplier-a',
                'modality': 'current_fact',
                'business_factors': ['procurement_cost', 'supply_availability'],
                'source_refs': [chunk.chunk_id],
                'source_quote': quote,
                'verification_status': 'source_supported',
            }],
            'edges': [{
                'edge_id': f'edge-{revision}', 'subject_id': 'company-a', 'predicate': 'buys_from',
                'object_id': 'supplier-a', 'scope': 'private', 'evidence_refs': [chunk.chunk_id],
                'derivation': 'extracted', 'verification_status': 'source_supported',
                'extractor_version': 'fixture-v1',
                'source_quote': quote,
            }],
        }

    def test_ingest_persists_original_chunks_and_source_backed_facts(self):
        document, chunk, extraction = self._document_and_fact()
        service = KnowledgeService(
            self.store, FixtureLLM(extraction), embeddings=FixtureEmbeddings(), object_dir=self.temp.name
        )

        saved = service.ingest(self.scope, document, original=document.text.encode())

        self.assertEqual(saved.status, 'ready')
        self.assertEqual(self.store.get('document', 'doc-1', **self.scope.db()).payload['original_storage'], 'object')
        self.assertTrue(Path(saved.original_path).is_file())
        self.assertEqual(self.store.get('chunk', chunk.chunk_id, **self.scope.db()).payload['text'], chunk.text)
        company = self.store.get('company', self.scope.company_id, **self.scope.db())
        self.assertEqual(company.payload['facts'][0]['source_refs'], [chunk.chunk_id])
        self.assertEqual(self.store.get('edge', 'edge-1', **self.scope.db()).payload['predicate'], 'buys_from')

    def test_ready_write_failure_rolls_back_company_facts_and_edges(self):
        class FailReadyStore(MemoryStore):
            def put(self, kind, key, payload, **kwargs):
                if kind == 'document' and payload.get('document', {}).get('status') == 'ready':
                    raise RuntimeError('simulated ready write failure')
                return super().put(kind, key, payload, **kwargs)

        self.store = FailReadyStore()
        document, _, extraction = self._document_and_fact()

        with self.assertRaises(KnowledgeExtractionError):
            KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name).ingest(
                self.scope, document
            )

        source = self.store.get('document', document.document_id, **self.scope.db())
        self.assertEqual(source.payload['document']['status'], 'failed')
        self.assertIsNone(self.store.get('company', self.scope.company_id, **self.scope.db()))
        self.assertEqual(self.store.list('fact', **self.scope.db()), [])
        self.assertEqual(self.store.list('edge', **self.scope.db()), [])

    def test_ingest_rejects_quote_or_chunk_from_another_revision_and_keeps_failed_document(self):
        document, _, extraction = self._document_and_fact()
        extraction['facts'][0]['source_quote'] = 'Строка, которой нет в чанке.'
        service = KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name)

        with self.assertRaises(KnowledgeExtractionError):
            service.ingest(self.scope, document)

        self.assertEqual(self.store.get('document', 'doc-1', **self.scope.db()).payload['document']['status'], 'failed')
        self.assertIsNotNone(self.store.get('document', 'doc-1', **self.scope.db()))
        self.assertEqual(self.store.get('company', self.scope.company_id, **self.scope.db()), None)

    def test_document_revision_is_immutable_and_new_revision_replaces_only_its_facts(self):
        document, _, extraction = self._document_and_fact()
        service = KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name)
        service.ingest(self.scope, document)
        with self.assertRaises(KnowledgeRevisionConflict):
            service.ingest(self.scope, document.model_copy(update={'text': 'changed'}))

        next_document, _, next_extraction = self._document_and_fact(revision=2, fact_id='fact-b')
        KnowledgeService(self.store, FixtureLLM(next_extraction), object_dir=self.temp.name).ingest(
            self.scope, next_document
        )
        company = self.store.get('company', self.scope.company_id, **self.scope.db())
        self.assertEqual([fact['fact_id'] for fact in company.payload['facts']], ['fact-b'])

    def test_failed_new_revision_keeps_last_ready_revision_retrievable(self):
        document, chunk, extraction = self._document_and_fact()
        KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name).ingest(
            self.scope, document
        )
        next_document, _, _ = self._document_and_fact(revision=2, fact_id='fact-b')
        failed = KnowledgeService(self.store, FixtureLLM(error=ValueError('bad extraction')),
                                  object_dir=self.temp.name)
        with self.assertRaises(KnowledgeExtractionError):
            failed.ingest(self.scope, next_document)

        event = Event(event_id='event-failed-revision', event_type='supplier_price_change',
                      action='цены выросли', subject='Поставщик-А',
                      summary='Поставщик-А меняет цены на упаковку', entities=['supplier-a'],
                      affected_factors=['procurement_cost'], evidence_quote='Поставщик-А меняет цены')
        pack = HybridRetriever(self.store).retrieve(self.scope, event, [], AS_OF)
        self.assertEqual([fact.fact_id for fact in pack.company_facts], ['fact-a'])
        self.assertIn(chunk.chunk_id, {item.chunk_id for item in pack.chunks})

    def test_ai_budget_error_is_preserved_and_embedding_failure_marks_source_failed(self):
        document, _, extraction = self._document_and_fact()
        budget_error = AIError('budget_exceeded', 'paused', retry_at=1234)
        with self.assertRaises(AIError) as caught:
            KnowledgeService(self.store, FixtureLLM(error=budget_error), object_dir=self.temp.name).ingest(
                self.scope, document
            )
        self.assertIs(caught.exception, budget_error)
        self.assertEqual(caught.exception.retry_at, 1234)

        class BrokenEmbeddings(FixtureEmbeddings):
            def embed(self, texts):
                raise RuntimeError('local model unavailable')

        # New document id avoids the failed budget-attempt record.
        second = parse_document('doc-2', 1, 'profile.txt', b'Company text', 'text/plain')
        with self.assertRaises(KnowledgeExtractionError) as embedding_error:
            KnowledgeService(self.store, FixtureLLM(extraction), embeddings=BrokenEmbeddings(),
                             object_dir=self.temp.name).ingest(self.scope, second)
        self.assertEqual(embedding_error.exception.code, 'EMBEDDING_FAILED')
        self.assertEqual(self.store.get('document', 'doc-2', **self.scope.db()).payload['document']['status'],
                         'failed')

    def test_retrieval_is_tenant_scoped_temporal_and_returns_graph_provenance(self):
        document, source_chunk, extraction = self._document_and_fact()
        KnowledgeService(self.store, FixtureLLM(extraction), embeddings=FixtureEmbeddings(),
                         object_dir=self.temp.name).ingest(self.scope, document)
        other = Scope(tenant_id='tenant-b', company_id='company-a')
        self.store.put('company', 'company-a', {'name': 'Company B', 'facts': []}, **other.db())
        event = Event(event_id='event-1', event_type='supplier_price_change', action='цены выросли',
                      subject='Поставщик-А', summary='Поставщик-А меняет цены на упаковку',
                      entities=['supplier-a'], affected_factors=['procurement_cost'],
                      evidence_quote='Поставщик-А меняет цены')
        news = [NewsArticle(news_id='news-1', title='Цены на упаковку', content='Поставщик-А объявил рост цен',
                            published_at=AS_OF)]

        pack = HybridRetriever(self.store, embeddings=FixtureEmbeddings()).retrieve(
            self.scope, event, news, AS_OF
        )

        self.assertEqual(pack.company_facts[0].fact_id, 'fact-a')
        self.assertIn('graph', pack.retrieval['channels'])
        self.assertTrue(pack.candidate_paths)
        self.assertIn(source_chunk.chunk_id, pack.candidate_paths[0].evidence_refs)

    def test_retrieval_version_tracks_settings_and_future_documents_are_excluded(self):
        document, _, extraction = self._document_and_fact()
        future = document.model_copy(update={
            'received_at': AS_OF.replace(year=AS_OF.year + 1),
        })
        KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name).ingest(
            self.scope, future
        )
        event = Event(event_id='event-future', event_type='supplier_price_change',
                      action='цены выросли', subject='Поставщик-А',
                      summary='Поставщик-А меняет цены на упаковку', entities=['supplier-a'],
                      affected_factors=['procurement_cost'], evidence_quote='Поставщик-А меняет цены')
        retriever = HybridRetriever(self.store)
        pack = retriever.retrieve(self.scope, event, [], AS_OF)
        self.assertFalse(pack.company_facts)
        self.assertFalse(pack.chunks)
        self.assertNotEqual(retriever.version, HybridRetriever(self.store, top_k=5).version)

    def test_retrieval_surfaces_embedding_fallback_warning(self):
        class BrokenEmbeddings(FixtureEmbeddings):
            def embed(self, texts):
                raise RuntimeError('model unavailable')

        document, _, extraction = self._document_and_fact()
        KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name).ingest(
            self.scope, document
        )
        event = Event(event_id='event-embed-warning', event_type='supplier_price_change',
                      action='цены выросли', subject='Поставщик-А',
                      summary='Поставщик-А меняет цены на упаковку', entities=['supplier-a'],
                      affected_factors=['procurement_cost'], evidence_quote='Поставщик-А меняет цены')

        pack = HybridRetriever(self.store, embeddings=BrokenEmbeddings()).retrieve(
            self.scope, event, [], AS_OF
        )

        self.assertIn('lexical channels only', pack.retrieval['embedding_warning'])
        self.assertFalse(pack.retrieval['query_vector_available'])

    def test_graphify_json_import_requires_known_chunk_quote_and_allowed_relation(self):
        document, chunk, _ = self._document_and_fact()
        graph_json = json.dumps({'edges': [{
            'id': 'graph-edge-1', 'source': 'company-a', 'target': 'supplier-a', 'type': 'buys_from',
            'source_refs': [chunk.chunk_id], 'source_quote': 'Компания закупает упаковку у Поставщик-А.'
        }]})
        result = import_graphify_json(graph_json, self.scope, document)
        self.assertEqual(result[0].predicate, 'buys_from')
        invalid = graph_json.replace('buys_from', 'invented_relation')
        with self.assertRaises(ValueError):
            import_graphify_json(invalid, self.scope, document)


if __name__ == '__main__':
    unittest.main()
