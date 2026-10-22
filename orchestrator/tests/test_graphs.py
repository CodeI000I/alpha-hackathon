"""Проверки маршрутов на подставных узлах; внешние сервисы не вызываются."""

import unittest

from orchestrator.graphs import build_graphs


class GraphTests(unittest.TestCase):
    def run_flow(self, flow, decisions, **inputs):
        trace = []

        def node(name):
            def execute(state):
                trace.append(name)
                return decisions.get(name, {})
            return execute

        # Первый вызов только собирает графы, интеграции ещё не исполняются.
        graphs = build_graphs()
        names = set()
        for graph in graphs.values():
            names.update(graph.get_graph().nodes)
        handlers = {name: node(name) for name in names if not name.startswith('__')}
        graphs = build_graphs(handlers)
        result = graphs[flow].invoke(inputs)
        return trace, result

    def test_duplicate_stops_before_scoring(self):
        trace, _ = self.run_flow('event', {
            'validate_event': {'input_decision': 'valid'},
            'deduplicate_event': {'event_decision': 'duplicate'},
        })
        self.assertNotIn('score_relevance', trace)

    def test_report_is_prepared_before_card_publication(self):
        trace, _ = self.run_flow('company', {
            'score_relevance': {'relevance_decision': 'relevant'},
        })
        self.assertIn('save_feed_card', trace)
        self.assertLess(trace.index('enqueue_report'), trace.index('save_feed_card'))

    def test_relevant_company_enqueues_report(self):
        trace, _ = self.run_flow('company', {
            'score_relevance': {'relevance_decision': 'relevant'},
        })
        self.assertIn('enqueue_report', trace)

    def test_new_event_dispatches_company_jobs(self):
        trace, _ = self.run_flow('event', {
            'validate_event': {'input_decision': 'valid'},
            'deduplicate_event': {'event_decision': 'new'},
            'select_companies': {'candidate_decision': 'found'},
        })
        self.assertEqual(trace[-1], 'dispatch_company_jobs')
        self.assertNotIn('score_relevance', trace)

    def test_open_returns_existing_report_or_job(self):
        for decision, expected in [('ready', 'return_report'), ('running', 'return_pending')]:
            with self.subTest(decision=decision):
                trace, _ = self.run_flow('open', {
                    'authorize': {'access_decision': 'allowed'},
                    'inspect_report': {'report_decision': decision},
                })
                self.assertEqual(trace[-1], expected)
                self.assertNotIn('ensure_report_job', trace)

    def test_concurrent_open_uses_existing_job(self):
        trace, _ = self.run_flow('open', {
            'authorize': {'access_decision': 'allowed'},
            'inspect_report': {'report_decision': 'stale'},
            'ensure_report_job': {'job_decision': 'existing'},
        })
        self.assertEqual(trace[-1], 'return_pending')
        self.assertNotIn('ensure_report_job', trace)
        self.assertNotIn('enqueue_report', trace)

    def test_access_denied_stops_before_loading_data(self):
        trace, _ = self.run_flow('chat', {
            'authorize': {'access_decision': 'denied'},
        })
        self.assertEqual(trace, ['authorize', 'return_denied'])

    def test_search_budget_stops_cycle(self):
        trace, result = self.run_flow('report', {
            'assess_evidence': {'evidence_decision': 'search'},
        }, max_searches=1)
        self.assertEqual(trace.count('search_external'), 1)
        self.assertEqual(trace[-1], 'save_insufficient_report')
        self.assertEqual(result['searches_used'], 1)

    def test_revision_budget_stops_cycle(self):
        trace, _ = self.run_flow('report', {
            'assess_evidence': {'evidence_decision': 'enough'},
            'verify_report': {'quality_decision': 'revise'},
        }, max_revisions=1)
        self.assertEqual(trace.count('revise_report'), 1)
        self.assertEqual(trace[-1], 'save_insufficient_report')
        self.assertNotIn('save_report', trace)

    def test_chat_clarification_does_not_search(self):
        trace, _ = self.run_flow('chat', {
            'authorize': {'access_decision': 'allowed'},
            'plan_answer': {'answer_decision': 'clarify'},
        })
        self.assertIn('ask_clarification', trace)
        self.assertNotIn('search_external', trace)

    def test_missing_integration_fails_explicitly(self):
        with self.assertRaises(NotImplementedError):
            build_graphs()['event'].invoke({})

    def test_missing_decision_fails_explicitly(self):
        with self.assertRaises(ValueError):
            self.run_flow('event', {})

    def test_irrelevant_and_uncertain_do_not_create_card(self):
        for decision in ('irrelevant', 'uncertain'):
            with self.subTest(decision=decision):
                trace, _ = self.run_flow('company', {
                    'score_relevance': {'relevance_decision': decision},
                })
                self.assertNotIn('save_feed_card', trace)
                self.assertNotIn('enqueue_report', trace)

    def test_ready_report_does_not_search(self):
        trace, _ = self.run_flow('report', {
            'assess_evidence': {'evidence_decision': 'enough'},
            'verify_report': {'quality_decision': 'valid'},
        })
        self.assertEqual(trace[-1], 'save_report')
        self.assertNotIn('search_external', trace)

    def test_no_implicit_search_budget(self):
        trace, _ = self.run_flow('report', {
            'assess_evidence': {'evidence_decision': 'search'},
        })
        self.assertNotIn('search_external', trace)
        self.assertEqual(trace[-1], 'save_insufficient_report')


if __name__ == '__main__':
    unittest.main()
