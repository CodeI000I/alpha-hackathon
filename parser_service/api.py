"""HTTP-приём, состояния и сохранённые результаты заданий."""

import json
import os
from datetime import datetime
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import FastAPI, Path
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .config import positive_setting
from .repository import JobConflict, JobRepository, RepositoryUnavailable
from .result_models import JobResult, ResultError


IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
Identifier = Annotated[str, Field(strict=True, pattern=IDENTIFIER_PATTERN)]
JobIdPath = Annotated[str, Path(pattern=IDENTIFIER_PATTERN)]


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    job_id: Identifier
    mode: Literal["discover"]
    source_id: Literal["cbr_press"]
    requested_level: Literal["content"]
    policy_version: Identifier


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    status_url: str
    result_url: str
    created_at: datetime
    updated_at: datetime
    error: ResultError | None = None


def error_response(status, code, message, *, retryable=False):
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        status_code=status,
        headers=headers,
    )


class RequestBoundary:
    """Проверяет доступ и ограничивает поток до JSON-декодирования."""

    def __init__(self, app, *, api_token, max_request_bytes):
        self.app = app
        self.authorization = b"Bearer " + api_token.encode("ascii")
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = [v for k, v in scope["headers"] if k == b"authorization"]
        if len(authorization) != 1 or not compare_digest(
            authorization[0], self.authorization
        ):
            await error_response(401, "UNAUTHORIZED", "Service token required.")(
                scope, receive, send
            )
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_request_bytes:
                await error_response(
                    413, "REQUEST_TOO_LARGE", "Request exceeds configured size."
                )(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        consumed = False

        async def replay():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def create_app(*, repository=None, api_token=None, max_request_bytes=None):
    """Uvicorn factory; создание приложения не открывает соединений и не мигрирует БД."""
    if api_token is None:
        api_token = os.environ.get("PARSER_API_TOKEN", "")
    if max_request_bytes is None:
        max_request_bytes = positive_setting("PARSER_MAX_REQUEST_BYTES")
    if (
        not isinstance(api_token, str)
        or not api_token
        or not api_token.isascii()
        or any(c.isspace() or not c.isprintable() for c in api_token)
    ):
        raise ValueError("PARSER_API_TOKEN must be a nonempty printable ASCII token")
    if type(max_request_bytes) is not int or max_request_bytes <= 0:
        raise ValueError("PARSER_MAX_REQUEST_BYTES must be a positive integer")
    if repository is None:
        dsn = os.environ.get("PARSER_DATABASE_URL", "")
        if not dsn.strip():
            raise ValueError("PARSER_DATABASE_URL is required")
        repository = JobRepository(
            dsn,
            connect_timeout=positive_setting("PARSER_CONNECT_TIMEOUT_SECONDS"),
            statement_timeout_ms=positive_setting("PARSER_STATEMENT_TIMEOUT_MS"),
        )

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        RequestBoundary, api_token=api_token, max_request_bytes=max_request_bytes
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error_response(422, "INVALID_REQUEST", "Invalid request.")

    @app.exception_handler(JobConflict)
    async def conflict(request, exc):
        return error_response(409, "JOB_CONFLICT", "Job ID belongs to another request.")

    @app.exception_handler(RepositoryUnavailable)
    async def storage_unavailable(request, exc):
        return error_response(
            503, "STORAGE_UNAVAILABLE", "Storage unavailable.", retryable=True
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(exc.status_code, "HTTP_ERROR", "Request rejected.")

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error_response(500, "INTERNAL_ERROR", "Internal service error.")

    def public_job(row):
        path = f"/v1/jobs/{row['job_id']}"
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "status_url": path,
            "result_url": f"{path}/result",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error": row.get("error"),
        }

    @app.post("/v1/jobs", status_code=202, response_model=JobResponse,
              response_model_exclude_none=True)
    def submit_job(job: JobRequest):
        return public_job(repository.submit(job.model_dump()))

    @app.get("/v1/jobs/{job_id}", response_model=JobResponse,
             response_model_exclude_none=True)
    def get_job(job_id: JobIdPath):
        row = repository.get(job_id)
        if row is None:
            return error_response(404, "JOB_NOT_FOUND", "Job not found.")
        return public_job(row)

    @app.get("/v1/jobs/{job_id}/result", response_model=JobResult)
    def get_result(job_id: JobIdPath):
        row = repository.get(job_id)
        if row is None:
            return error_response(404, "JOB_NOT_FOUND", "Job not found.")
        if row["status"] == "succeeded":
            # JSON-mode validation preserves strict ISO dates read from JSONB.
            return JobResult.model_validate_json(json.dumps(row["result"]), strict=True)
        if row["status"] == "failed":
            error = ResultError.model_validate(row["error"])
            return error_response(
                409, "JOB_FAILED", error.message, retryable=error.retryable
            )
        return error_response(
            409, "RESULT_NOT_READY", "Job result is not ready.", retryable=True
        )

    return app
