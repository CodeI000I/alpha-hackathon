"""Private HTTP host for the analytics pipeline, authenticated by the Go backend."""

from contextlib import asynccontextmanager
import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from orchestrator.config import load_settings
from orchestrator.llm import AIError
from parser_service.api import RequestBoundary
from .integration import BackendRankRequest, rank, sync_company
from .models import Scope
from .router import _invoke, create_router
from .runtime import runtime


class _Boundary(RequestBoundary):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        # 12 MiB original becomes 16 MiB base64, plus bounded JSON metadata.
        self.document_boundary = RequestBoundary(app, api_token=kwargs['api_token'],
                                                 max_request_bytes=16 * 1024 * 1024 + 65536)

    async def __call__(self, scope, receive, send):
        if scope.get('path') in {'/healthz', '/readyz'}:
            await self.app(scope, receive, send)
        elif scope.get('path') == '/v1/analytics/documents' and scope.get('method') == 'POST':
            await self.document_boundary(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


def create_app(*, service=None, service_token=None, backend=None):
    token = service_token if service_token is not None else load_settings().service_token.get_secret_value()
    if not token or not token.isascii() or any(c.isspace() or not c.isprintable() for c in token):
        raise ValueError('AI_SERVICE_TOKEN is required for the private analytics API')

    @asynccontextmanager
    async def lifespan(app):
        if service is not None:
            app.state.service = service
            yield
        else:
            with runtime(allow_unconfigured=True) as configured:
                app.state.service = configured
                yield

    app = FastAPI(title='Alpha analytics internal API', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_Boundary, api_token=token, max_request_bytes=2 * 1024 * 1024)
    if backend is None and os.environ.get('ANALYTICS_BACKEND_DATABASE_URL'):
        from .worker import BackendRepository
        backend = BackendRepository(os.environ['ANALYTICS_BACKEND_DATABASE_URL'])

    class ServiceHandle:
        # Runtime opens/closes resources in lifespan; routes never own a second client.
        def __getattr__(self, name):
            return getattr(app.state.service, name)

    def authorize(request: Request):
        headers = request.headers
        user, company, role = (headers.get(name, '') for name in ('x-user-id', 'x-company-id', 'x-role'))
        if (headers.get('x-tenant-id', '') != 'alpha' or len(user) > 20 or len(company) > 20
                or not user.isascii() or not user.isdecimal()
                or not company.isascii() or not company.isdecimal() or int(user) <= 0 or int(company) <= 0
                or not role.strip() or len(role) > 80):
            raise HTTPException(403, detail={'code': 'scope_required'})
        scope = Scope(tenant_id='alpha', company_id=company, user_id=user, role=role)
        if backend is not None:
            value = backend.company(int(company))
            if value is None:
                raise HTTPException(404, detail={'code': 'not_found'})
            _invoke(sync_company, app.state.service, value)
        return scope

    app.include_router(create_router(ServiceHandle(), authorize))

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'detail': {'code': 'invalid_input'}}, status_code=422)

    @app.exception_handler(AIError)
    async def model_error(request, exc):
        headers = {'Retry-After': str(max(1, int(exc.retry_at - time.time()) + 1))} if exc.retry_at else {}
        return JSONResponse({'detail': exc.public()}, status_code=429 if exc.code in {
            'budget_exceeded', 'rate_limited', 'busy'} else 503, headers=headers)

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/readyz')
    def ready():
        try:
            app.state.service.store.get('event', '__readiness__')
            if backend is not None:
                backend.ready()
        except Exception:
            return JSONResponse({'status': 'unavailable'}, status_code=503)
        return {'status': 'ready'}

    @app.post('/rank')
    def rank_news(value: BackendRankRequest):
        company = backend.company(value.company.id) if backend is not None else None
        if backend is not None and company is None:
            raise HTTPException(404, detail={'code': 'company_not_found'})
        return _invoke(rank, app.state.service, value, company=company)

    return app
