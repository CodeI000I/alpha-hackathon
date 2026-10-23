import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.analytics.knowledge import (
    DocumentParseError,
    HybridRetriever,
    KnowledgeExtractionError,
    KnowledgeService,
    MAX_CHUNK_CHARS,
    MAX_CHUNKS,
    MAX_DOCUMENT_CHARS,
    RevisionConflict as KnowledgeRevisionConflict,
    _canonical_node,
    import_graphify_json,
    parse_document,
)
from orchestrator.analytics.models import Event, NewsArticle, Scope, SourceChunk, SourceDocument
from orchestrator.analytics.models import KnowledgeEdge
from orchestrator.analytics.store import MemoryStore
from orchestrator.llm import AIError
from orchestrator.models import digest


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

    def test_pdf_text_limit_stops_reading_pages_as_soon_as_cumulative_limit_is_exceeded(self):
        import pymupdf

        class Page:
            rect = type('Rect', (), {'width': 100, 'height': 100})()

            def __init__(self):
                self.reads = 0

            def get_text(self, *_args, **_kwargs):
                self.reads += 1
                return 'x' * (MAX_DOCUMENT_CHARS // 2 + 1)

            def get_images(self, **_kwargs):
                return []

        class Pdf:
            needs_pass = False
            page_count = 3

            def __init__(self):
                self.pages = [Page() for _ in range(3)]

            def __iter__(self):
                return iter(self.pages)

            def close(self):
                pass

        fake_pdf = Pdf()
        with patch.object(pymupdf, 'open', return_value=fake_pdf):
            with self.assertRaisesRegex(DocumentParseError, 'TEXT_LIMIT'):
                parse_document('large-pdf', 1, 'large.pdf', b'pdf', 'application/pdf')

        self.assertEqual([page.reads for page in fake_pdf.pages], [1, 1, 0])

    def test_ingest_rejects_oversized_text_and_chunks_before_persisting(self):
        service = KnowledgeService(self.store, FixtureLLM(), object_dir=self.temp.name)
        oversized_text = SourceDocument(
            document_id='too-large-text', filename='large.txt', media_type='text/plain',
            text='x' * (MAX_DOCUMENT_CHARS + 1),
        )
        with self.assertRaisesRegex(DocumentParseError, 'TEXT_LIMIT'):
            service.ingest(self.scope, oversized_text)
        self.assertIsNone(self.store.get('document', oversized_text.document_id, **self.scope.db()))

        oversized_chunk = SourceChunk(
            chunk_id='too-large-chunk', document_id='too-large-chunks', document_revision=1,
            text='x' * (MAX_CHUNK_CHARS + 1), locator='text:body', start=0,
            end=MAX_CHUNK_CHARS + 1, text_hash='hash',
        )
        oversized_chunks = SourceDocument(
            document_id='too-large-chunks', filename='chunks.txt', media_type='text/plain',
            text='small', chunks=[oversized_chunk],
        )
        with self.assertRaisesRegex(DocumentParseError, 'CHUNK_LIMIT'):
            service.ingest(self.scope, oversized_chunks)
        self.assertIsNone(self.store.get('document', oversized_chunks.document_id, **self.scope.db()))

        too_many_chunks = [SourceChunk(
            chunk_id=f'chunk-{index}', document_id='too-many-chunks', document_revision=1,
            text='x', locator=f'text:{index}', start=index, end=index + 1, text_hash='hash',
        ) for index in range(MAX_CHUNKS + 1)]
        excessive_document = SourceDocument(
            document_id='too-many-chunks', filename='chunks.txt', media_type='text/plain',
            text='small', chunks=too_many_chunks,
        )
        with self.assertRaisesRegex(DocumentParseError, 'CHUNK_LIMIT'):
            service.ingest(self.scope, excessive_document)
        self.assertIsNone(self.store.get('document', excessive_document.document_id, **self.scope.db()))

    def test_canonical_graph_nodes_normalize_unicode_composition(self):
        self.assertEqual(_canonical_node('Café'), _canonical_node('Cafe\u0301'))

    def test_parse_html_reuses_semantic_cleaner_and_pdf_docx_fail_explicitly_if_missing(self):
        document = parse_document(
            'html-1', 1, 'profile.html',
            '<main><h1>Поставки</h1><p>Поставщик-А.</p></main>'.encode(), 'text/html'
        )
        self.assertIn('Поставщик-А', document.text)
        self.assertIn('html', document.chunks[0].locator)
        with self.assertRaises(DocumentParseError):
            parse_document('bad', 1, 'broken.txt', b'\xff', 'text/plain')

    def test_ingest_rejects_chunk_text_not_bound_to_document_before_writes(self):
        source_text = 'Company buys from Supplier-A.'
        document = parse_document('provenance-doc', 1, 'source.txt', source_text.encode(), 'text/plain')
        chunk = document.chunks[0]
        substituted_text = 'Company buys from Supplier-B.'
        substituted_chunk = chunk.model_copy(update={
            'text': substituted_text,
            'text_hash': hashlib.sha256(substituted_text.encode()).hexdigest(),
        })
        forged = document.model_copy(update={'chunks': [substituted_chunk]})
        llm = FixtureLLM()

        with self.assertRaisesRegex(DocumentParseError, 'CHUNK_PROVENANCE'):
            KnowledgeService(self.store, llm, object_dir=self.temp.name).ingest(self.scope, forged)

        self.assertEqual(llm.calls, 0)
        self.assertIsNone(self.store.get('document', document.document_id, **self.scope.db()))
        self.assertIsNone(self.store.get('chunk', chunk.chunk_id, **self.scope.db()))

    def test_ingest_rejects_invalid_chunk_namespace_offsets_hash_and_duplicates(self):
        text = 'Company buys from Supplier-A.'
        document = parse_document('provenance-doc', 1, 'source.txt', text.encode(), 'text/plain')
        chunk = document.chunks[0]
        foreign = parse_document('other-document', 2, 'source.txt', text.encode(), 'text/plain').chunks[0]
        cases = {
            'foreign chunk id': [foreign.model_copy(update={
                'document_id': document.document_id, 'document_revision': document.revision,
            })],
            'wrong document id': [chunk.model_copy(update={'document_id': 'other-document'})],
            'wrong revision': [chunk.model_copy(update={'document_revision': document.revision + 1})],
            'invalid offset': [chunk.model_copy(update={'start': -1})],
            'invalid text hash': [chunk.model_copy(update={'text_hash': '0' * 64})],
            'duplicate chunk id': [chunk, chunk],
        }

        for name, chunks in cases.items():
            with self.subTest(name=name):
                store = MemoryStore()
                forged = document.model_copy(update={'chunks': chunks})
                with self.assertRaisesRegex(DocumentParseError, 'CHUNK_PROVENANCE'):
                    KnowledgeService(store, FixtureLLM(), object_dir=self.temp.name).ingest(
                        self.scope, forged
                    )
                self.assertEqual(store.list('document', **self.scope.db()), [])
                self.assertEqual(store.list('chunk', **self.scope.db()), [])

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

    def test_pdf_with_native_text_and_image_ocr_includes_image_text(self):
        import pymupdf

        image_source = pymupdf.open()
        image_page = image_source.new_page(width=120, height=60)
        image_page.draw_rect(pymupdf.Rect(0, 0, 120, 60), color=(0, 0, 0), fill=(1, 1, 1))
        image_bytes = image_page.get_pixmap().tobytes('png')
        image_source.close()

        source = pymupdf.open()
        page = source.new_page(width=500, height=150)
        page.insert_text((40, 40), 'Selectable header')
        page.insert_image(pymupdf.Rect(40, 60, 300, 130), stream=image_bytes)
        raw = source.tobytes()
        source.close()

        with patch('orchestrator.analytics.knowledge._ocr_page_text',
                   return_value='Selectable header\nScanned body') as ocr:
            parsed = parse_document('hybrid-pdf', 1, 'hybrid.pdf', raw, 'application/pdf')

        ocr.assert_called_once()
        self.assertFalse(ocr.call_args.kwargs['full'])
        self.assertIn('Selectable header', parsed.text)
        self.assertIn('Scanned body', parsed.text)

    def test_vector_only_pdf_page_uses_full_ocr_fallback(self):
        import pymupdf

        source = pymupdf.open()
        page = source.new_page(width=500, height=150)
        page.draw_rect(pymupdf.Rect(20, 20, 450, 120), color=(0, 0, 0), fill=(1, 1, 1))
        raw = source.tobytes()
        source.close()

        with patch('orchestrator.analytics.knowledge._ocr_page_text',
                   return_value='Outlined glyph text') as ocr:
            parsed = parse_document('vector-pdf', 1, 'vector.pdf', raw, 'application/pdf')

        ocr.assert_called_once()
        self.assertTrue(ocr.call_args.kwargs['full'])
        self.assertIn('Outlined glyph text', parsed.text)

    def test_pdf_ocr_rejects_excessive_raster_area_before_invoking_tesseract(self):
        import pymupdf

        source = pymupdf.open()
        page = source.new_page(width=14400, height=14400)
        page.insert_image(pymupdf.Rect(0, 0, 100, 100),
                          stream=pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 1, 1), 0).tobytes('png'))
        raw = source.tobytes()
        source.close()

        with self.assertRaisesRegex(DocumentParseError, 'OCR_PIXEL_LIMIT'):
            parse_document('huge-pdf', 1, 'huge.pdf', raw, 'application/pdf')

    def test_pdf_ocr_enforces_document_pixel_budget(self):
        import pymupdf

        image = pymupdf.open()
        image_page = image.new_page(width=10, height=10)
        image_page.draw_rect(pymupdf.Rect(0, 0, 10, 10), fill=(1, 1, 1))
        image_bytes = image_page.get_pixmap().tobytes('png')
        image.close()
        source = pymupdf.open()
        for _ in range(24):
            page = source.new_page(width=595, height=842)
            page.insert_image(pymupdf.Rect(10, 10, 20, 20), stream=image_bytes)
        raw = source.tobytes()
        source.close()

        with patch('orchestrator.analytics.knowledge._ocr_page_text', return_value='recognized') as ocr:
            with self.assertRaisesRegex(DocumentParseError, 'OCR_PIXEL_LIMIT'):
                parse_document('many-scans', 1, 'many.pdf', raw, 'application/pdf')

        self.assertLess(ocr.call_count, 24)

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

        hybrid = pymupdf.open()
        page = hybrid.new_page(width=800, height=200)
        page.insert_text((35, 35), 'Selectable header')
        page.insert_image(pymupdf.Rect(20, 55, 780, 190), stream=raster)
        hybrid_raw = hybrid.tobytes()
        hybrid.close()
        hybrid_parsed = parse_document('scan-rus-hybrid', 1, 'hybrid.pdf', hybrid_raw,
                                       'application/pdf')
        self.assertEqual(hybrid_parsed.text.count('Selectable header'), 1)
        self.assertIn('Поставщик', hybrid_parsed.text)
        self.assertIn('договор', hybrid_parsed.text)

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

    def test_reindex_updates_current_chunks_and_facts_without_extraction(self):
        document, chunk, extraction = self._document_and_fact()
        llm = FixtureLLM(extraction)
        service = KnowledgeService(self.store, llm, embeddings=FixtureEmbeddings(), object_dir=self.temp.name)
        service.ingest(self.scope, document)
        calls_before = llm.calls
        company_before = self.store.get('company', self.scope.company_id, **self.scope.db())
        document_before = self.store.get('document', document.document_id, **self.scope.db())
        fact_before = self.store.get('fact', 'fact-a', **self.scope.db())

        class NewModelEmbeddings(FixtureEmbeddings):
            model_id = 'fixture-new'
            version = 'v2-token-windows-v1'

        count = KnowledgeService(self.store, llm, embeddings=NewModelEmbeddings()).reindex(self.scope)

        self.assertEqual(count, len(document.chunks) + len(extraction['facts']))
        self.assertEqual(llm.calls, calls_before)
        company_after = self.store.get('company', self.scope.company_id, **self.scope.db())
        self.assertEqual(company_after.version, company_before.version)
        self.assertEqual(company_after.payload, company_before.payload)
        self.assertEqual(
            self.store.get('document', document.document_id, **self.scope.db()).version,
            document_before.version,
        )
        self.assertEqual(self.store.get('fact', 'fact-a', **self.scope.db()).version, fact_before.version)
        chunk_index = self.store._documents[('chunk', self.scope.tenant_id, self.scope.company_id, chunk.chunk_id)]
        fact = company_after.payload['facts'][0]
        fact_index = self.store._documents[('fact', self.scope.tenant_id, self.scope.company_id, fact['fact_id'])]
        self.assertEqual(chunk_index['model_id'], 'fixture-new')
        self.assertEqual(chunk_index['model_version'], 'v2-token-windows-v1')
        self.assertEqual(chunk_index['text_version'], f'{document.document_id}:r{document.revision}:{chunk.text_hash}')
        self.assertEqual(fact_index['model_id'], 'fixture-new')
        self.assertEqual(fact_index['model_version'], 'v2-token-windows-v1')
        self.assertEqual(fact_index['text_version'], digest(fact))

    def test_reindex_embedding_failure_rolls_back_all_index_updates(self):
        document, _, extraction = self._document_and_fact()
        llm = FixtureLLM(extraction)
        KnowledgeService(self.store, llm, embeddings=FixtureEmbeddings(), object_dir=self.temp.name).ingest(
            self.scope, document
        )
        documents_before = dict(self.store._documents)
        dimensions_before = dict(self.store._embedding_dimensions)

        class PartiallyInvalidEmbeddings(FixtureEmbeddings):
            model_id = 'fixture-invalid'
            version = 'v3-token-windows-v1'

            def embed(self, texts):
                vectors = super().embed(texts)
                vectors[1] = [float('nan'), 1.0]
                return vectors

        with self.assertRaisesRegex(ValueError, 'finite'):
            KnowledgeService(self.store, llm, embeddings=PartiallyInvalidEmbeddings()).reindex(self.scope)

        self.assertEqual(self.store._documents, documents_before)
        self.assertEqual(self.store._embedding_dimensions, dimensions_before)
        self.assertEqual(llm.calls, 1)

    def test_parser_digest_is_bound_to_original_bytes_at_ingest(self):
        parsed_bytes = b'Parsed and cited text A.'
        document = parse_document('digest-doc', 1, 'source.txt', parsed_bytes, 'text/plain')
        self.assertEqual(document.source_digest, hashlib.sha256(parsed_bytes).hexdigest())
        service = KnowledgeService(self.store, object_dir=self.temp.name)

        with self.assertRaises(KnowledgeRevisionConflict):
            service.ingest(self.scope, document, original=b'Unrelated source B.')

        self.assertIsNone(self.store.get('document', 'digest-doc', **self.scope.db()))

        changed_text = document.model_copy(update={'text': 'Changed text with stale parser digest.'})
        with self.assertRaises(KnowledgeRevisionConflict):
            service.ingest(self.scope, changed_text)

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

    def test_extraction_rejects_invalid_edge_interval(self):
        quote = 'Контракт действует с 2026-10-01 до 2026-09-01.'
        document = parse_document('dated-edge', 1, 'dated.txt', quote.encode(), 'text/plain')
        chunk = document.chunks[0]
        extraction = {'facts': [], 'edges': [{
            'edge_id': 'invalid-interval', 'subject_id': 'company-a', 'predicate': 'buys_from',
            'object_id': 'supplier-a', 'scope': 'private', 'evidence_refs': [chunk.chunk_id],
            'derivation': 'extracted', 'verification_status': 'source_supported',
            'source_quote': quote, 'valid_from': '2026-10-01T00:00:00Z',
            'valid_until': '2026-09-01T00:00:00Z',
        }]}

        with self.assertRaises(KnowledgeExtractionError):
            KnowledgeService(self.store, FixtureLLM(extraction), object_dir=self.temp.name).ingest(
                self.scope, document
            )

        self.assertEqual(
            self.store.get('document', document.document_id, **self.scope.db())
            .payload['document']['status'], 'failed'
        )

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

    def test_retrieval_batches_document_history_and_chunk_lookup_once(self):
        class CountingStore(MemoryStore):
            def __init__(self):
                super().__init__()
                self.calls = {'document_list': 0, 'chunk_list': 0, 'histories': 0, 'history': 0, 'get': 0}

            def list(self, kind, **kwargs):
                if kind == 'document':
                    self.calls['document_list'] += 1
                elif kind == 'chunk':
                    self.calls['chunk_list'] += 1
                return super().list(kind, **kwargs)

            def histories(self, kind, **kwargs):
                self.calls['histories'] += 1
                return super().histories(kind, **kwargs)

            def history(self, kind, key, **kwargs):
                self.calls['history'] += 1
                return super().history(kind, key, **kwargs)

            def get(self, kind, key, **kwargs):
                self.calls['get'] += 1
                return super().get(kind, key, **kwargs)

        store = CountingStore()
        for number in range(3):
            document = parse_document(f'lookup-{number}', 1, 'source.txt',
                                      f'Supplier {number} contract'.encode(), 'text/plain')
            document = document.model_copy(update={'status': 'ready', 'received_at': AS_OF})
            store.put('document', document.document_id,
                      {'document': document.model_dump(mode='json'), 'revision': 1}, **self.scope.db())
            for chunk in document.chunks:
                store.put('chunk', chunk.chunk_id, chunk.model_dump(mode='json'), **self.scope.db())
        event = Event(event_id='batch-read', event_type='test', action='supplier terms changed',
                      subject='supplier', summary='supplier terms changed', entities=['supplier'],
                      evidence_quote='supplier terms changed')

        HybridRetriever(store).retrieve(self.scope, event, [], AS_OF)

        self.assertEqual(store.calls, {
            'document_list': 0, 'chunk_list': 1, 'histories': 1, 'history': 0, 'get': 1,
        })

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

    def test_graph_traversal_normalizes_each_hop_and_keeps_original_path_ids(self):
        chunk = parse_document('graph-source', 1, 'source.txt', b'Graph evidence.', 'text/plain').chunks[0]
        for edge in [
            KnowledgeEdge(edge_id='edge-1', subject_id='company-a', predicate='supplies_to',
                          object_id='  Supplier A  ', evidence_refs=[chunk.chunk_id],
                          verification_status='source_supported'),
            KnowledgeEdge(edge_id='edge-2', subject_id='supplier a', predicate='produces',
                          object_id='Factory X', evidence_refs=[chunk.chunk_id],
                          verification_status='source_supported'),
        ]:
            self.store.put('edge', edge.edge_id, edge.model_dump(mode='json'), **self.scope.db())
        event = Event(event_id='graph-normalized', event_type='supplier_change', action='production change',
                      subject='factory x', summary='production change', entities=['factory x'],
                      evidence_quote='production change')

        paths = HybridRetriever(self.store, max_depth=2)._paths(self.scope, event, AS_OF, [chunk])

        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].node_ids, ['company-a', '  Supplier A  ', 'Factory X'])
        self.assertEqual(paths[0].relation_types, ['->supplies_to', '->produces'])

    def test_graph_traversal_does_not_emit_normalized_cycle_as_target(self):
        chunk = parse_document('graph-cycle-source', 1, 'source.txt', b'Graph evidence.', 'text/plain').chunks[0]
        edge = KnowledgeEdge(edge_id='cycle-1', subject_id='company-a', predicate='part_of',
                             object_id='COMPANY A', evidence_refs=[chunk.chunk_id],
                             verification_status='source_supported')
        self.store.put('edge', edge.edge_id, edge.model_dump(mode='json'), **self.scope.db())
        event = Event(event_id='graph-cycle', event_type='supplier_change', action='company change',
                      subject='company a', summary='company change', entities=['company a'],
                      evidence_quote='company change')

        paths = HybridRetriever(self.store, max_depth=3)._paths(self.scope, event, AS_OF, [chunk])

        self.assertEqual(paths, [])

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

        invented_date = json.dumps({'edges': [{
            'id': 'dated-edge', 'source': 'company-a', 'target': 'supplier-a', 'type': 'buys_from',
            'source_refs': [chunk.chunk_id], 'source_quote': 'Компания закупает упаковку у Поставщик-А.',
            'valid_from': '2026-10-01T00:00:00Z',
        }]})
        with self.assertRaisesRegex(ValueError, 'dates must appear explicitly'):
            import_graphify_json(invented_date, self.scope, document)

    def test_graphify_json_import_rejects_invalid_edge_interval(self):
        quote = 'Контракт действует с 2026-10-01 до 2026-09-01.'
        document = parse_document('graph-dated-edge', 1, 'dated.txt', quote.encode(), 'text/plain')
        chunk = document.chunks[0]
        graph_json = json.dumps({'edges': [{
            'id': 'invalid-interval', 'source': 'company-a', 'target': 'supplier-a',
            'type': 'buys_from', 'source_refs': [chunk.chunk_id], 'source_quote': quote,
            'valid_from': '2026-10-01T00:00:00Z', 'valid_until': '2026-09-01T00:00:00Z',
        }]})

        with self.assertRaisesRegex(ValueError, 'invalid edge interval'):
            import_graphify_json(graph_json, self.scope, document)


if __name__ == '__main__':
    unittest.main()
