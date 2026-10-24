"""Strict internal models for model-assisted extraction."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _non_blank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Value must not be empty or whitespace")
    return value


def _unique(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("Values must be unique")
    return values


class DocumentBlock(_StrictModel):
    block_id: str
    start: int
    end: int

    _valid_id = field_validator("block_id")(_non_blank)

    @model_validator(mode="after")
    def valid_range(self):
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Invalid block range")
        return self


class SourceDocument(_StrictModel):
    document_revision: str
    text: str
    blocks: list[DocumentBlock]

    _valid_revision = field_validator("document_revision")(_non_blank)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str) -> str:
        if value and not value.strip():
            raise ValueError("Document text must not contain only whitespace")
        return value

    @model_validator(mode="after")
    def valid_blocks(self):
        if self.text and not self.blocks:
            raise ValueError("A non-empty document requires blocks")
        if not self.text and self.blocks:
            raise ValueError("An empty document cannot contain blocks")
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Block IDs must be unique")
        if any(block.end > len(self.text) for block in self.blocks):
            raise ValueError("Block range exceeds document text")
        return self

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class EvidenceLocator(_StrictModel):
    block_id: str
    start: int | None = None
    end: int | None = None

    _valid_block_id = field_validator("block_id")(_non_blank)

    @model_validator(mode="after")
    def valid_offsets(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Evidence offsets must both be set or both be null")
        if self.start is not None and (self.start < 0 or self.end <= self.start):
            raise ValueError("Invalid evidence offsets")
        return self


class Evidence(_StrictModel):
    evidence_id: str
    document_revision: str
    text_hash: str
    locator: EvidenceLocator
    quote: str

    _valid_ids = field_validator("evidence_id", "document_revision")(_non_blank)
    _valid_quote = field_validator("quote")(_non_blank)

    @field_validator("text_hash")
    @classmethod
    def valid_text_hash(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Invalid text hash")
        return value


class DateValue(_StrictModel):
    at: AwareDatetime | None
    date: date | None
    precision: Literal["second", "day", "unknown"]
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def valid_evidence_ids(cls, values: list[str]) -> list[str]:
        return _unique([_non_blank(value) for value in values])

    @model_validator(mode="after")
    def consistent_value(self):
        if self.precision == "second":
            valid = self.at is not None and self.date is None
        elif self.precision == "day":
            valid = self.at is None and self.date is not None
        else:
            valid = self.at is None and self.date is None
        if not valid:
            raise ValueError("Date fields do not match precision")
        if self.precision != "unknown" and not self.evidence_ids:
            raise ValueError("Known dates require evidence")
        return self


class ExtractedClaim(_StrictModel):
    claim_id: str
    text: str
    modality: Literal[
        "reported_fact", "announcement", "forecast", "opinion", "unknown"
    ]
    event_date: DateValue | None
    effective_date: DateValue | None
    evidence_ids: list[str]

    _valid_text = field_validator("claim_id", "text")(_non_blank)

    @field_validator("evidence_ids")
    @classmethod
    def valid_evidence_ids(cls, values: list[str]) -> list[str]:
        values = _unique([_non_blank(value) for value in values])
        if not values:
            raise ValueError("Claims require evidence")
        return values


class ExtractionResult(_StrictModel):
    title: str | None
    publication: DateValue
    claims: list[ExtractedClaim]
    evidence: list[Evidence]
    incomplete_fields: list[str]

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        return None if value is None else _non_blank(value)

    @field_validator("incomplete_fields")
    @classmethod
    def valid_incomplete_fields(cls, values: list[str]) -> list[str]:
        return [_non_blank(value) for value in values]

    @model_validator(mode="after")
    def valid_references(self):
        evidence_ids = [item.evidence_id for item in self.evidence]
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs must be unique")
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Claim IDs must be unique")

        known_evidence = set(evidence_ids)
        referenced = list(self.publication.evidence_ids)
        for claim in self.claims:
            referenced.extend(claim.evidence_ids)
            for date_value in (claim.event_date, claim.effective_date):
                if date_value is not None:
                    referenced.extend(date_value.evidence_ids)
        if any(item not in known_evidence for item in referenced):
            raise ValueError("Extraction result references unknown evidence")
        return self
