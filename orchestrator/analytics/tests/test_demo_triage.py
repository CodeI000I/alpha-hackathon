import unittest

from orchestrator.analytics.demo import run_demo


class DemoTriageTests(unittest.TestCase):
    def test_triage_is_disabled_by_default(self):
        result = run_demo()

        self.assertEqual(result['triage_mode'], 'disabled')
        self.assertEqual(result['triage']['count'], 0)
        self.assertEqual(result['read_calls'], 0)
        self.assertEqual(result['overall_effect'], 'mixed')

    def test_systemone_and_fallback_modes_keep_grounded_outcome_and_report_usage(self):
        for mode, provider, stage in (
            ('systemone', 'systemone', 'systemone'),
            ('fallback', 'llm', 'decision'),
        ):
            with self.subTest(mode=mode):
                result = run_demo(triage_mode=mode)

                self.assertEqual(result['triage_mode'], mode)
                self.assertEqual(result['events'], 3)
                self.assertEqual(result['overall_effect'], 'mixed')
                self.assertEqual(result['read_calls'], 0)
                self.assertEqual(result['triage']['count'], 6)
                self.assertEqual(result['triage']['providers'], {provider: 6})
                metric = next(row for row in result['metrics'] if row['stage'] == stage)
                self.assertGreater(metric['calls'], 0)
                self.assertGreater(metric['prompt_tokens'], 0)
                self.assertGreater(metric['completion_tokens'], 0)


if __name__ == '__main__':
    unittest.main()
