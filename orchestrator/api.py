"""Internal service only. A server-side bearer token authenticates the Go backend."""

import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import ConfigurationError, load_settings
from .llm import AIError, LLMClient
from .models import CaseStatePatch, Company, RankRequest
from .pipeline import Pipeline, Principal
from .storage import Store


class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)


class RefreshRequest(BaseModel):
    company: Company
    roles: list[str] = Field(min_length=1, max_length=9)


def create_app(pipeline=None):
    @asynccontextmanager
    async def lifespan(app):
        if pipeline is None:
            settings = load_settings()
            settings.require_key()
            if not settings.service_token.get_secret_value():
                raise ConfigurationError('AI_SERVICE_TOKEN required for HTTP service')
            store = Store(settings.db_path)
            client = LLMClient(settings, store)
            app.state.pipeline = Pipeline(settings, store, client)
            try:
                yield
            finally:
                client.close()
        else:
            app.state.pipeline = pipeline
            yield

    app = FastAPI(title='News analytics internal API', lifespan=lifespan)

    def authorized(authorization: Annotated[str, Header()] = ''):
        p = app.state.pipeline
        expected = p.settings.service_token.get_secret_value()
        if not expected or not secrets.compare_digest(authorization, f'Bearer {expected}'):
            raise HTTPException(status_code=401, detail='Service authentication required')
        return p

    def principal(x_user_id: Annotated[str, Header()], x_company_id: Annotated[int, Header()]):
        # These headers are assertions made by the authenticated backend after its ACL check.
        if not x_user_id.strip() or x_company_id <= 0:
            raise HTTPException(status_code=403, detail='Principal required')
        return Principal(x_user_id, frozenset({x_company_id}))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default JSON includes the rejected input; never echo documents/secrets.
        return JSONResponse(status_code=422, content={'error': {'code': 'invalid_input'}})

    @app.exception_handler(AIError)
    async def ai_error(request, exc):
        headers = {}
        if exc.retry_at:
            headers['Retry-After'] = str(max(1, int(exc.retry_at - time.time()) + 1))
        status = 429 if exc.code in {'budget_exceeded', 'rate_limited'} else 503
        return JSONResponse(status_code=status, content={'error': exc.public()}, headers=headers)

    @app.exception_handler(PermissionError)
    async def denied(request, exc):
        return JSONResponse(status_code=404, content={'error': {'code': 'not_found'}})

    @app.exception_handler(ValueError)
    async def bad_state(request, exc):
        return JSONResponse(status_code=409, content={'error': {'code': 'conflict'}})

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.post('/rank')
    def rank(request: RankRequest, p=Depends(authorized)):
        return p.rank(request)

    @app.post('/v1/jobs', status_code=202)
    def submit(request: RankRequest, p=Depends(authorized)):
        return {'job_ids': p.submit(request)}

    @app.post('/v1/companies/refresh', status_code=202)
    def refresh(request: RefreshRequest, p=Depends(authorized)):
        return {'job_ids': p.refresh_company(request.company, request.roles)}

    @app.get('/v1/jobs/{job_id}')
    def read(job_id: str, p=Depends(authorized), user=Depends(principal)):
        return p.read(job_id, user)

    @app.post('/v1/jobs/{job_id}/chat')
    def chat(job_id: str, request: ChatRequest, p=Depends(authorized), user=Depends(principal)):
        return p.chat(job_id, user, request.conversation_id, request.question)

    @app.patch('/v1/jobs/{job_id}/state')
    def update_state(job_id: str, request: CaseStatePatch, p=Depends(authorized), user=Depends(principal)):
        return p.update_case(job_id, user, request)

    @app.get('/v1/conversations')
    def conversations(p=Depends(authorized), user=Depends(principal)):
        return p.conversations(user, next(iter(user.company_ids)))

    @app.get('/v1/conversations/{conversation_id}')
    def conversation(conversation_id: str, p=Depends(authorized), user=Depends(principal)):
        return p.conversations(user, next(iter(user.company_ids)), conversation_id)

    return app
