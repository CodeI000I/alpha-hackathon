"""Reproducible synthetic demo through the real client and a fake HTTP gateway."""

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
from pydantic import SecretStr

from orchestrator.config import Settings
from orchestrator.llm import LLMClient
from .knowledge import KnowledgeService, parse_document
from .models import CompanyProfile, NewsArticle, Scope
from .service import AnalyticsService
from .store import MemoryStore


AS_OF = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


class SyntheticGateway:
    """Fixture responses test orchestration and grounding, not model accuracy."""
    def __init__(self):
        self.calls = []

    def __call__(self, request):
        body = json.loads(request.content)
        schema = json.loads(body['messages'][0]['content'].split('Верни только JSON по схеме: ', 1)[1])
        context = json.loads(body['messages'][-1]['content'])
        name = schema['title']
        self.calls.append(name)
        output = self.respond(name, context)
        return httpx.Response(200, json={
            'id': 'synthetic', 'object': 'chat.completion', 'created': 0, 'model': body['model'],
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': json.dumps(output, ensure_ascii=False)},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 80, 'total_tokens': 180},
        })

    def respond(self, name, context):
        if name == 'FactExtraction':
            chunk = context['chunks'][0]
            fact = dict(fact_id='supply-contract', text=chunk['text'], subject_id='plant',
                        predicate='buys_from', object_id='supplier_x', exposure='shipment-november',
                        verification_status='source_supported', source_refs=[chunk['chunk_id']],
                        source_quote=chunk['text'], business_factors=['procurement_cost', 'logistics'])
            edges = [dict(edge_id='supplier-link', subject_id='plant', predicate='buys_from', object_id='supplier_x'),
                     dict(edge_id='route-link', subject_id='supplier_x', predicate='uses_route', object_id='sea_route')]
            return {'facts': [fact], 'edges': [dict(edge, evidence_refs=[chunk['chunk_id']],
                    verification_status='source_supported', source_quote=chunk['text']) for edge in edges]}
        if name == 'EventDraft':
            article = context['article']
            event_type = {'logistics': 'logistics_cost', 'currency': 'currency_change', 'supplier': 'supplier_price'}[article['news_id']]
            return dict(event_type=event_type, action=event_type, subject='Ноябрьская поставка',
                        modality='announcement', summary=article['title'],
                        entities=['sea_route' if event_type == 'logistics_cost' else 'supplier_x'],
                        affected_factors=['procurement_cost'], event_time=AS_OF.isoformat(),
                        effective_from='2026-11-01T00:00:00Z', evidence_quote=article['content'])
        if name == 'ImpactAssessment':
            pack = context['evidence']
            fixed = any('фиксирована' in fact['text'] for fact in pack['company_facts'])
            positive = pack['event']['event_type'] == 'currency_change'
            risk = not positive and not (fixed and pack['event']['event_type'] == 'supplier_price')
            return dict(relevance='relevant', evidence_sufficiency='conditional',
                        link_type='indirect' if pack['candidate_paths'] else 'direct',
                        risk_supported='yes' if risk else 'no', opportunity_supported='yes' if positive else 'no',
                        impact_magnitude='unknown', urgency='soon', impact_horizon='short',
                        business_factors=['procurement_cost'],
                        supporting_fact_ids=[fact['fact_id'] for fact in pack['company_facts']],
                        supporting_path_ids=[path['path_id'] for path in pack['candidate_paths']],
                        missing_factors=['Размер и валюта ближайшего платежа'], exposure='shipment-november',
                        summary='Зафиксированная цена ограничивает действие нового прайса.' if fixed and not risk and not positive
                        else ('Изменение валютного курса может снизить затраты.' if positive else 'Изменение может повысить затраты на поставку.'),
                        conditions=['Оценка зависит от условий конкретной отгрузки.'],
                        suggested_action='Сверить цену, валюту и дату ближайшей поставки.')
        if name == 'IssueSynthesis':
            assessments = [item['assessment'] for item in context['impacts']]
            risks = any(a['risk_supported'] == 'yes' for a in assessments)
            opportunities = any(a['opportunity_supported'] == 'yes' for a in assessments)
            effect = 'mixed' if risks and opportunities else 'risk' if risks else 'opportunity' if opportunities else 'neutral'
            return dict(title='Стоимость ноябрьской поставки',
                        summary='Логистика, валютный курс и условия поставщика совместно влияют на ближайшую закупку. '
                                'Направления воздействия различаются; итоговая сумма пока неизвестна.',
                        overall_effect=effect, evidence_sufficiency='conditional',
                        key_unknowns=['Размер и валюта платежа'], conditions=['Проверить условия договора.'],
                        suggested_action='Сопоставить договор и расчёт ближайшей отгрузки.', claims=[])
        if name == 'SnapshotSynthesis':
            return dict(summary='Есть несколько актуальных вопросов, требующих проверки условий.',
                        key_unknowns=[], actions=['Проверить условия ближайших поставок.'], claims=[])
        if name == 'Answer':
            return dict(text='Если цена зафиксирована, новый прайс может не применяться к этому заказу. '
                             'Это сценарий: он не меняет факты компании без подтверждения документом.',
                        evidence_ids=context['issue']['evidence_ids'][:1], missing_facts=['Область действия фиксации цены'])
        raise AssertionError(f'Unexpected synthetic schema: {name}')


def run_demo(store=None, *, checkpointer=None):
    store = store or MemoryStore()
    gateway = SyntheticGateway()
    settings = Settings(api_key=SecretStr('synthetic-test-key'), requests_per_minute=120,
                        max_input_chars=100000, max_retries=0)
    client = LLMClient(settings, store, http_client=httpx.Client(transport=httpx.MockTransport(gateway)))
    scope = Scope(tenant_id='demo-' + uuid4().hex, company_id='plant', user_id='demo-user')
    try:
        with TemporaryDirectory(prefix='alfa-documents-') as directory:
            knowledge = KnowledgeService(store, client, object_dir=directory)
            service = AnalyticsService(store, client, knowledge=knowledge, checkpointer=checkpointer,
                                       clock=lambda: AS_OF, debounce_seconds=0)
            service.update_company_profile(scope, CompanyProfile(name='Производственная компания'))
            text = 'Компания закупает комплектующие у supplier_x. Поставщик использует sea_route. Цена определяется при отгрузке.'
            document = parse_document('contract', 1, 'contract.txt', text.encode(), 'text/plain').model_copy(update={'received_at': AS_OF})
            service.ingest_company_document(scope, document, original=text.encode())
            news = [
                ('logistics', 'Повышение стоимости морской логистики', 'С ноября стоимость перевозки по sea_route вырастет.'),
                ('currency', 'Снижение курса валюты закупки', 'Объявлено снижение курса валюты расчёта по контрактам supplier_x.'),
                ('supplier', 'Поставщик изменяет прайс', 'supplier_x объявил повышение прайса с ноября.'),
            ]
            for news_id, title, content in news:
                service.ingest_news(NewsArticle(source='synthetic-demo', news_id=news_id, title=title, content=content,
                    published_at=AS_OF, received_at=AS_OF), scopes=[scope])
            before = service.get_company_situation(scope)
            issue = service.list_company_issues(scope)[0]
            calls_before_read = len(gateway.calls)
            service.get_issue_evidence(scope, issue.issue_id)
            service.get_company_situation(scope)
            assert len(gateway.calls) == calls_before_read
            answer = service.ask_about_issue(scope, issue.issue_id, 'Что если цена фиксирована?',
                                             conversation_id='demo-dialogue', request_id='question-1')
            updated_text = text + ' Цена фиксирована для ноябрьского заказа.'
            document2 = parse_document('contract', 2, 'contract.txt', updated_text.encode(), 'text/plain').model_copy(update={'received_at': AS_OF})
            service.ingest_company_document(scope, document2, original=updated_text.encode())
            service.process_jobs(scope)
            after = service.get_company_situation(scope)
            latest = service.list_company_issues(scope)[0]
            assert len(store.list('impact', **scope.db())) == 3
            assert len(latest.event_ids) == 3
            assert latest.overall_effect == 'mixed'
            assert after['current']
            return dict(synthetic=True, backend='PostgreSQL' if type(store).__name__ == 'PostgresStore' else 'temporary memory',
                        scope=scope.db(), events=3, issues=1, issue_versions=len(service.get_issue_history(scope, issue.issue_id)),
                        before=before, after=after, answer=answer,
                        evidence=[pack.model_dump(mode='json') for pack in service.get_issue_evidence(scope, latest.issue_id)],
                        calls=gateway.calls, read_calls=0)
    finally:
        client.close()


if __name__ == '__main__':
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
