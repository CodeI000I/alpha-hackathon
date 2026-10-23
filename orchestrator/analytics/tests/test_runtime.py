import contextlib
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from orchestrator.analytics import runtime as runtime_module
from orchestrator.analytics.runtime import AnalyticsSettings, load_analytics_settings
from orchestrator.analytics.__main__ import main
from orchestrator.config import Settings


class RuntimeTests(unittest.TestCase):
    def settings(self, contents='', environment=None):
        with TemporaryDirectory() as directory, patch.dict(os.environ, environment or {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text(contents)
            return load_analytics_settings(path)

    def test_never_uses_backend_database_implicitly(self):
        with self.assertRaisesRegex(ValueError, 'ANALYTICS_DATABASE_URL'):
            self.settings('DATABASE_URL=postgresql://backend/live\n')

    def test_process_environment_overrides_file_and_preserves_explicit_baseline(self):
        result = self.settings('ANALYTICS_DATABASE_URL=postgresql://local/test\nANALYTICS_TOP_K=4\n',
                               {'ANALYTICS_TOP_K': '7', 'EMBEDDING_BACKEND': 'lexical'})
        self.assertEqual(result.top_k, 7)
        self.assertEqual(result.embedding_backend, 'lexical')
        self.assertFalse(result.graphify_enabled)
        self.assertFalse(result.triage_enabled)

    def test_triage_is_opt_in_from_environment(self):
        disabled = self.settings('ANALYTICS_DATABASE_URL=postgresql://local/test\n')
        enabled = self.settings('ANALYTICS_DATABASE_URL=postgresql://local/test\n',
                                {'ANALYTICS_TRIAGE_ENABLED': 'true'})
        self.assertFalse(disabled.triage_enabled)
        self.assertTrue(enabled.triage_enabled)

    def test_runtime_builds_and_closes_router_only_when_enabled_and_writable(self):
        from orchestrator.decision import LLMRoutingDecisionProvider

        config = AnalyticsSettings(database_url='postgresql://local/test', triage_enabled=True,
                                   checkpoints=False)
        model_settings, store, llm, router = object(), Mock(), Mock(), Mock()
        service = Mock()
        created = {}

        def construct_service(*args, **kwargs):
            created['args'], created['kwargs'] = args, kwargs
            return service

        with (patch.object(runtime_module, 'load_analytics_settings', return_value=config),
              patch.object(runtime_module, 'load_settings', return_value=model_settings),
              patch.object(runtime_module, 'PostgresStore', return_value=store),
              patch.object(runtime_module, 'LLMClient', return_value=llm) as llm_factory,
              patch.object(runtime_module, 'HybridRetriever'),
              patch.object(runtime_module, 'KnowledgeService'),
              patch.object(runtime_module, 'AnalyticsService', side_effect=construct_service),
              patch('orchestrator.decision.build_decision_router', return_value=router) as build_router,
              patch('orchestrator.analytics.triage.triage_policy', return_value='triage-v1') as policy):
            with runtime_module.runtime() as actual:
                self.assertIs(actual, service)
            llm_factory.assert_called_once()
            build_router.assert_called_once()
            provider = build_router.call_args.args[1]
            self.assertIsInstance(provider, LLMRoutingDecisionProvider)
            self.assertIs(provider.llm, llm)
            self.assertIs(build_router.call_args.kwargs['store'], store)
            self.assertIs(created['kwargs']['decision_router'], router)
            self.assertEqual(created['kwargs']['triage_version'], 'triage-v1')
            policy.assert_called_once_with(model_settings)
        router.close.assert_called_once_with()

    def test_runtime_default_does_not_build_router(self):
        config = AnalyticsSettings(database_url='postgresql://local/test', checkpoints=False)
        captured = {}

        def construct_service(*args, **kwargs):
            captured.update(kwargs)
            return object()

        with (patch.object(runtime_module, 'load_analytics_settings', return_value=config),
              patch.object(runtime_module, 'load_settings', return_value=object()),
              patch.object(runtime_module, 'PostgresStore'),
              patch.object(runtime_module, 'LLMClient'),
              patch.object(runtime_module, 'HybridRetriever'),
              patch.object(runtime_module, 'KnowledgeService'),
              patch.object(runtime_module, 'AnalyticsService', side_effect=construct_service),
              patch('orchestrator.decision.build_decision_router') as build_router):
            with runtime_module.runtime() as service:
                self.assertIsNotNone(service)
        build_router.assert_not_called()
        self.assertIsNone(captured['decision_router'])
        self.assertIsNone(captured['triage_version'])

    def test_read_only_keeps_triage_identity_without_creating_client_or_router(self):
        config = AnalyticsSettings(database_url='postgresql://local/test', triage_enabled=True,
                                   checkpoints=False)
        model_settings, store, service = object(), Mock(), Mock()
        captured = {}

        def construct_service(*args, **kwargs):
            captured.update(kwargs)
            return service

        with (patch.object(runtime_module, 'load_analytics_settings', return_value=config),
              patch.object(runtime_module, 'load_settings', return_value=model_settings),
              patch.object(runtime_module, 'PostgresStore', return_value=store),
              patch.object(runtime_module, 'LLMClient') as llm_factory,
              patch.object(runtime_module, 'HybridRetriever'),
              patch.object(runtime_module, 'KnowledgeService'),
              patch.object(runtime_module, 'AnalyticsService', side_effect=construct_service),
              patch('orchestrator.decision.build_decision_router') as build_router,
              patch('orchestrator.analytics.triage.triage_policy', return_value='triage-v1') as policy):
            with runtime_module.runtime(read_only=True) as actual:
                self.assertIs(actual, service)
            llm_factory.assert_not_called()
            build_router.assert_not_called()
            policy.assert_called_once_with(model_settings)
        self.assertIsNone(captured['decision_router'])
        self.assertEqual(captured['triage_version'], 'triage-v1')

    def test_real_services_share_triage_policy_identity_with_keyless_read_only(self):
        from orchestrator.analytics.triage import triage_policy

        config = AnalyticsSettings(database_url='postgresql://local/test', triage_enabled=True,
                                   checkpoints=False)
        settings = Settings()
        store, router = Mock(), Mock()
        retriever = SimpleNamespace(version='runtime-test')
        knowledge = object()
        llm = SimpleNamespace(settings=settings, close=Mock())
        services = {}

        with (patch.object(runtime_module, 'load_analytics_settings', return_value=config),
              patch.object(runtime_module, 'load_settings', return_value=settings),
              patch.object(runtime_module, 'PostgresStore', return_value=store),
              patch.object(runtime_module, 'LLMClient', return_value=llm) as llm_factory,
              patch.object(runtime_module, 'HybridRetriever', return_value=retriever),
              patch.object(runtime_module, 'KnowledgeService', return_value=knowledge),
              patch('orchestrator.decision.build_decision_router', return_value=router) as build_router):
            with runtime_module.runtime() as writable:
                services['writable'] = writable
            with runtime_module.runtime(read_only=True) as read_only:
                services['read_only'] = read_only

        self.assertEqual(services['writable'].triage_version, triage_policy(settings))
        self.assertEqual(services['read_only'].triage_version, triage_policy(settings))
        self.assertEqual(services['writable'].policy, services['read_only'].policy)
        self.assertIs(services['writable'].decision_router, router)
        self.assertIsNone(services['read_only'].decision_router)
        llm_factory.assert_called_once()
        build_router.assert_called_once()
        router.close.assert_called_once_with()

    def test_optional_features_require_explicit_assets(self):
        for config, missing in [('EMBEDDING_BACKEND=local', 'EMBEDDING_MODEL_PATH'),
                                ('ANALYTICS_GRAPHIFY_ENABLED=true', 'GRAPHIFY_JSON_PATH')]:
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, missing):
                self.settings('ANALYTICS_DATABASE_URL=postgresql://local/test\n' + config)

    def test_postgres_demo_rejects_remote_or_ambiguous_targets_before_connecting(self):
        targets = ['host=example.com dbname=analytics_test_demo',
                   'host=localhost hostaddr=203.0.113.1 dbname=analytics_test_demo',
                   'host=localhost dbname=production',
                   'host=localhost,example.com dbname=analytics_test_demo',
                   'host=localhost service=external dbname=analytics_test_demo']
        for dsn in targets:
            with self.subTest(dsn=dsn), patch('sys.argv', ['analytics', 'demo', '--postgres-test-dsn', dsn]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
