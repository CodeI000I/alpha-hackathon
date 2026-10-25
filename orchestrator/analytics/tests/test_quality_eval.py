import unittest

from orchestrator.analytics.quality_eval import evaluate_quality


class QualityEvalTests(unittest.TestCase):
    def test_offline_corpus_runs_real_pipeline_and_rejects_bad_outputs(self):
        report = evaluate_quality()
        self.assertEqual(report['evaluation_scope'], 'synthetic_contract_replay')
        self.assertEqual(report['metrics']['fixture_count'], len(report['cases']))
        self.assertGreaterEqual(len(report['cases']), 12)
        self.assertEqual(report['failures'], [])
        cases = {case['fixture_id']: case for case in report['cases']}
        self.assertEqual(cases['truncated-negative']['label'], 'needs_context')
        self.assertEqual(cases['uncited-chat']['label'], 'invalid_response')
        self.assertEqual(cases['uncited-chat']['replies_saved'], 0)
        self.assertEqual(cases['floating-contract']['issues_published'], 1)
        self.assertEqual(cases['cancelled-event']['assessment_calls'], 0)
        self.assertEqual(report['metrics']['label_accuracy'], 1.0)

    def test_wrong_label_is_reported_instead_of_hiding_a_failure(self):
        report = evaluate_quality([dict(fixture_id='incorrect-expectation',
                                       expected_label='irrelevant')])
        self.assertEqual(report['metrics']['label_accuracy'], 0.0)
        self.assertEqual(report['failures'], ['incorrect-expectation'])

    def test_empty_or_duplicate_corpus_cannot_report_success(self):
        case = dict(fixture_id='duplicate', expected_label='accepted')
        for cases in ([], [case, case]):
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                evaluate_quality(cases)
