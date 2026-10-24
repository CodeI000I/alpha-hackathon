import hashlib
import json
import unittest
import warnings
from datetime import date, datetime, timezone

from pydantic import ValidationError

from parser_service.evidence import EvidenceMismatch, validate_evidence
from parser_service.extraction_models import (
    DateValue,
    DocumentBlock,
    Evidence,
    EvidenceLocator,
    ExtractedClaim,
    ExtractionResult,
    SourceDocument,
)


DOCUMENT_TEXT = "Вводный абзац.\nСтавка составит 16 процентов.\nПрогноз сохранён."
FACT_QUOTE = "Ставка составит 16 процентов."
FACT_START = DOCUMENT_TEXT.index(FACT_QUOTE)
FACT_END = FACT_START + len(FACT_QUOTE)
TEXT_HASH = hashlib.sha256(DOCUMENT_TEXT.encode("utf-8")).hexdigest()


def source_document():
    return SourceDocument(
        document_revision="revision-1",
        text=DOCUMENT_TEXT,
        blocks=[
            DocumentBlock(block_id="lead", start=0, end=FACT_END),
            DocumentBlock(
                block_id="body",
                start=DOCUMENT_TEXT.index("Ставка"),
                end=len(DOCUMENT_TEXT),
            ),
        ],
    )


def evidence(**changes):
    values = {
        "evidence_id": "evidence-1",
        "document_revision": "revision-1",
        "text_hash": TEXT_HASH,
        "locator": EvidenceLocator(
            block_id="body", start=FACT_START, end=FACT_END
        ),
        "quote": FACT_QUOTE,
    }
    values.update(changes)
    return Evidence(**values)


def known_day():
    return DateValue(
        at=None,
        date=date(2026, 10, 22),
        precision="day",
        evidence_ids=["evidence-1"],
    )


def extraction_result(**changes):
    values = {
        "title": "Решение по ставке",
        "publication": known_day(),
        "claims": [
            ExtractedClaim(
                claim_id="claim-1",
                text="Ставка составит 16 процентов.",
                modality="announcement",
                event_date=None,
                effective_date=known_day(),
                evidence_ids=["evidence-1"],
            )
        ],
        "evidence": [evidence()],
        "incomplete_fields": ["claims[0].event_date"],
    }
    values.update(changes)
    return ExtractionResult(**values)


class SourceDocumentTests(unittest.TestCase):
    def test_computes_hash_and_allows_overlapping_blocks(self):
        document = source_document()

        self.assertEqual(document.text_hash, TEXT_HASH)
        self.assertLess(document.blocks[1].start, document.blocks[0].end)

    def test_allows_empty_document_only_without_blocks(self):
        empty = SourceDocument(document_revision="revision-empty", text="", blocks=[])

        self.assertEqual(
            empty.text_hash, hashlib.sha256(b"").hexdigest()
        )
        self.assertEqual(empty.blocks, [])

        for text, blocks in (
            ("   ", []),
            ("", [{"block_id": "block", "start": 0, "end": 1}]),
        ):
            with self.subTest(text=text, blocks=blocks), self.assertRaises(ValidationError):
                SourceDocument(
                    document_revision="revision-invalid", text=text, blocks=blocks
                )

    def test_rejects_invalid_document_structure(self):
        invalid_documents = [
            {"document_revision": " ", "text": "text", "blocks": [
                {"block_id": "block", "start": 0, "end": 4}
            ]},
            {"document_revision": "revision", "text": "text", "blocks": []},
            {"document_revision": "revision", "text": "text", "blocks": [
                {"block_id": "block", "start": 1, "end": 1}
            ]},
            {"document_revision": "revision", "text": "text", "blocks": [
                {"block_id": "block", "start": 0, "end": 5}
            ]},
            {"document_revision": "revision", "text": "text", "blocks": [
                {"block_id": "same", "start": 0, "end": 2},
                {"block_id": "same", "start": 2, "end": 4},
            ]},
        ]

        for values in invalid_documents:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                SourceDocument(**values)


class ExtractionModelTests(unittest.TestCase):
    def test_accepts_unknown_day_and_timezone_aware_second_dates(self):
        unknown = DateValue(
            at=None, date=None, precision="unknown", evidence_ids=[]
        )
        day = known_day()
        second = DateValue(
            at=datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc),
            date=None,
            precision="second",
            evidence_ids=["evidence-1"],
        )

        self.assertEqual(unknown.precision, "unknown")
        self.assertEqual(day.date, date(2026, 10, 22))
        self.assertIsNotNone(second.at.tzinfo)

    def test_rejects_inconsistent_or_unsupported_dates(self):
        invalid_dates = [
            {"at": None, "date": None, "precision": "day", "evidence_ids": ["evidence-1"]},
            {"at": datetime(2026, 10, 22, 12, 30), "date": None,
             "precision": "second", "evidence_ids": ["evidence-1"]},
            {"at": None, "date": date(2026, 10, 22), "precision": "day",
             "evidence_ids": []},
            {"at": None, "date": None, "precision": "unknown",
             "evidence_ids": ["evidence-1", "evidence-1"]},
        ]

        for values in invalid_dates:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                DateValue(**values)

    def test_rejects_partial_offsets_whitespace_and_extra_fields(self):
        for values in (
            {"block_id": "body", "start": FACT_START, "end": None},
            {"block_id": "body", "start": None, "end": FACT_END},
            {"block_id": "body", "start": 4, "end": 4},
            {"block_id": "body", "start": True, "end": FACT_END},
            {"block_id": "body", "start": FACT_START, "end": False},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                EvidenceLocator(**values)

        with self.assertRaises(ValidationError):
            evidence(quote="   ")
        for invalid_hash in ("A" * 64, "0" * 63, "g" * 64):
            with self.subTest(invalid_hash=invalid_hash), self.assertRaises(ValidationError):
                evidence(text_hash=invalid_hash)
        with self.assertRaises(ValidationError):
            EvidenceLocator(block_id="body", start=None, end=None, extra="forbidden")

    def test_result_rejects_duplicate_and_unknown_references(self):
        duplicate_evidence = evidence(evidence_id="evidence-1")
        invalid_results = [
            {"evidence": [evidence(), duplicate_evidence]},
            {"claims": [extraction_result().claims[0], extraction_result().claims[0]]},
            {"publication": DateValue(
                at=None, date=date(2026, 10, 22), precision="day",
                evidence_ids=["missing-evidence"],
            )},
            {"claims": [ExtractedClaim(
                claim_id="claim-2", text="Текст", modality="reported_fact",
                event_date=None, effective_date=None,
                evidence_ids=["missing-evidence"],
            )]},
        ]

        for changes in invalid_results:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                extraction_result(**changes)

    def test_result_rejects_unknown_event_and_effective_date_references(self):
        for field in ("event_date", "effective_date"):
            claim_values = {
                "claim_id": "claim-date-reference",
                "text": "Ставка составит 16 процентов.",
                "modality": "announcement",
                "event_date": None,
                "effective_date": None,
                "evidence_ids": ["evidence-1"],
            }
            claim_values[field] = DateValue(
                at=None,
                date=date(2026, 10, 22),
                precision="day",
                evidence_ids=["missing-date-evidence"],
            )

            with self.subTest(field=field), self.assertRaises(ValidationError):
                extraction_result(claims=[ExtractedClaim(**claim_values)])

    def test_preserves_modality_incompleteness_and_empty_unknown_result(self):
        result = extraction_result()
        empty = ExtractionResult(
            title=None,
            publication=DateValue(
                at=None, date=None, precision="unknown", evidence_ids=[]
            ),
            claims=[],
            evidence=[],
            incomplete_fields=["title", "publication"],
        )

        for modality in (
            "announcement", "forecast", "opinion", "unknown", "reported_fact"
        ):
            with self.subTest(modality=modality):
                claim = ExtractedClaim(
                    claim_id=f"claim-{modality}",
                    text="Ставка составит 16 процентов.",
                    modality=modality,
                    event_date=None,
                    effective_date=None,
                    evidence_ids=["evidence-1"],
                )
                self.assertEqual(claim.modality, modality)
        self.assertEqual(result.incomplete_fields, ["claims[0].event_date"])
        self.assertEqual(empty.claims, [])
        self.assertEqual(empty.incomplete_fields, ["title", "publication"])

        with self.assertRaises(ValidationError):
            extraction_result(title="   ")

    def test_rejects_malformed_json_and_output_fields_outside_this_slice(self):
        with self.assertRaises(ValidationError):
            ExtractionResult.model_validate_json('{"title":')

        payload = extraction_result().model_dump(mode="json")
        for field, value in (
            ("summary", "Пересказ"),
            ("body", "Тело"),
            ("url", "https://example.test/news"),
            ("content_status", "full"),
        ):
            invalid = {**payload, field: value}
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ExtractionResult.model_validate_json(json.dumps(invalid))

    def test_json_round_trip_preserves_iso_day_and_second_values(self):
        result = extraction_result(claims=[ExtractedClaim(
            claim_id="claim-round-trip",
            text="Ставка составит 16 процентов.",
            modality="announcement",
            event_date=DateValue(
                at=datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc),
                date=None,
                precision="second",
                evidence_ids=["evidence-1"],
            ),
            effective_date=known_day(),
            evidence_ids=["evidence-1"],
        )])

        restored = ExtractionResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored.publication.date, date(2026, 10, 22))
        self.assertEqual(
            restored.claims[0].event_date.at,
            datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(restored.claims[0].effective_date.date, date(2026, 10, 22))


class EvidenceValidationTests(unittest.TestCase):
    def test_accepts_exact_quote_and_does_not_mutate_inputs(self):
        document = source_document()
        result = extraction_result()
        before_document = document.model_dump(mode="json")
        before_result = result.model_dump(mode="json")

        validate_evidence(result, document)

        self.assertEqual(document.model_dump(mode="json"), before_document)
        self.assertEqual(result.model_dump(mode="json"), before_result)

    def test_accepts_exact_quote_with_block_only_locator(self):
        block_only = EvidenceLocator(block_id="body")
        result = extraction_result(evidence=[evidence(locator=block_only)])

        validate_evidence(result, source_document())

        self.assertIsNone(block_only.start)
        self.assertIsNone(block_only.end)

    def test_rejects_quote_that_only_occurs_in_another_block(self):
        result = extraction_result(evidence=[evidence(
            locator=EvidenceLocator(block_id="lead", start=None, end=None),
            quote="Прогноз сохранён.",
        )])

        self.assert_mismatch_is_safe(result, source_document())

    def test_rejects_foreign_revision_hash_or_block(self):
        cases = [
            evidence(document_revision="other-revision"),
            evidence(text_hash="0" * 64),
            evidence(locator=EvidenceLocator(
                block_id="missing-block", start=None, end=None
            )),
        ]

        for invalid_evidence in cases:
            with self.subTest(evidence=invalid_evidence):
                self.assert_mismatch_is_safe(
                    extraction_result(evidence=[invalid_evidence]), source_document()
                )

    def test_rejects_offsets_outside_block_or_not_matching_quote(self):
        cases = [
            evidence(locator=EvidenceLocator(
                block_id="body", start=0, end=len(FACT_QUOTE)
            )),
            evidence(locator=EvidenceLocator(
                block_id="body", start=FACT_START, end=FACT_END - 1
            )),
        ]

        for invalid_evidence in cases:
            with self.subTest(evidence=invalid_evidence):
                self.assert_mismatch_is_safe(
                    extraction_result(evidence=[invalid_evidence]), source_document()
                )

    def test_revalidates_reference_and_block_lists_after_mutation(self):
        result = extraction_result()
        result.claims[0].evidence_ids.append("missing-after-validation")
        document = source_document()
        document.blocks.append(
            DocumentBlock(block_id="body", start=0, end=len(DOCUMENT_TEXT))
        )

        for changed_result, changed_document in (
            (result, source_document()),
            (extraction_result(), document),
        ):
            with self.subTest(
                references=changed_result.claims[0].evidence_ids,
                block_ids=[block.block_id for block in changed_document.blocks],
            ):
                self.assert_mismatch_is_safe(changed_result, changed_document)

    def test_malformed_document_does_not_leak_through_serialization_warning(self):
        document = source_document()
        document.blocks.append("private-placeholder")

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            self.assert_mismatch_is_safe(extraction_result(), document)

        self.assertEqual(captured, [])

    def assert_mismatch_is_safe(self, result, document):
        with self.assertRaises(EvidenceMismatch) as raised:
            validate_evidence(result, document)

        message = str(raised.exception)
        self.assertNotIn(DOCUMENT_TEXT, message)
        self.assertNotIn(FACT_QUOTE, message)
        self.assertNotIn("Прогноз сохранён.", message)


if __name__ == "__main__":
    unittest.main()
