"""CLI for offline demos and explicit isolated analytics operations."""

import argparse
import json
from pathlib import Path

from .models import CompanyProfile, NewsArticle, Scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['demo', 'migrate', 'cleanup', 'profile', 'document', 'news', 'worker',
                                          'schedule', 'refresh', 'situation', 'issues', 'issue', 'history',
                                          'evidence', 'ask', 'metrics', 'conversation', 'state'])
    parser.add_argument('--tenant')
    parser.add_argument('--company')
    parser.add_argument('--user', default='operator')
    parser.add_argument('--role', default='owner')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--id')
    parser.add_argument('--revision', type=int, default=1)
    parser.add_argument('--question')
    parser.add_argument('--conversation', default='cli')
    parser.add_argument('--request-id')
    parser.add_argument('--postgres-test-dsn')
    parser.add_argument('--triage-mode', choices=['disabled', 'systemone', 'fallback'], default='disabled')
    args = parser.parse_args()
    if args.command == 'demo':
        from .demo import run_demo
        if args.postgres_test_dsn:
            from psycopg.conninfo import conninfo_to_dict, make_conninfo
            from langgraph.checkpoint.postgres import PostgresSaver
            from .migrate import apply_migrations
            from .store import PostgresStore
            connection = conninfo_to_dict(args.postgres_test_dsn)
            loopback = {'127.0.0.1', 'localhost', '::1'}
            if (not connection.get('dbname', '').startswith('analytics_test_')
                    or connection.get('host') not in loopback
                    or connection.get('hostaddr', '127.0.0.1') not in {'127.0.0.1', '::1'}
                    or connection.get('service')):
                parser.error('Demo requires an explicit loopback analytics_test_* database')
            args.postgres_test_dsn = make_conninfo(args.postgres_test_dsn,
                hostaddr='::1' if connection['host'] == '::1' else '127.0.0.1')
            apply_migrations(args.postgres_test_dsn, connect_timeout=5, statement_timeout_ms=10000)
            with PostgresSaver.from_conn_string(args.postgres_test_dsn) as checkpoints:
                checkpoints.setup()
                result = run_demo(PostgresStore(args.postgres_test_dsn, connect_timeout=5, statement_timeout_ms=10000),
                                  checkpointer=checkpoints, triage_mode=args.triage_mode)
        else:
            result = run_demo(triage_mode=args.triage_mode)
    elif args.command in {'migrate', 'cleanup'}:
        from .runtime import load_analytics_settings, migrate, cleanup
        config = load_analytics_settings()
        result = {'applied': migrate(config)} if args.command == 'migrate' else cleanup(config)
    else:
        if not args.tenant or not args.company:
            parser.error('--tenant and --company are required')
        scope = Scope(tenant_id=args.tenant, company_id=args.company, user_id=args.user, role=args.role)
        read_only = args.command in {'situation', 'issues', 'issue', 'history', 'evidence', 'metrics', 'conversation', 'state'}
        from .runtime import runtime
        with runtime(read_only=read_only) as service:
            if args.command in {'profile', 'news', 'document'} and not args.file:
                parser.error('--file is required')
            if args.command == 'profile':
                result = service.update_company_profile(scope, CompanyProfile.model_validate_json(args.file.read_text()))
            elif args.command == 'news':
                result = service.ingest_news(NewsArticle.model_validate_json(args.file.read_text()), scopes=[scope])
            elif args.command == 'document':
                from .knowledge import parse_document
                import mimetypes
                content = args.file.read_bytes()
                document = parse_document(args.id or args.file.name, args.revision, args.file.name,
                                          content, mimetypes.guess_type(args.file.name)[0] or 'text/plain')
                result = service.ingest_company_document(scope, document, original=content)
            elif args.command == 'worker':
                result = service.process_jobs(scope)
            elif args.command == 'schedule':
                result = service.scheduled_refresh(scope)
            elif args.command == 'refresh':
                result = service.reprocess_company(scope, reason='cli_requested', retry_failed=True)
            elif args.command == 'situation':
                result = service.get_company_situation(scope)
            elif args.command == 'issues':
                result = service.list_company_issues(scope)
            elif args.command == 'metrics':
                result = service.store.metrics()
            else:
                if not args.id:
                    parser.error('--id is required')
                if args.command == 'ask':
                    if not args.question or not args.request_id:
                        parser.error('--question and --request-id are required')
                    result = service.ask_about_issue(scope, args.id, args.question,
                        conversation_id=args.conversation, request_id=args.request_id)
                else:
                    method = {'issue': service.get_issue, 'history': service.get_issue_history,
                              'evidence': service.get_issue_evidence, 'conversation': service.get_conversation,
                              'state': service.get_user_state}[args.command]
                    result = method(scope, args.id)
    def encode(value):
        if hasattr(value, 'model_dump'):
            return value.model_dump(mode='json')
        raise TypeError(type(value).__name__)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=encode))


if __name__ == '__main__':
    main()
