import unittest
from datetime import datetime, timedelta, timezone

from orchestrator.models import Claim
from orchestrator.analytics.models import (
    CandidatePath, CompanyFact, CompanyImpact, Event, EvidencePack,
    ImpactAssessment, IssueSynthesis, NewsArticle, SnapshotSynthesis,
    SourceChunk,
)
from orchestrator.analytics.synthesis import (
    issue_identity, route_assessment, semantic_fingerprint, snapshot_fingerprint, synthesize_issue,
    synthesize_snapshot, validate_assessment, validate_claims,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def make_impact(*, event_id='event-1', impact_id=None, summary='Цена логистики может вырасти.',
                exposure='поставка стали', fact_exposure='поставка стали',
                factors=None, urgency='soon', risk='yes', opportunity='no',
                effective_until=None, event_status='active', valid_until=None):
    event = Event(
        event_id=event_id, event_type='cost_change', action='увеличение стоимости',
        subject='доставка стали', summary='Поставщик меняет условия перевозки',
        modality='announcement', status=event_status, evidence_quote='Изменятся тарифы',
        affected_factors=factors or ['procurement_cost'],
        effective_until=effective_until,
    )
    fact = CompanyFact(
        fact_id=f'fact-{event_id}', text='Компания закупает сталь', subject_id='company-1',
        predicate='buys', object_id='steel', business_factors=['procurement_cost'],
        exposure=fact_exposure, valid_until=valid_until, source_refs=['chunk-1'],
        source_quote='Компания закупает сталь', verification_status='source_supported',
    )
    pack = EvidencePack(
        tenant_id='tenant-1', company_id='company-1', event=event, as_of=NOW,
        company_knowledge_revision=2,
        news=[NewsArticle(news_id=event_id, title=event.summary, content=event.evidence_quote,
                          published_at=NOW, received_at=NOW)],
        company_facts=[fact],
        chunks=[SourceChunk(chunk_id='chunk-1', document_id='doc-1', document_revision=1,
                            text='Компания закупает сталь', locator='page=1', start=0, end=24,
                            text_hash='hash-1')],
        candidate_paths=[CandidatePath(path_id='path-1', node_ids=['company-1', 'steel'],
                                       relation_types=['buys'], evidence_refs=['chunk-1'])],
    )
    # A supporting claim uses only references exposed by this evidence pack.
    assessment = ImpactAssessment(
        relevance='relevant', evidence_sufficiency='sufficient', link_type='direct',
        risk_supported=risk, opportunity_supported=opportunity, impact_magnitude='medium',
        urgency=urgency, impact_horizon='short', business_factors=factors or ['procurement_cost'],
        supporting_fact_ids=[fact.fact_id], supporting_path_ids=['path-1'], missing_factors=[],
        summary=summary, causal_chain=[Claim(text='Рост тарифа повышает стоимость поставки.',
                                              evidence_ids=[fact.fact_id, 'path-1', pack.news[0].evidence_id])],
        conditions=[], suggested_action='Проверить условия ближайшей поставки.', exposure=exposure,
    )
    return CompanyImpact(
        impact_id=impact_id or f'impact-{event_id}', event_id=event_id, event_revision=1,
        company_knowledge_revision=2, assessment=assessment, evidence=pack, route='accepted',
        policy_version='policy-v1', generated_at=NOW,
    )


class FakeLLM:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def structured(self, stage, instruction, context, schema, validate=None):
        self.calls.append((stage, instruction, context, schema))
        result = self.output if isinstance(self.output, schema) else schema.model_validate(self.output)
        if validate:
            validate(result)
        return result


class SynthesisTests(unittest.TestCase):
    def test_path_chunk_cannot_bypass_invalid_supporting_fact(self):
        for changes, expected in (
            ({'status': 'conflicting'}, 'inconsistent'),
            ({'verification_status': 'unverified'}, 'needs_context'),
            ({'valid_until': NOW - timedelta(days=1)}, 'needs_context'),
        ):
            with self.subTest(changes=changes):
                impact = make_impact()
                impact.evidence.company_facts[0] = impact.evidence.company_facts[0].model_copy(update=changes)
                impact.assessment.supporting_fact_ids = []
                impact.assessment.causal_chain = [Claim(text='Связь через документ.', evidence_ids=[
                    impact.evidence.news[0].evidence_id, 'path-1'])]
                self.assertEqual(route_assessment(impact.assessment, impact.evidence), expected)

    def test_relevant_impact_needs_news_and_selected_company_causal_citations(self):
        impact = make_impact()
        news_id = impact.evidence.news[0].evidence_id
        for ids in ([], [news_id], ['fact-event-1'], ['chunk-1'], ['path-1']):
            with self.subTest(citations=ids):
                assessment = impact.assessment.model_copy(update={
                    'causal_chain': [Claim(text='Вывод', evidence_ids=ids)] if ids else []})
                self.assertEqual(route_assessment(assessment, impact.evidence), 'needs_context')

    def test_causal_citations_resolve_selected_fact_chunks_and_paths(self):
        impact = make_impact()
        news_id = impact.evidence.news[0].evidence_id
        for company_id in ('fact-event-1', 'chunk-1', 'path-1'):
            with self.subTest(company_id=company_id):
                assessment = impact.assessment.model_copy(update={
                    'causal_chain': [Claim(text='Вывод', evidence_ids=[news_id, company_id])]})
                self.assertEqual(route_assessment(assessment, impact.evidence), 'accepted')

    def test_unselected_company_evidence_and_news_only_paths_do_not_ground_impact(self):
        impact = make_impact()
        news_id = impact.evidence.news[0].evidence_id
        other = impact.evidence.company_facts[0].model_copy(update={'fact_id': 'other-fact'})
        pack = impact.evidence.model_copy(update={
            'company_facts': [*impact.evidence.company_facts, other],
            'candidate_paths': [CandidatePath(path_id='news-only', node_ids=['supplier'],
                relation_types=['mentions'], evidence_refs=[news_id])]})
        for company_id, paths in (('other-fact', []), ('news-only', ['news-only'])):
            with self.subTest(company_id=company_id):
                assessment = impact.assessment.model_copy(update={
                    'supporting_path_ids': paths,
                    'causal_chain': [Claim(text='Вывод', evidence_ids=[news_id, company_id])]})
                self.assertEqual(route_assessment(assessment, pack), 'needs_context')

    def test_unknown_causal_citation_is_inconsistent(self):
        impact = make_impact()
        assessment = impact.assessment.model_copy(update={
            'causal_chain': [Claim(text='Вывод', evidence_ids=['foreign'])]})
        self.assertEqual(route_assessment(assessment, impact.evidence), 'inconsistent')

    def test_selected_path_can_ground_company_side_without_explicit_fact_selection(self):
        impact = make_impact()
        news_id = impact.evidence.news[0].evidence_id
        for ref in ('chunk-1', 'fact-event-1'):
            with self.subTest(path_reference=ref):
                pack = impact.evidence.model_copy(update={'candidate_paths': [CandidatePath(
                    path_id='path-1', node_ids=['company-1', 'steel'],
                    relation_types=['buys'], evidence_refs=[ref])]})
                assessment = impact.assessment.model_copy(update={
                    'supporting_fact_ids': [],
                    'causal_chain': [Claim(text='Вывод', evidence_ids=[news_id, 'path-1'])]})
                self.assertEqual(route_assessment(assessment, pack), 'accepted')
                if ref == 'fact-event-1':
                    pack.company_facts = [pack.company_facts[0].model_copy(
                        update={'verification_status': 'unverified'})]
                    self.assertEqual(route_assessment(assessment, pack), 'needs_context')

    def test_truncated_context_cannot_support_negative_conclusion(self):
        impact = make_impact(risk='no', opportunity='no')
        pack = impact.evidence.model_copy(update={'retrieval': {'context_truncated': True}})
        for relevance in ('irrelevant', 'relevant'):
            with self.subTest(relevance=relevance):
                assessment = impact.assessment.model_copy(update={'relevance': relevance})
                self.assertEqual(route_assessment(assessment, pack), 'needs_context')
                self.assertEqual(route_assessment(assessment, impact.evidence),
                                 'irrelevant' if relevance == 'irrelevant' else 'accepted')

    def test_assessment_references_and_logic_are_checked(self):
        impact = make_impact()
        validate_assessment(impact.assessment, impact.evidence)
        self.assertEqual(route_assessment(impact.assessment, impact.evidence), 'accepted')

        bad = impact.assessment.model_copy(update={'supporting_fact_ids': ['missing-fact']})
        with self.assertRaises(ValueError):
            validate_assessment(bad, impact.evidence)
        self.assertEqual(route_assessment(bad, impact.evidence), 'inconsistent')

        unknown = impact.assessment.model_copy(update={'relevance': 'unknown'})
        self.assertEqual(route_assessment(unknown, impact.evidence), 'needs_context')

    def test_cancelled_event_and_expired_support_do_not_route_as_accepted(self):
        cancelled = make_impact(event_status='cancelled')
        self.assertEqual(route_assessment(cancelled.assessment, cancelled.evidence), 'inconsistent')

        expired = make_impact(valid_until=NOW - timedelta(seconds=1))
        self.assertEqual(route_assessment(expired.assessment, expired.evidence), 'needs_context')

    def test_unverified_hypothesis_and_conflicting_facts_route_conservatively(self):
        impact = make_impact()
        fact = impact.evidence.company_facts[0]
        for update in ({'verification_status': 'unverified'}, {'modality': 'hypothesis'}):
            pack = impact.evidence.model_copy(update={
                'company_facts': [fact.model_copy(update=update)]})
            self.assertEqual(route_assessment(impact.assessment, pack), 'needs_context')
        conflicting = impact.evidence.model_copy(update={
            'company_facts': [fact.model_copy(update={'status': 'conflicting'})]})
        self.assertEqual(route_assessment(impact.assessment, conflicting), 'inconsistent')

    def test_claim_references_are_checked_recursively(self):
        value = {'outer': [Claim(text='known', evidence_ids=['fact-1']),
                           {'nested': {'claims': [Claim(text='bad', evidence_ids=['missing'])]}}]}
        with self.assertRaises(ValueError):
            validate_claims(value, {'fact-1'})
        validate_claims({'claims': [Claim(text='supported', evidence_ids=['fact-1'])]}, {'fact-1'})

    def test_issue_identity_uses_only_supported_exposure(self):
        first = make_impact(event_id='event-a', factors=['logistics', 'procurement_cost'])
        second = make_impact(event_id='event-b', factors=['procurement_cost', 'logistics'])
        self.assertEqual(issue_identity(first), issue_identity(second))

        unsupported = make_impact(event_id='event-a', fact_exposure='different supplier')
        other_event = make_impact(event_id='event-b', fact_exposure='different supplier')
        self.assertNotEqual(issue_identity(unsupported), issue_identity(other_event))
        unverified = make_impact(event_id='event-a')
        unverified.evidence.company_facts[0].verification_status = 'unverified'
        other_unverified = make_impact(event_id='event-b')
        other_unverified.evidence.company_facts[0].verification_status = 'unverified'
        self.assertNotEqual(issue_identity(unverified), issue_identity(other_unverified))

    def test_single_impact_is_deterministic_and_preserves_mixed_effect(self):
        impact = make_impact(risk='yes', opportunity='yes')
        llm = FakeLLM({})
        issue = synthesize_issue(llm, [impact], issue_id='issue-1', company_id='company-1', as_of=NOW)
        self.assertEqual(issue.overall_effect, 'mixed')
        self.assertEqual(issue.event_ids, ['event-1'])
        self.assertEqual(issue.impact_ids, ['impact-event-1'])
        self.assertEqual(issue.urgency, 'soon')
        self.assertEqual(issue.impact_magnitude, 'medium')
        self.assertEqual(llm.calls, [])

    def test_multiple_events_use_one_validated_synthesis_call(self):
        impacts = [make_impact(event_id='event-a', opportunity='yes'),
                   make_impact(event_id='event-b', risk='yes')]
        output = IssueSynthesis(
            title='Изменение условий закупок', summary='На закупки влияют два события.',
            overall_effect='mixed', evidence_sufficiency='conditional', key_unknowns=['цена заказа'],
            conditions=['для ближайшей поставки'], suggested_action='Проверить договоры.',
            claims=[Claim(text='Условия влияют на стоимость.', evidence_ids=['fact-event-a', 'path-1'])],
        )
        llm = FakeLLM(output)
        issue = synthesize_issue(llm, impacts, issue_id='issue-1', company_id='company-1', as_of=NOW)
        self.assertEqual(issue.overall_effect, 'mixed')
        self.assertEqual(issue.event_ids, ['event-a', 'event-b'])
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(llm.calls[0][0], 'analysis')
        self.assertEqual(llm.calls[0][2]['as_of'], NOW.isoformat())

    def test_multi_event_synthesis_cannot_erase_supported_mixed_effect(self):
        impacts = [make_impact(event_id='event-a', opportunity='yes'),
                   make_impact(event_id='event-b', risk='yes')]
        output = IssueSynthesis(
            title='Закупки', summary='Есть риск и возможность.', overall_effect='risk',
            evidence_sufficiency='sufficient', key_unknowns=[], conditions=[],
            suggested_action='Проверить договоры.',
        )
        issue = synthesize_issue(FakeLLM(output), impacts, issue_id='issue-1',
                                 company_id='company-1', as_of=NOW)
        self.assertEqual(issue.overall_effect, 'mixed')

    def test_semantically_unchanged_summary_format_reuses_previous_issue(self):
        impact = make_impact(summary='Цена логистики может вырасти.')
        llm = FakeLLM({})
        previous = synthesize_issue(llm, [impact], issue_id='issue-1', company_id='company-1', as_of=NOW)
        changed_format = make_impact(summary='  Цена логистики может вырасти.\n')

        before = semantic_fingerprint(impact)
        after = semantic_fingerprint(changed_format)
        result = synthesize_issue(llm, [changed_format], issue_id='issue-1', company_id='company-1',
                                  as_of=NOW + timedelta(hours=1), previous=previous)
        self.assertEqual(before, after)
        self.assertEqual(result.version, previous.version)
        self.assertIs(result, previous)
        self.assertEqual(result.as_of, previous.as_of)
        self.assertEqual(len(llm.calls), 0)

    def test_issue_version_changes_when_time_expires_supporting_fact(self):
        impact = make_impact(valid_until=NOW + timedelta(hours=1))
        llm = FakeLLM({})
        previous = synthesize_issue(llm, [impact], issue_id='issue-1', company_id='company-1', as_of=NOW)
        llm.calls.clear()
        updated = synthesize_issue(llm, [impact], issue_id='issue-1', company_id='company-1',
                                   as_of=NOW + timedelta(hours=2), previous=previous)
        self.assertEqual(len(llm.calls), 0)  # A single impact remains deterministic.
        self.assertEqual(updated.version, previous.version + 1)

    def test_snapshot_quiet_single_reuse_and_multi_synthesis(self):
        llm = FakeLLM(SnapshotSynthesis(summary='Несколько изменений требуют внимания.',
                                        key_unknowns=['сроки'], actions=['Проверить условия.']))
        quiet = synthesize_snapshot(llm, [], company_id='company-1', role='owner',
                                    knowledge_revision=2, as_of=NOW,
                                    news_processed_through=NOW, policy_version='policy-v1')
        self.assertEqual(llm.calls, [])
        self.assertIn('существенных', quiet.overall.summary)

        issue = synthesize_issue(FakeLLM({}), [make_impact()], issue_id='issue-1',
                                 company_id='company-1', as_of=NOW)
        one = synthesize_snapshot(llm, [issue], company_id='company-1', role='owner',
                                  knowledge_revision=2, as_of=NOW,
                                  news_processed_through=NOW, policy_version='policy-v1')
        self.assertIn(issue.summary, one.overall.summary)
        self.assertEqual(llm.calls, [])

        second = issue.model_copy(update={'issue_id': 'issue-2', 'version': 1, 'urgency': 'immediate'})
        many = synthesize_snapshot(llm, [issue, second], company_id='company-1', role='owner',
                                   knowledge_revision=2, as_of=NOW,
                                   news_processed_through=NOW, policy_version='policy-v1')
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(llm.calls[0][3], SnapshotSynthesis)
        self.assertEqual(many.priority_issues[0]['issue_id'], 'issue-2')

    def test_snapshot_orders_equal_urgency_by_impact_magnitude(self):
        first = synthesize_issue(FakeLLM({}), [make_impact(event_id='event-a')],
                                 issue_id='issue-a', company_id='company-1', as_of=NOW)
        second = synthesize_issue(FakeLLM({}), [make_impact(event_id='event-b')],
                                  issue_id='issue-b', company_id='company-1', as_of=NOW)
        first.impact_magnitude = 'low'
        second.impact_magnitude = 'high'
        snapshot = synthesize_snapshot(FakeLLM(SnapshotSynthesis(
            summary='Обзор.', key_unknowns=[], actions=[])), [first, second],
            company_id='company-1', role='owner', knowledge_revision=2,
            as_of=NOW, news_processed_through=NOW, policy_version='policy-v1')
        self.assertEqual([item['issue_id'] for item in snapshot.priority_issues],
                         ['issue-b', 'issue-a'])

    def test_snapshot_reuses_unchanged_state_and_changes_are_deterministic(self):
        llm = FakeLLM(SnapshotSynthesis(summary='Обзор.', key_unknowns=[], actions=[]))
        issue = synthesize_issue(FakeLLM({}), [make_impact()], issue_id='issue-1',
                                 company_id='company-1', as_of=NOW)
        previous = synthesize_snapshot(llm, [issue], company_id='company-1', role='owner',
                                       knowledge_revision=2, as_of=NOW,
                                       news_processed_through=NOW, policy_version='policy-v1')
        self.assertEqual(snapshot_fingerprint([issue], company_id='company-1', role='owner',
                                              knowledge_revision=2, policy_version='policy-v1'),
                         snapshot_fingerprint([issue], company_id='company-1', role='owner',
                                              knowledge_revision=2, policy_version='policy-v1'))
        llm.calls.clear()
        reused = synthesize_snapshot(llm, [issue], company_id='company-1', role='owner',
                                     knowledge_revision=2, as_of=NOW + timedelta(hours=1),
                                     news_processed_through=NOW + timedelta(hours=1),
                                     policy_version='policy-v1', previous=previous)
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(reused.snapshot_version, previous.snapshot_version)
        self.assertEqual(reused.overall, previous.overall)

    def test_snapshot_multi_event_reuse_avoids_llm(self):
        llm = FakeLLM(SnapshotSynthesis(summary='Обзор.', key_unknowns=[], actions=[]))
        first = synthesize_issue(FakeLLM({}), [make_impact(event_id='event-a')],
                                 issue_id='issue-a', company_id='company-1', as_of=NOW)
        second = synthesize_issue(FakeLLM({}), [make_impact(event_id='event-b')],
                                  issue_id='issue-b', company_id='company-1', as_of=NOW)
        previous = synthesize_snapshot(llm, [first, second], company_id='company-1', role='owner',
                                       knowledge_revision=2, as_of=NOW, news_processed_through=NOW,
                                       policy_version='policy-v1')
        llm.calls.clear()
        reused = synthesize_snapshot(llm, [first, second], company_id='company-1', role='owner',
                                     knowledge_revision=2, as_of=NOW + timedelta(hours=1),
                                     news_processed_through=NOW + timedelta(hours=1),
                                     policy_version='policy-v1', previous=previous)
        self.assertEqual(llm.calls, [])
        self.assertEqual(reused.snapshot_version, previous.snapshot_version)


if __name__ == '__main__':
    unittest.main()
