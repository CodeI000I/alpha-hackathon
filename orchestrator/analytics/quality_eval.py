"""Offline contract replay: real graph, retrieval and LLM adapter; synthetic HTTP only."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from pydantic import SecretStr

from orchestrator.config import Settings
from orchestrator.llm import AIError, LLMClient
from .demo import AS_OF, SyntheticGateway
from .evaluation import compare_pipelines
from .knowledge import HybridRetriever, KnowledgeService, parse_document
from .models import CompanyProfile, NewsArticle, Scope
from .service import AnalyticsService
from .store import MemoryStore


CORPUS = Path(__file__).with_name('evals') / 'answer-quality.json'
CONTRACT = ('Компания закупает комплектующие у supplier_x. Поставщик использует sea_route. '
            'Цена определяется при отгрузке.')


class ReplayGateway(SyntheticGateway):
    def __init__(self, fixture):
        super().__init__()
        self.fixture, self.fact_ids = fixture, []

    def respond(self, name, context):
        output = super().respond(name, context)
        if name == 'FactExtraction':
            output['facts'][0].update(self.fixture.get('fact_patch', {}))
            for index in range(1, self.fixture.get('fact_count', 1)):
                output['facts'].append(dict(output['facts'][0], fact_id=f'supply-contract-{index}'))
        if name == 'ImpactAssessment':
            self.fact_ids = [fact['fact_id'] for fact in context['evidence']['company_facts']]
        output.update(deepcopy(self.fixture.get('responses', {}).get(name, {})))
        return output


def replay_case(fixture, *, as_of, context_budget):
    """Every resource is disposable; no environment settings or network clients are used."""
    clock = datetime.fromisoformat(as_of)
    store, gateway = MemoryStore(), ReplayGateway(fixture)
    settings = Settings(api_key=SecretStr('synthetic-quality-key'),
                        requests_per_minute=120, max_input_chars=context_budget, max_retries=0)
    client = LLMClient(settings, store, http_client=httpx.Client(transport=httpx.MockTransport(gateway)))
    scope = Scope(tenant_id='quality-fixture', company_id='plant', user_id='fixture-user')
    try:
        with TemporaryDirectory(prefix='alfa-quality-docs-') as directory:
            service = AnalyticsService(store, client, clock=lambda: clock,
                retriever=HybridRetriever(store, top_k=fixture.get('top_k', 12)),
                knowledge=KnowledgeService(store, client, object_dir=directory), debounce_seconds=0)
            service.update_company_profile(scope, CompanyProfile(name='Синтетическая компания'))
            contract = fixture.get('contract', CONTRACT)
            if contract is not None:
                document = parse_document('contract', 1, 'contract.txt', contract.encode(), 'text/plain')
                document.received_at = clock
                service.ingest_company_document(scope, document, original=contract.encode())
            label = None
            try:
                event_id = service.ingest_news(NewsArticle(source='synthetic-quality', news_id='supplier',
                    title='Поставщик изменяет прайс', content='supplier_x объявил повышение прайса с ноября.',
                    published_at=clock, received_at=clock))['event_id']
                impact = service.analyze_event_for_company(scope, event_id)
                gateway.fact_ids = [fact.fact_id for fact in impact.evidence.company_facts]
                label = impact.route
                if fixture.get('question'):
                    issue = service.list_company_issues(scope)[0]
                    service.ask_about_issue(scope, issue.issue_id, fixture['question'],
                                            conversation_id='fixture', request_id='question-1')
                    label = 'answered'
            except AIError as exc:
                label = exc.code
            metrics = store.metrics()
            return dict(label=label, fact_ids=gateway.fact_ids,
                calls=sum(row['calls'] for row in metrics),
                tokens=sum(row['prompt_tokens'] + row['completion_tokens'] for row in metrics),
                assessment_calls=gateway.calls.count('ImpactAssessment'),
                issues_published=len(service.list_company_issues(scope)),
                replies_saved=sum(len(record.payload['replies'])
                                  for record in store.list('conversation', **scope.db())))
    finally:
        client.close()


def evaluate_quality(cases=None):
    if cases is None:
        cases = json.loads(CORPUS.read_text())['cases']
    if not cases or len({case['fixture_id'] for case in cases}) != len(cases):
        raise ValueError('quality corpus must contain unique nonempty cases')
    fixtures = [{'as_of': AS_OF.isoformat(), 'context_budget': 32000,
                 'expected_fact_ids': ['supply-contract'], 'max_calls': 3, **case} for case in cases]
    observed = []

    def run(fixture, **controls):
        prediction = replay_case(fixture, **controls)
        observed.append(dict(fixture_id=fixture['fixture_id'], expected_label=fixture['expected_label'],
                             max_calls=fixture['max_calls'], **prediction))
        return prediction

    metrics = compare_pipelines(fixtures, {'current': run})['current']
    failures = [row['fixture_id'] for row, fixture in zip(observed, fixtures)
                if row['label'] != row['expected_label'] or row['calls'] > row['max_calls']
                or row['issues_published'] != int(bool(fixture.get('question')) or
                                                 fixture['expected_label'] == 'accepted')
                or row['replies_saved'] != int(fixture['expected_label'] == 'answered')]
    return dict(evaluation_scope='synthetic_contract_replay',
        limitations='Synthetic responses and token usage; this does not measure model truthfulness or production accuracy.',
        metrics=metrics, cases=observed, failures=failures)


if __name__ == '__main__':
    result = evaluate_quality()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result['failures']))
