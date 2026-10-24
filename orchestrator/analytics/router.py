"""Scoped analytics routes; the host injects authenticated company ownership."""

import base64
import binascii
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from orchestrator.llm import AIError
from orchestrator.models import digest
from .knowledge import DocumentParseError, KnowledgeExtractionError, parse_document
from .models import CompanyProfile, Model, NewsArticle, Scope
from .store import RevisionConflict, StoreBusy


class DocumentInput(Model):
    document_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    filename: str = Field(min_length=1, max_length=500)
    media_type: str
    content_base64: str = Field(min_length=1, max_length=16 * 1024 * 1024)


class Question(Model):
    question: str = Field(min_length=1, max_length=6000)
    conversation_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1)


class Refresh(Model):
    reason: str = Field(default='user_requested', min_length=1, max_length=300)
    retry_failed: bool = False


class UserState(Model):
    workflow: Literal['open', 'watching', 'closed'] = 'open'
    pinned: bool = False
    mark_read: bool = False


def _invoke(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, detail={'code': 'not_found'}) from None
    except RevisionConflict:
        raise HTTPException(409, detail={'code': 'revision_conflict'}) from None
    except StoreBusy:
        raise HTTPException(503, detail={'code': 'busy'}) from None
    except (ValueError, DocumentParseError):
        raise HTTPException(422, detail={'code': 'invalid_input'}) from None
    except KnowledgeExtractionError:
        raise HTTPException(503, detail={'code': 'extraction_failed'}) from None
    except AIError as exc:
        raise HTTPException(429 if exc.code in {'budget_exceeded', 'rate_limited', 'busy'} else 503,
                            detail=exc.public(),
                            headers={'Retry-After': str(max(1, int(exc.retry_at - time.time()) + 1))}
                            if exc.retry_at else None) from None


def create_router(service, authorize, *, authorize_ingestion=None):
    """Auth returns trusted scopes; global news requires a separate ingestion principal."""
    router = APIRouter(prefix='/v1/analytics', tags=['analytics'])

    def deny_ingestion():
        raise HTTPException(403, detail={'code': 'ingestion_permission_required'})

    news_authorize = authorize_ingestion or deny_ingestion

    @router.post('/news')
    def ingest(article: NewsArticle, scope: Scope = Depends(news_authorize)):
        return _invoke(service.ingest_news, article, scopes=[scope])

    @router.put('/company')
    def profile(value: CompanyProfile, expected_revision: int | None = Query(None, ge=0),
                scope: Scope = Depends(authorize)):
        return _invoke(service.update_company_profile, scope, value, expected_revision=expected_revision)

    @router.post('/documents', status_code=202)
    def document(value: DocumentInput, scope: Scope = Depends(authorize)):
        try:
            content = base64.b64decode(value.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, detail={'code': 'invalid_encoding'}) from None
        parsed = _invoke(parse_document, value.document_id, value.revision, value.filename,
                         content, value.media_type)
        return _invoke(service.ingest_company_document, scope, parsed, original=content)

    @router.get('/documents')
    def documents(scope: Scope = Depends(authorize)):
        fields = {'file_id', 'filename', 'document_id', 'status', 'attempts', 'error', 'retry_at'}
        return [{key: value for key, value in row.payload.items() if key in fields}
                for row in service.store.list('integration_file', **scope.db())]

    @router.post('/events/{event_id}/analyze')
    def analyze(event_id: str, scope: Scope = Depends(authorize)):
        return _invoke(service.analyze_event_for_company, scope, event_id)

    @router.get('/situation')
    def situation(scope: Scope = Depends(authorize)):
        return _invoke(service.get_company_situation, scope)

    @router.get('/issues')
    def issues(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
               scope: Scope = Depends(authorize)):
        return _invoke(service.list_company_issues, scope, offset=offset, limit=limit)

    @router.get('/issues/{issue_id}')
    def issue(issue_id: str, version: int | None = Query(None, ge=1), scope: Scope = Depends(authorize)):
        return _invoke(service.get_issue, scope, issue_id, version=version)

    @router.get('/issues/{issue_id}/evidence')
    def evidence(issue_id: str, version: int | None = Query(None, ge=1), scope: Scope = Depends(authorize)):
        return _invoke(service.get_issue_evidence, scope, issue_id, version=version)

    @router.get('/issues/{issue_id}/history')
    def history(issue_id: str, scope: Scope = Depends(authorize)):
        return _invoke(service.get_issue_history, scope, issue_id)

    @router.patch('/issues/{issue_id}/state')
    def user_state(issue_id: str, value: UserState, scope: Scope = Depends(authorize)):
        return _invoke(service.set_user_state, scope, issue_id, **value.model_dump())

    @router.get('/issues/{issue_id}/state')
    def read_user_state(issue_id: str, scope: Scope = Depends(authorize)):
        return _invoke(service.get_user_state, scope, issue_id)

    @router.get('/conversations/{conversation_id}')
    def conversation(conversation_id: str, scope: Scope = Depends(authorize)):
        return _invoke(service.get_conversation, scope, conversation_id)

    @router.post('/issues/{issue_id}/questions')
    def question(issue_id: str, value: Question, scope: Scope = Depends(authorize)):
        return _invoke(service.ask_about_issue, scope, issue_id, **value.model_dump())

    @router.post('/refresh', status_code=202)
    def refresh(value: Refresh, scope: Scope = Depends(authorize)):
        return _invoke(refresh_company, value, scope)

    def refresh_company(value, scope):
        if value.retry_failed:
            for row in service.store.list('integration_file', **scope.db()):
                with service.store.lock('backend-file:' + digest([scope.db(), row.key])):
                    current = service.store.get('integration_file', row.key, **scope.db())
                    if current is not None and current.payload['status'] == 'failed':
                        service.store.put('integration_file', row.key,
                            dict(current.payload, status='queued', attempts=0, error=None, retry_at=0), **scope.db())
        return service.reprocess_company(scope, reason=value.reason, retry_failed=value.retry_failed)

    @router.get('/jobs/{job_id}')
    def job(job_id: str, scope: Scope = Depends(authorize)):
        record = service.store.get('job', job_id, **scope.db())
        if record is None:
            raise HTTPException(404, detail={'code': 'not_found'})
        return record.payload

    return router
