"""Synthetic offline fixture. Never contacts the bank or the model gateway."""

import json
from pathlib import Path

import httpx

REQUEST = json.loads((Path(__file__).parent / 'examples/bank-request.json').read_text())
IDS = ['news:1', 'profile:1:Б1:0']
CLAIM = {'text': 'Рост стоимости перевозки может увеличить затраты на закупку металла.', 'evidence_ids': IDS}
ASSESSMENT = {
    'score': 0.9, 'confidence': 0.9, 'reason': CLAIM['text'],
    'relevance': 'relevant', 'link_evidence_status': 'sufficient', 'relation_kind': 'direct',
    'risk_supported': True, 'opportunity_supported': False, 'potential_impact_band': 'limited',
    'urgency_band': 'this_month', 'effect_horizon': 'within_month', 'primary_channel': 'logistics',
    'strongest_company_fact': IDS[1], 'strongest_candidate_link': 'not_listed',
    'evidence_ids': IDS, 'causal_chain': [CLAIM], 'mitigations': [],
    'missing_facts': [],
}
REPORT = {
    'headline': 'Пересмотреть бюджет доставки металла', 'summary': CLAIM['text'],
    'facts': [{'text': 'Компания отдельно оплачивает перевозку металла.', 'evidence_ids': [IDS[1]]}],
    'bank_view': [], 'conclusions': [CLAIM], 'risks': [CLAIM], 'opportunities': [],
    'actions': ['Уточнить условия доставки у поставщика.'], 'missing_facts': [],
}
ANSWER = {'text': 'Уточните условия договора перевозки и долю доставки в затратах.',
          'evidence_ids': IDS, 'missing_facts': ['Неизвестна доля доставки в затратах.']}


def completion(content):
    return httpx.Response(200, json={
        'id': 'mock', 'object': 'chat.completion', 'created': 0, 'model': 'mock',
        'choices': [{'index': 0, 'finish_reason': 'stop',
                     'message': {'role': 'assistant', 'content': json.dumps(content, ensure_ascii=False)}}],
        'usage': {'prompt_tokens': 30, 'completion_tokens': 30, 'total_tokens': 60},
    })


def mock_response(request):
    data = json.loads(request.content)
    system = data['messages'][0]['content']
    if '"title":"Assessment"' in system:
        return completion(ASSESSMENT)
    if '"title":"Report"' in system:
        return completion(REPORT)
    return completion(ANSWER)
