import unittest
from unittest.mock import patch

from orchestrator.analytics import prepare_assets


class AssetPreparationTests(unittest.TestCase):
    def test_only_explicit_asset_flags_run_downloaders(self):
        with patch.object(prepare_assets, 'prepare_model') as model, \
             patch.object(prepare_assets, 'prepare_ocr') as ocr:
            self.assertEqual(prepare_assets.main(['--ocr']), 0)
            model.assert_not_called()
            ocr.assert_called_once_with()

    def test_asset_preparation_requires_an_explicit_selection(self):
        with self.assertRaises(SystemExit) as result:
            prepare_assets.main([])
        self.assertEqual(result.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
