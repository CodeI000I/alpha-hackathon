"""Один проход исполнения с переданным обработчиком и сохранённым снимком."""

import json

from .repository import LeaseLost, RepositoryUnavailable
from .result_models import JobResult


PROCESSING_ERRORS = {
    "SOURCE_POLICY_DENIED": ("Source policy does not permit this request.", False),
    "FEED_UNAVAILABLE": ("Feed unavailable.", True),
    "FEED_INVALID": ("Feed could not be parsed.", False),
}


class ProcessingError(Exception):
    def __init__(self, code):
        if code not in PROCESSING_ERRORS:
            raise ValueError("Unsupported processing error code")
        message, retryable = PROCESSING_ERRORS[code]
        self.error = {"code": code, "message": message, "retryable": retryable}
        super().__init__(code)


def _result_snapshot(raw, request, max_items):
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ValueError("Handler must return a result object with items")
    limited = len(raw["items"]) > max_items
    candidate = {**raw, "items": raw["items"][:max_items]}
    result = JobResult.model_validate_json(json.dumps(candidate), strict=True)
    if result.job_id != request["job_id"]:
        raise ValueError("Result belongs to another job")
    for item in result.items:
        if (
            item.provenance.source_id != request["source_id"]
            or item.provenance.policy_version != request["policy_version"]
        ):
            raise ValueError("Result provenance belongs to another request")
        if item.fetched_at is None and "fetched_at" not in item.incomplete_fields:
            item.incomplete_fields.append("fetched_at")
    if limited:
        if "items" not in result.incomplete_fields:
            result.incomplete_fields.append("items")
    if result.incomplete_fields or any(
        item.content_status != "full" or item.error or item.incomplete_fields
        or item.date_precision == "unknown"
        for item in result.items
    ):
        result.result_status = "partial"
    return result.model_dump(mode="json")


def execute_once(repository, handler, *, lease_seconds, max_attempts, max_items):
    """Захватывает максимум одно задание; время и повторы ограничиваются конфигурацией."""
    for name, value in (("lease_seconds", lease_seconds), ("max_attempts", max_attempts),
                        ("max_items", max_items)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not callable(handler):
        raise ValueError("handler must be callable")
    job = repository.claim(lease_seconds=lease_seconds, max_attempts=max_attempts)
    if job is None or job["status"] == "failed":
        return job

    error = None
    result = None
    try:
        raw = handler(dict(job["request"]))
    except ProcessingError as exc:
        error = exc.error
    except (RepositoryUnavailable, LeaseLost):
        raise
    except Exception:
        error = {
            "code": "PROCESSING_FAILED", "message": "Job processing failed.",
            "retryable": False,
        }
    else:
        try:
            result = _result_snapshot(raw, job["request"], max_items)
        except Exception:
            error = {
                "code": "INVALID_RESULT", "message": "Handler returned an invalid result.",
                "retryable": False,
            }
    # Storage/lease failures propagate; a failed commit must not become a second finish.
    return repository.finish(job["job_id"], job["lease_token"], result=result, error=error)
