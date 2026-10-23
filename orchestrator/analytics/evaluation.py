"""Small offline retrieval comparison over supplied synthetic fixture packs.

Metrics describe only these fixtures; they are not estimates of production quality.
"""

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from time import perf_counter


def _unique(values):
    return list(dict.fromkeys(str(value) for value in values))


def _candidates(fixture, variant, graphify):
    result = _unique([*fixture.get('structured_fact_ids', []),
                      *fixture.get('fulltext_fact_ids', [])])
    if variant in {'B', 'C', 'D'}:
        result = _unique([*result, *fixture.get('embedding_fact_ids', [])])
    if variant in {'C', 'D'}:
        result = _unique([*result, *fixture.get('graph_fact_ids', [])])
    if variant == 'D' and graphify is not None:
        result = _unique([*result, *graphify(fixture)])
    return result


def compare_retrieval(fixture_packs: Iterable[Mapping], *, k=5,
                      graphify: Callable[[Mapping], Iterable[str]] | None = None):
    """Compare A/B/C and optionally D on identical fixtures with measured local latency.

    Each fixture supplies ``expected_fact_ids`` plus candidate IDs for the available
    channels. Optional ``graphify`` is called only for D and only on supplied fixtures.
    """
    if type(k) is not int or k < 1:
        raise ValueError('k must be a positive integer')
    fixtures = list(fixture_packs)
    variants = ('A', 'B', 'C', 'D') if graphify is not None else ('A', 'B', 'C')
    result = {}
    for variant in variants:
        relevant_total = retrieved_relevant = retrieved_total = 0
        audit = []
        started = perf_counter()
        for index, fixture in enumerate(fixtures):
            expected = set(fixture.get('expected_fact_ids', []))
            ranked = _candidates(fixture, variant, graphify)[:k]
            found = expected.intersection(ranked)
            relevant_total += len(expected)
            retrieved_relevant += len(found)
            retrieved_total += len(ranked)
            missing = sorted(expected - found)
            if missing:
                audit.append(dict(fixture_id=fixture.get('fixture_id', str(index)),
                                  missing_fact_ids=missing))
        elapsed = perf_counter() - started
        result[variant] = dict(
            recall_at_k=(retrieved_relevant / relevant_total if relevant_total else 1.0),
            precision_at_k=(retrieved_relevant / retrieved_total if retrieved_total else 0.0),
            latency_seconds=elapsed,
            candidate_false_negative_audit=audit,
        )
    return result


def compare_pipelines(fixtures: Iterable[Mapping], variants: Mapping[str, Callable]):
    """Run real local pipeline callables on the same labeled fixtures.

    Each fixture contains ``expected_fact_ids``, ``expected_label``, ``as_of`` and
    ``context_budget``. A variant receives an isolated fixture copy and those two
    shared controls as keyword arguments, then returns ``fact_ids``, ``label`` and
    optional integer ``tokens``/``calls``. Results describe only the supplied
    fixtures; they are not estimates of production retrieval quality.
    """
    fixtures = list(fixtures)
    if not variants:
        raise ValueError('at least one pipeline variant is required')
    for fixture in fixtures:
        if 'as_of' not in fixture or 'context_budget' not in fixture:
            raise ValueError('each fixture must provide as_of and context_budget')

    results = {}
    for name, run in variants.items():
        relevant_total = retrieved_relevant = retrieved_total = 0
        labels_correct = tokens_total = calls_total = 0
        false_negatives = []
        started = perf_counter()
        for index, fixture in enumerate(fixtures):
            prediction = run(deepcopy(fixture), as_of=fixture['as_of'],
                             context_budget=fixture['context_budget'])
            if not isinstance(prediction, Mapping) or not {'fact_ids', 'label'} <= prediction.keys():
                raise ValueError(f'pipeline {name!r} must return fact_ids and label')
            fact_ids = _unique(prediction['fact_ids'])
            expected = set(fixture.get('expected_fact_ids', []))
            found = expected.intersection(fact_ids)
            relevant_total += len(expected)
            retrieved_relevant += len(found)
            retrieved_total += len(fact_ids)
            missing = sorted(expected - found)
            if missing:
                false_negatives.append(dict(fixture_id=fixture.get('fixture_id', str(index)),
                                            missing_fact_ids=missing))
            labels_correct += int(prediction['label'] == fixture.get('expected_label'))
            tokens = prediction.get('tokens', 0)
            calls = prediction.get('calls', 0)
            if type(tokens) is not int or tokens < 0 or type(calls) is not int or calls < 0:
                raise ValueError('tokens and calls must be non-negative integers')
            tokens_total += tokens
            calls_total += calls
        elapsed = perf_counter() - started
        results[name] = dict(
            evaluation_scope='synthetic_fixtures_only',
            fixture_count=len(fixtures),
            recall=(retrieved_relevant / relevant_total if relevant_total else 1.0),
            precision=(retrieved_relevant / retrieved_total if retrieved_total else 0.0),
            label_accuracy=(labels_correct / len(fixtures) if fixtures else 1.0),
            latency_seconds=elapsed,
            calls=calls_total,
            tokens=tokens_total,
            candidate_false_negative_audit=false_negatives,
        )
    return results
