"""Offline regression checks for PDF chart exports; no source reports required."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_report_charts import prepare, validate_catalog, verify_export


class ReportChartTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            'schema_version': 1,
            'documents': [{'id': 'report', 'file': 'report.pdf', 'sha256': 'a'*64, 'pages': 1, 'title': 'Report'}],
            'charts': [{'id': 'chart', 'document_id': 'report', 'page': 1, 'title': 'Forecast',
                        'kind': 'bar', 'crop': [0.1, 0.2, 0.9, 0.8], 'data_status': 'labelled_values',
                        'x_axis': {'label': 'Month', 'kind': 'time'}, 'note': '',
                        'series': [{'id': 'rate', 'label': 'Rate', 'unit': '%',
                                    'points': [{'label': 'дек.27', 'value': -1.25, 'forecast': True}]}]}],
        }

    def test_rejects_unsafe_or_inconsistent_annotations(self):
        variants = [
            ('id', '../escape'), ('page', 1.5), ('page', True),
            ('crop', [0.8, 0, 0.1, 1]), ('crop', [0, 0, 1, float('nan')]),
            ('data_status', 'image_only'), ('series', []),
        ]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(self.catalog)
                bad['charts'][0][field] = value
                with self.assertRaises(ValueError):
                    validate_catalog(bad)
        bad = copy.deepcopy(self.catalog)
        bad['documents'][0]['file'] = '../report.pdf'
        with self.assertRaises(ValueError):
            validate_catalog(bad)

    def test_rejects_nonfinite_values_and_duplicate_series(self):
        for value in (float('inf'), float('nan'), True, 10**400):
            with self.subTest(value=value):
                bad = copy.deepcopy(self.catalog)
                bad['charts'][0]['series'][0]['points'][0]['value'] = value
                with self.assertRaises(ValueError):
                    validate_catalog(bad)
        bad = copy.deepcopy(self.catalog)
        bad['charts'][0]['series'] *= 2
        with self.assertRaises(ValueError):
            validate_catalog(bad)

    def test_export_checks_source_hash_and_preserves_points(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'reports'
            source.mkdir()
            doc = pymupdf.open()
            page = doc.new_page(width=200, height=100)
            page.draw_rect(pymupdf.Rect(20, 20, 180, 80), color=(1, 0, 0))
            doc.save(source / 'report.pdf')
            doc.close()
            self.catalog['documents'][0]['sha256'] = hashlib.sha256((source / 'report.pdf').read_bytes()).hexdigest()
            output = root / 'export'
            prepare(source, output, self.catalog)
            verify_export(output, self.catalog)
            exported = json.loads((output / 'catalog.json').read_text())
            self.assertEqual(exported['charts'][0]['series'], self.catalog['charts'][0]['series'])
            self.assertTrue((output / 'images/chart.jpg').read_bytes().startswith(b'\xff\xd8'))
            self.assertIn('дек.27', (output / 'points.csv').read_text())
            series_path = output / 'series/chart--rate.json'
            record = json.loads(series_path.read_text())
            self.assertEqual(record['exact_points'], self.catalog['charts'][0]['series'][0]['points'])
            self.assertEqual(record['source']['document']['sha256'], self.catalog['documents'][0]['sha256'])
            original = series_path.read_bytes()
            series_path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'series/chart--rate.json'):
                verify_export(output, self.catalog)
            series_path.write_bytes(original)
            svg_path = output / 'series/chart--rate.svg'
            svg = svg_path.read_bytes()
            svg_path.unlink()
            with self.assertRaisesRegex(ValueError, 'series/chart--rate.svg'):
                verify_export(output, self.catalog)
            svg_path.write_bytes(svg)
            stale = output / 'series/chart--obsolete.json'
            stale.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'unexpected series'):
                verify_export(output, self.catalog)
            prepare(source, output, self.catalog)
            self.assertFalse(stale.exists())
            verify_export(output, self.catalog)
            snapshot = (output / 'catalog.json').read_bytes()
            (source / 'report.pdf').write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                prepare(source, output, self.catalog)
            self.assertEqual((output / 'catalog.json').read_bytes(), snapshot)
            (output / 'images/chart.jpg').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'image'):
                verify_export(output, self.catalog)


if __name__ == '__main__':
    unittest.main()
