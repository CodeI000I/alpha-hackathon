import json
import unittest

from langgraph.graph import END, START, StateGraph

from orchestrator.observability import GraphTrace, log_event


class ObservabilityTests(unittest.TestCase):
    def graph(self, fail=False):
        def assess(state):
            log_event('llm_structured', stage='decision', schema='ImpactAssessment',
                      cache_hit=False, validation_outcome='valid', duration_ms=1,
                      prompt=state['secret'], api_key='secret-key')
            if fail:
                raise ValueError('secret customer document')
            return {'secret': state['secret'], 'route': 'needs_context'}

        builder = StateGraph(dict)
        builder.add_node('assess', assess)
        builder.add_edge(START, 'assess')
        builder.add_edge('assess', END)
        return builder.compile()

    def test_real_graph_correlates_nodes_and_model_without_content(self):
        trace = GraphTrace('opaque-run', 'policy-v2')
        with self.assertLogs('orchestrator.quality', level='INFO') as logs:
            self.graph().invoke({'secret': 'secret customer document'}, config={
                'callbacks': [trace], 'metadata': {'analytics_run_id': 'opaque-run', 'model_policy': 'policy-v2'}})
        records = [json.loads(record.getMessage()) for record in logs.records]
        self.assertEqual([record['event'] for record in records], ['llm_structured', 'graph_node'])
        for record in records:
            self.assertEqual(record['run_id'], 'opaque-run')
            self.assertEqual(record['node'], 'assess')
            self.assertEqual(record['policy'], 'policy-v2')
            self.assertNotIn('secret', json.dumps(record))
        self.assertEqual(records[-1]['outcome'], 'ok')
        self.assertEqual(records[-1]['route'], 'needs_context')
        self.assertIsNone(trace.failed_node)

    def test_failed_node_does_not_log_exception_text(self):
        trace = GraphTrace('opaque-run', 'policy-v2')
        with self.assertLogs('orchestrator.quality', level='INFO') as logs:
            with self.assertRaisesRegex(ValueError, 'secret customer document'):
                self.graph(fail=True).invoke({'secret': 'secret customer document'},
                                            config={'callbacks': [trace]})
        records = [json.loads(record.getMessage()) for record in logs.records]
        self.assertEqual(records[-1]['outcome'], 'error')
        self.assertEqual(records[-1]['error_code'], 'ValueError')
        self.assertEqual(trace.failed_node, 'assess')
        self.assertNotIn('secret', json.dumps(records))

    def test_standalone_model_event_filters_unknown_fields(self):
        with self.assertLogs('orchestrator.quality', level='INFO') as logs:
            log_event('llm_structured', stage='chat', cache_hit=True, response='secret',
                      validation_outcome='invalid', error_code='invalid_response')
        value = json.loads(logs.records[0].getMessage())
        self.assertNotIn('response', value)
        self.assertNotIn('run_id', value)
        self.assertTrue(value['cache_hit'])


if __name__ == '__main__':
    unittest.main()
