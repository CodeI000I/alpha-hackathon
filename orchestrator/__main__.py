"""Explicit live commands; offline demo is separate from paid API checks."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import httpx
from pydantic import SecretStr, ValidationError

from .config import ConfigurationError, Settings, load_settings
from .decision import SystemOneDecisionProvider, SystemOneUnavailable
from .llm import AIError, LLMClient
from .models import RankRequest
from .pipeline import Pipeline
from .storage import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description='Оркестратор новостной аналитики')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('demo', help='Полный локальный пример через mock API, бесплатно')
    sub.add_parser('check-config', help='Проверка настроек, без сетевых запросов')
    sub.add_parser('check-systemone', help='Проверка доступа к настроенной модели Jev/Clef')
    sub.add_parser('smoke', help='Один реальный короткий запрос, расходует командный бюджет')
    sub.add_parser('worker', help='Однократно обработать доступные долговечные задания')
    serve = sub.add_parser('serve', help='Внутренний HTTP API с Bearer-аутентификацией')
    serve.add_argument('--port', type=int, default=8091)
    for name in ('submit', 'analyze', 'rank'):
        sub.add_parser(name).add_argument('--file', type=Path, required=True)
    sub.add_parser('retry', help='Вернуть failed-задание в очередь, максимум три запуска').add_argument('job_id')
    args = parser.parse_args(argv)
    if args.command == 'demo':
        from .demo import REQUEST, mock_response
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(api_key=SecretStr('offline-demo'), db_path=Path(directory) / 'demo.sqlite3')
            store = Store(settings.db_path)
            client = LLMClient(settings, store, http_client=httpx.Client(transport=httpx.MockTransport(mock_response)))
            try:
                print(json.dumps(Pipeline(settings, store, client).rank(RankRequest.model_validate(REQUEST)),
                                 ensure_ascii=False, indent=2))
            finally:
                client.close()
        return 0
    settings = load_settings()
    if args.command == 'check-systemone':
        if not settings.systemone_url:
            raise ConfigurationError('Заполните AI_SYSTEMONE_URL для проверки Jev/Clef.')
        provider = SystemOneDecisionProvider(
            settings.systemone_url, settings.systemone_model, settings.systemone_api_key,
            timeout_seconds=settings.systemone_timeout_seconds)
        try:
            provider.probe()
        finally:
            provider.close()
        print(f'System One доступен; модель {settings.systemone_model} разрешена аккаунту.')
        return 0
    settings.require_key()
    if args.command == 'smoke':
        settings = settings.model_copy(update={'max_retries': 0})
    if args.command == 'check-config':
        print('Настройки корректны; ключ скрыт. Сетевые запросы не выполнялись.')
        return 0
    if args.command == 'serve':
        if not settings.service_token.get_secret_value():
            raise ConfigurationError('Заполните AI_SERVICE_TOKEN для внутреннего HTTP API.')
        import uvicorn
        uvicorn.run('orchestrator.api:create_app', factory=True, host='127.0.0.1', port=args.port)
        return 0
    store = Store(settings.db_path)
    client = LLMClient(settings, store)
    try:
        if args.command == 'smoke':
            client.complete('decision', [{'role': 'user', 'content': 'Ответь одним словом: ОК'}], max_tokens=64)
            print('API доступен. Выполнен один короткий запрос; текст ответа не выводится.')
            return 0
        pipeline = Pipeline(settings, store, client)
        if args.command in {'submit', 'analyze', 'rank'}:
            request = RankRequest.model_validate_json(args.file.read_text())
            if args.command == 'rank':
                print(json.dumps(pipeline.rank(request), ensure_ascii=False, indent=2))
                return 0
            ids = pipeline.submit(request)
            jobs = [pipeline.run_job(i) if args.command == 'analyze' else store.get_job(i) for i in ids]
        elif args.command == 'worker':
            jobs = pipeline.drain()
        else:
            changed = store.retry(args.job_id)
            print('Задание возвращено в очередь.' if changed else 'Повтор сейчас недоступен.')
            return 0 if changed else 1
        print(json.dumps([{'id': job['id'], 'status': job['status'], 'error': job['error']} for job in jobs],
                         ensure_ascii=False, indent=2))
        return int(any(job['status'] in {'failed', 'budget_exceeded'} for job in jobs))
    finally:
        client.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (AIError, ConfigurationError, SystemOneUnavailable) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (ValidationError, ValueError, OSError):
        print('Проверьте формат входного файла и доступ к хранилищу.', file=sys.stderr)
        sys.exit(1)
