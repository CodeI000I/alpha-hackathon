"""Local validation that extracted quotes originate in a saved document."""

from pydantic import ValidationError

from .extraction_models import ExtractionResult, SourceDocument


class EvidenceMismatch(ValueError):
    """The evidence cannot be verified against the supplied document."""


def validate_evidence(result: ExtractionResult, document: SourceDocument) -> None:
    """Validate current model state without exposing document or quote contents."""
    try:
        current_result = ExtractionResult.model_validate(result.model_dump(warnings=False))
        current_document = SourceDocument.model_validate(document.model_dump(warnings=False))

        blocks = {block.block_id: block for block in current_document.blocks}
        for item in current_result.evidence:
            if (
                item.document_revision != current_document.document_revision
                or item.text_hash != current_document.text_hash
            ):
                raise ValueError
            block = blocks.get(item.locator.block_id)
            if block is None:
                raise ValueError
            block_text = current_document.text[block.start:block.end]
            if item.quote not in block_text:
                raise ValueError
            if item.locator.start is not None and (
                item.locator.start < block.start
                or item.locator.end > block.end
                or current_document.text[item.locator.start:item.locator.end] != item.quote
            ):
                raise ValueError
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise EvidenceMismatch("Evidence does not match the source document.") from None
