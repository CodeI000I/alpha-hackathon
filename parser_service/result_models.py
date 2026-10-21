"""Снимок результата задания; глобальные материалы и версии пока не реализованы."""

from datetime import date
from typing import Literal

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, model_validator


class ResultError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    message: str
    retryable: bool


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: Literal["cbr_press"]
    discovery_method: Literal["rss"]
    discovery_url: AnyHttpUrl
    policy_version: str


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: AnyHttpUrl
    media_type: str | None = None


class ResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    external_id: str | None = None
    url: AnyHttpUrl
    title: str | None
    description: str | None = None
    published_at: AwareDatetime | None
    published_date: date | None
    date_precision: Literal["second", "day", "unknown"]
    # При unknown источник проверенного поля может быть известен без значения даты.
    published_at_source: str | None
    content_text: str | None
    content_status: Literal["full", "partial", "metadata_only", "unavailable"]
    extraction_method: str
    fetched_at: AwareDatetime | None = None
    provenance: Provenance
    attachments: list[Attachment] = []
    incomplete_fields: list[str] = []
    error: ResultError | None = None

    @model_validator(mode="after")
    def consistent_fields(self):
        if self.date_precision == "second":
            valid_date = self.published_at is not None and self.published_date is None
        elif self.date_precision == "day":
            valid_date = self.published_date is not None and self.published_at is None
        else:
            valid_date = self.published_at is None and self.published_date is None
        if not valid_date or (
            self.date_precision != "unknown" and not self.published_at_source
        ):
            raise ValueError("Inconsistent publication date fields")
        if self.content_status == "full" and (
            not self.content_text or not self.content_text.strip() or self.error is not None
        ):
            raise ValueError("Full content must contain text without an extraction error")
        if self.content_status in ("metadata_only", "unavailable") and self.content_text is not None:
            raise ValueError("Content status does not permit a body")
        if self.content_status == "unavailable" and self.error is None:
            raise ValueError("Unavailable content must carry a reason")
        return self


class JobResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    job_id: str
    result_status: Literal["complete", "partial"]
    items: list[ResultItem]
    incomplete_fields: list[str] = []
