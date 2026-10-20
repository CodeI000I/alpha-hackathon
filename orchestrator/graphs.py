"""Топология LangGraph. Бизнес-операции передаются через handlers.

Сборка доступна без интеграций; вызов неподключённого узла завершится ошибкой.
"""

from collections.abc import Callable, Mapping
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    # shortcut: общий state для схемы; разделить по графам после согласования контрактов.
    task_id: str
    company_id: str
    user_id: str
    role: str
    event_id: str
    event_version: str
    company_version: str
    report_id: str
    report_version: str
    conversation_id: str
    event: dict[str, Any]
    company_context: dict[str, Any]
    candidate_company_ids: list[str]
    evidence: list[dict[str, Any]]
    missing_facts: list[str]
    relevance_score: float
    relevance_reason: str
    report: dict[str, Any]
    question: str
    messages: list[dict[str, Any]]
    answer: str
    status: str
    error: dict[str, Any]
    search_status: str  # ok | no_hits | access_error; не эквивалентны друг другу
    max_searches: int
    searches_used: int
    max_revisions: int
    revisions_used: int
    input_decision: str
    event_decision: str
    candidate_decision: str
    relevance_decision: str
    priority_decision: str
    access_decision: str
    report_decision: str
    job_decision: str
    evidence_decision: str
    quality_decision: str
    answer_decision: str
    answer_quality_decision: str


Node = Callable[[State], dict[str, Any]]


# Линейные связи и развилки разделены, чтобы схема читалась без бизнес-кода.
EDGES = {
    'event': [
        (START, 'validate_event'),
        ('save_event', 'select_companies'),
        ('record_invalid_event', END),
        ('dispatch_company_jobs', END),
    ],
    'company': [
        (START, 'load_company_context'),
        ('load_company_context', 'score_relevance'),
        ('save_feed_card', 'choose_report_priority'),
        ('record_irrelevant', END),
        ('record_uncertain', END), ('mark_report_deferred', END),
        ('enqueue_report', END),
    ],
    'open': [
        (START, 'authorize'),
        ('enqueue_report', 'return_pending'),
        ('return_report', END), ('return_pending', END), ('return_denied', END),
    ],
    'report': [
        (START, 'load_report_inputs'),
        ('load_report_inputs', 'retrieve_evidence'),
        ('retrieve_evidence', 'assess_evidence'),
        ('search_external', 'validate_sources'),
        ('validate_sources', 'assess_evidence'),
        ('draft_report', 'verify_report'),
        ('revise_report', 'verify_report'),
        ('save_report', END), ('save_insufficient_report', END),
    ],
    'chat': [
        (START, 'authorize'),
        ('load_conversation', 'plan_answer'),
        ('retrieve_evidence', 'assess_answer_evidence'),
        ('search_external', 'validate_sources'),
        ('validate_sources', 'assess_answer_evidence'),
        ('draft_answer', 'verify_answer'),
        ('ask_clarification', 'save_conversation'),
        ('answer_insufficient', 'save_conversation'),
        ('save_conversation', END), ('return_denied', END),
    ],
}

BRANCHES = {
    'event': {
        'validate_event': ('input_decision', {
            'valid': 'deduplicate_event', 'invalid': 'record_invalid_event',
        }),
        'deduplicate_event': ('event_decision', {
            'new': 'save_event', 'updated': 'save_event', 'duplicate': END,
        }),
        'select_companies': ('candidate_decision', {
            'found': 'dispatch_company_jobs', 'none': END,
        }),
    },
    'company': {
        'score_relevance': ('relevance_decision', {
            'relevant': 'save_feed_card', 'irrelevant': 'record_irrelevant',
            'uncertain': 'record_uncertain',
        }),
        'choose_report_priority': ('priority_decision', {
            'background': 'enqueue_report', 'on_open': 'mark_report_deferred',
        }),
    },
    'open': {
        'authorize': ('access_decision', {
            'allowed': 'inspect_report', 'denied': 'return_denied',
        }),
        'inspect_report': ('report_decision', {
            'ready': 'return_report', 'running': 'return_pending',
            'missing': 'ensure_report_job', 'stale': 'ensure_report_job',
        }),
        'ensure_report_job': ('job_decision', {
            'created': 'enqueue_report', 'existing': 'return_pending',
        }),
    },
    'report': {
        'assess_evidence': ('evidence_decision', {
            'enough': 'draft_report', 'search': 'search_external',
            'insufficient': 'save_insufficient_report',
        }),
        'verify_report': ('quality_decision', {
            'valid': 'save_report', 'revise': 'revise_report',
            'insufficient': 'save_insufficient_report',
        }),
    },
    'chat': {
        'authorize': ('access_decision', {
            'allowed': 'load_conversation', 'denied': 'return_denied',
        }),
        'plan_answer': ('answer_decision', {
            'direct': 'draft_answer', 'internal': 'retrieve_evidence',
            'external': 'search_external', 'clarify': 'ask_clarification',
        }),
        'assess_answer_evidence': ('evidence_decision', {
            'enough': 'draft_answer', 'search': 'search_external',
            'insufficient': 'answer_insufficient',
        }),
        'verify_answer': ('answer_quality_decision', {
            'valid': 'save_conversation', 'insufficient': 'answer_insufficient',
        }),
    },
}


def _remaining(state: State, kind: str) -> bool:
    limit = state.get(f'max_{kind}', 0)
    used = state.get(f'{kind}_used', 0)
    if type(limit) is not int or type(used) is not int or min(limit, used) < 0:
        raise ValueError(f'{kind}: лимит и счётчик должны быть целыми >= 0')
    return used < limit


def _handler(name: str, handlers: Mapping[str, Node], decision=None) -> Node:
    def execute(state: State) -> dict[str, Any]:
        if name not in handlers:
            raise NotImplementedError(f'Не подключена операция: {name}')
        update = handlers[name](state)
        if not isinstance(update, dict):
            raise TypeError(f'{name}: узел должен возвращать dict с обновлением state')
        if decision:
            key, paths = decision
            if update.get(key) not in paths:
                raise ValueError(f'{name}: ожидается {key} из {tuple(paths)}')
        if name == 'search_external':
            update = {**update, 'searches_used': state.get('searches_used', 0) + 1}
        if name == 'revise_report':
            update = {**update, 'revisions_used': state.get('revisions_used', 0) + 1}
        return update
    return execute


def _router(key, paths, flow):
    def route(state: State) -> str:
        destination = paths[state[key]]
        if destination == 'search_external' and not _remaining(state, 'searches'):
            return 'save_insufficient_report' if flow == 'report' else 'answer_insufficient'
        if destination == 'revise_report' and not _remaining(state, 'revisions'):
            return 'save_insufficient_report'
        return destination
    return route


def build_graphs(handlers: Mapping[str, Node] | None = None, *, checkpointer=None):
    """Собрать графы. handlers — синхронные операции; I/O и политики реализуются снаружи.

    company запускается заданием из dispatch_company_jobs для одной компании.
    report запускается заданием из enqueue_report как из фона, так и при клике.
    """
    handlers = handlers or {}
    graphs = {}
    for flow in ('event', 'company', 'open', 'report', 'chat'):
        edges = EDGES[flow]
        branches = BRANCHES[flow]
        names = {name for edge in edges for name in edge}
        names.update(branches)
        for _, paths in branches.values():
            names.update(paths.values())
        graph = StateGraph(State)
        for name in sorted(names - {START, END}):
            graph.add_node(name, _handler(name, handlers, branches.get(name)))
        for source, target in edges:
            graph.add_edge(source, target)
        for name, (key, paths) in branches.items():
            destinations = set(paths.values())
            if 'search_external' in destinations:
                destinations.add('save_insufficient_report' if flow == 'report' else 'answer_insufficient')
            if 'revise_report' in destinations:
                destinations.add('save_insufficient_report')
            graph.add_conditional_edges(name, _router(key, paths, flow),
                                        {target: target for target in destinations})
        graphs[flow] = graph.compile(checkpointer=checkpointer)
    return graphs
