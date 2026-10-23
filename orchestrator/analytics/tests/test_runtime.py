import contextlib
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from orchestrator.analytics.runtime import load_analytics_settings
from orchestrator.analytics.__main__ import main


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
