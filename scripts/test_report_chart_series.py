import json
import unittest

from scripts.report_chart_series import build_series_exports


def catalog(chart):
    return {
        "schema_version": 1,
        "documents": [{"id": "doc-one", "title": "Документ <A>", "file": "a.pdf", "sha256": "a" * 64, "pages": 2}],
        "charts": [{
            "id": "chart-one", "document_id": "doc-one", "page": 1, "title": "График & <тест>",
            "kind": "line", "crop": [0.1, 0.1, 0.9, 0.9], "image": "images/chart-one.jpg",
            "image_sha256": "b" * 64, "image_width": 1200, "image_height": 800,
            "data_status": "labelled_values", "x_axis": {"label": "Дата", "kind": "time"}, "note": "Примечание",
            **chart,
        }],
    }


class ReportChartSeriesTests(unittest.TestCase):
    def test_splits_series_and_preserves_exact_points_and_forecasts(self):
        c = catalog({"series": [
            {"id": "known", "label": "Known", "unit": "%", "points": [{"label": "2024", "value": -2, "forecast": False}, {"label": "2025", "value": 3, "forecast": True}]},
            {"id": "second", "label": "Other", "unit": "руб.", "points": [{"label": "Апрель", "value": 12}]},
        ]})
        files = build_series_exports(c)
        self.assertEqual(set(files), {"series/chart-one--known.json", "series/chart-one--known.svg", "series/chart-one--second.json", "series/chart-one--second.svg", "series-index.json"})
        first = json.loads(files["series/chart-one--known.json"])
        self.assertEqual(first["exact_points"], c["charts"][0]["series"][0]["points"])
        self.assertEqual(first["points"][0], {"x": "2024", "value": -2, "source_index": 0, "forecast": False})
        self.assertEqual(first["points"][1]["forecast"], True)
        svg = files["series/chart-one--known.svg"].decode()
        self.assertIn("2024", svg)
        self.assertIn("2025", svg)
        self.assertIn("&amp; &lt;тест&gt;", svg)
        self.assertIn("Прогноз", svg)
        index = json.loads(files["series-index.json"])
        self.assertEqual(len(index["items"]), 2)

    def test_digitization_inverts_y_scales_independently_and_handles_stacked_band(self):
        chart = {
            "series": [
                {"id": "line", "label": "Line", "unit": "USD", "points": [{"label": "exact", "value": 1}]},
                {"id": "stack", "label": "Stack", "unit": "%", "points": [{"label": "exact", "value": 2}]},
                {"id": "band", "label": "Band", "unit": "pp", "points": [{"label": "exact", "value": 3}]},
            ],
            "digitization": {
                "image_sha256": "b" * 64, "plot": [100, 50, 1100, 750],
                "x_ticks": [{"position": 0, "label": "2019"}, {"position": 1, "label": "2025"}],
                "series": [
                    {"id": "line", "mode": "line", "y_axis": {"min": -10, "max": 30}, "anchors": [[0, 0.25], [0.5, 0.75]], "estimated_error": 0.23456, "note": "rough", "forecast_from": 0.5},
                    {"id": "stack", "mode": "stacked", "y_axis": {"min": 0, "max": 100}, "anchors": [[0, 0.2, 0.7]], "estimated_error": 2, "note": "stack"},
                    {"id": "band", "mode": "band", "y_axis": {"min": -5, "max": 5}, "anchors": [[1, 0.2, 0.8]], "estimated_error": 0.2, "note": "band"},
                ],
            },
        }
        files = build_series_exports(catalog(chart))
        line = json.loads(files["series/chart-one--line.json"])
        self.assertEqual(line["points"], [{"x": 0, "value": 20, "forecast": False}, {"x": 0.5, "value": 0, "forecast": True}])
        self.assertEqual(line["exact_points"], chart["series"][0]["points"])
        self.assertEqual(line["data_status"], "digitized")
        self.assertEqual(line["digitization"]["series"][0]["estimated_error"], 0.23456)
        line_svg = files["series/chart-one--line.svg"].decode()
        # y=0 is the top of the plotted image; larger normalized y must render lower.
        self.assertIn('x1="82.0" y1="181.5" x2="506.0" y2="320.5"', line_svg)
        self.assertIn("опорные точки", line_svg)
        self.assertIn('class="title">Приблизительная оцифровка', line_svg)
        self.assertIn('class="grid"', line_svg)
        self.assertIn('>30.0</text>', line_svg)
        self.assertIn("#d87918", line_svg)
        stack = json.loads(files["series/chart-one--stack.json"])
        self.assertEqual(stack["points"], [{"x": 0, "value": 50}])
        band = json.loads(files["series/chart-one--band.json"])
        self.assertEqual(band["points"], [{"x": 1, "value_low": -3, "value_high": 3}])
        self.assertIn("Приблизительная оцифровка", files["series/chart-one--line.svg"].decode())

    def test_digitized_rounding_respects_error_for_values_bands_and_stacks(self):
        entries = [
            {"id": mode, "mode": mode, "y_axis": {"min": 0, "max": 100},
             "anchors": [[0.5, 0.602548]], "estimated_error": 0.04, "note": "measured"}
            for mode in ("line", "scatter", "bar")
        ]
        entries.extend([
            {"id": "band", "mode": "band", "y_axis": {"min": 0, "max": 100},
             "anchors": [[0.5, 0.602548, 0.876548]], "estimated_error": 0.04, "note": "range"},
            {"id": "stacked", "mode": "stacked", "y_axis": {"min": -100, "max": 0},
             "anchors": [[0.5, 0.1, 0.497452]], "estimated_error": 0.04, "note": "negative segment"},
        ])
        c = catalog({"series": [], "unavailable_series": [
            {"id": entry["id"], "label": entry["id"], "unit": "%"} for entry in entries
        ], "digitization": {"image_sha256": "b" * 64, "plot": [1, 1, 20, 20],
                            "x_ticks": [{"position": 0, "label": "a"}], "series": entries}})
        files = build_series_exports(c)
        for mode in ("line", "scatter", "bar"):
            with self.subTest(mode=mode):
                record = json.loads(files[f"series/chart-one--{mode}.json"])
                value = record["points"][0]["value"]
                self.assertEqual(value, 39.745)
                self.assertLess(abs(value - 39.7452), record["digitization"]["series"][0]["estimated_error"])
        self.assertEqual(json.loads(files["series/chart-one--band.json"])["points"],
                         [{"x": 0.5, "value_low": 12.345, "value_high": 39.745}])
        self.assertEqual(json.loads(files["series/chart-one--stacked.json"])["points"],
                         [{"x": 0.5, "value": -39.745}])

    def test_approximate_svg_uses_exported_values_and_preserves_source_anchors(self):
        for mode in ("line", "scatter", "band"):
            with self.subTest(mode=mode):
                anchors = [[0, 0.123456], [1, 0.234567]]
                if mode == "band":
                    anchors = [[0, 0.123456, 0.776544], [1, 0.234567, 0.654321]]
                c = catalog({"series": [], "unavailable_series": [{"id": "known", "label": "Known", "unit": "%"}],
                             "digitization": {"image_sha256": "b" * 64, "plot": [1, 1, 20, 20],
                                              "x_ticks": [{"position": 0, "label": "a"}],
                                              "series": [{"id": "known", "mode": mode, "y_axis": {"min": 0, "max": 1},
                                                          "anchors": anchors, "estimated_error": 0.4, "note": "rough", "forecast_from": 1}]}})
                files = build_series_exports(c)
                record = json.loads(files["series/chart-one--known.json"])
                svg = files["series/chart-one--known.svg"].decode()
                self.assertEqual(record["digitization"]["series"][0]["anchors"], anchors)
                self.assertIn('cx="82.0" cy="145.4"', svg)
                self.assertIn('cx="930.0" cy="175.9" r="4" fill="#d87918"', svg)
                if mode == "band":
                    self.assertEqual(record["points"][0], {"x": 0, "value_low": 0.22, "value_high": 0.88, "forecast": False})
                    self.assertIn('d="M82.0,145.4 L930.0,175.9 L930.0,292.7 L82.0,328.8 Z"', svg)
                else:
                    self.assertEqual(record["points"][0], {"x": 0, "value": 0.88, "forecast": False})
                    if mode == "line":
                        self.assertIn('x1="82.0" y1="145.4" x2="930.0" y2="175.9"', svg)

    def test_stacked_segments_preserve_sign_and_svg_bars_are_vertical(self):
        chart = {
            "series": [
                {"id": "stack", "label": "Stack", "unit": "млрд", "points": [{"label": "exact", "value": 1}]},
                {"id": "bars", "label": "Bars", "unit": "%", "points": [{"label": "exact", "value": 1}]},
            ],
            "digitization": {
                "image_sha256": "b" * 64, "plot": [100, 50, 1100, 750],
                "x_ticks": [{"position": 0, "label": "2024"}, {"position": 1, "label": "2025"}],
                "series": [
                    {"id": "stack", "mode": "stacked", "y_axis": {"min": -10, "max": 10}, "anchors": [[0.25, 0.1, 0.3], [0.75, 0.7, 0.9]], "estimated_error": 1, "note": "positive and negative bands"},
                    {"id": "bars", "mode": "bar", "y_axis": {"min": 0, "max": 100}, "anchors": [[0.25, 0.25], [0.75, 0.75]], "estimated_error": 2, "note": "vertical columns"},
                ],
            },
        }
        files = build_series_exports(catalog(chart))
        stack = json.loads(files["series/chart-one--stack.json"])
        self.assertEqual(stack["points"], [{"x": 0.25, "value": 4}, {"x": 0.75, "value": -4}])
        stack_svg = files["series/chart-one--stack.svg"].decode()
        self.assertIn('class="approx-bar"', stack_svg)
        self.assertIn('class="approx-bar" x="280.0" y="195.4" width="28.0" height="55.6"', stack_svg)
        self.assertIn('class="approx-bar" x="704.0" y="251.0" width="28.0" height="55.6"', stack_svg)
        bars = json.loads(files["series/chart-one--bars.json"])
        self.assertEqual(bars["points"], [{"x": 0.25, "value": 75}, {"x": 0.75, "value": 25}])
        bars_svg = files["series/chart-one--bars.svg"].decode()
        self.assertIn('class="approx-bar"', bars_svg)
        self.assertIn('class="approx-bar" x="280.0"', bars_svg)

    def test_line_svg_grid_matches_nonzero_source_axis(self):
        chart = {"series": [{"id": "line", "label": "Line", "unit": "pp", "points": [{"label": "a", "value": 100}]}],
                 "digitization": {"image_sha256": "b" * 64, "plot": [1, 1, 20, 20],
                                  "x_ticks": [{"position": 0, "label": "a"}, {"position": 1, "label": "b"}],
                                  "series": [{"id": "line", "mode": "line", "y_axis": {"min": 90, "max": 120},
                                              "anchors": [[0, 0.25], [1, 0.75]], "estimated_error": 1, "note": "source scale"}]}}
        svg = build_series_exports(catalog(chart))["series/chart-one--line.svg"].decode()
        self.assertIn('x1="82" y1="112.0" x2="930" y2="112.0"', svg)
        self.assertIn('x="72" y="116.0" text-anchor="end" class="label">120.0</text>', svg)
        self.assertIn('x="72" y="394.0" text-anchor="end" class="label">90.0</text>', svg)
        self.assertIn('x1="82.0" y1="181.5" x2="930.0" y2="320.5"', svg)

    def test_stacked_segment_crossing_zero_is_rejected(self):
        c = catalog({"series": [{"id": "stack", "label": "Stack", "unit": "x", "points": [{"label": "a", "value": 1}]}], "digitization": {
            "image_sha256": "b" * 64, "plot": [1, 1, 20, 20], "x_ticks": [{"position": 0, "label": "a"}],
            "series": [{"id": "stack", "mode": "stacked", "y_axis": {"min": -10, "max": 10}, "anchors": [[0.5, 0.4, 0.6]], "estimated_error": 0.1, "note": "crosses zero"}],
        }})
        with self.assertRaises(ValueError):
            build_series_exports(c)

    def test_long_title_wraps_visibly_and_remains_in_svg_accessible_title(self):
        c = catalog({"series": [{"id": "known", "label": "Known", "unit": "x", "points": [{"label": "a", "value": 1}]}]})
        c["charts"][0]["title"] = "Очень длинный заголовок графика о ставках, доходности, объёмах торгов и прогнозных значениях по годам"
        svg = build_series_exports(c)["series/chart-one--known.svg"].decode()
        self.assertEqual(svg.count('class="title"'), 2)
        self.assertIn("Очень длинный заголовок графика о ставках, доходности, объёмах торгов и прогнозных значениях по годам — Known", svg)

    def test_stale_hash_bad_ids_and_bad_profiles_are_rejected(self):
        c = catalog({"series": [{"id": "known", "label": "Known", "unit": "x", "points": [{"label": "a", "value": 1}]}], "unavailable_series": [{"id": "missing", "label": "Missing", "unit": "x"}], "digitization": {
            "image_sha256": "c" * 64, "plot": [1, 1, 20, 20], "x_ticks": [{"position": 0, "label": "a"}],
            "series": [{"id": "known", "mode": "line", "y_axis": {"min": 0, "max": 1}, "anchors": [[0.5, 0.5]], "estimated_error": 0.1, "note": "x"}],
        }})
        with self.assertRaises(ValueError):
            build_series_exports(c)
        c["charts"][0]["digitization"]["image_sha256"] = "b" * 64
        c["charts"][0]["digitization"]["series"][0]["id"] = "../bad"
        with self.assertRaises(ValueError):
            build_series_exports(c)
        c["charts"][0]["digitization"]["series"][0]["id"] = "unknown"
        with self.assertRaises(ValueError):
            build_series_exports(c)

    def test_axis_span_and_normalized_anchor_bounds_are_validated(self):
        c = catalog({"series": [{"id": "known", "label": "Known", "unit": "x", "points": [{"label": "a", "value": 1}]}], "digitization": {
            "image_sha256": "b" * 64, "plot": [1, 1, 20, 20], "x_ticks": [{"position": 0, "label": "a"}],
            "series": [{"id": "known", "mode": "line", "y_axis": {"min": 0, "max": 1}, "anchors": [[0.5, 0.5]], "estimated_error": 0.1, "note": "x"}],
        }})
        profile = c["charts"][0]["digitization"]["series"][0]
        profile["y_axis"] = {"min": -1e308, "max": 1e308}
        with self.assertRaises(ValueError):
            build_series_exports(c)
        profile["y_axis"] = {"min": 0, "max": 1}
        profile["anchors"] = [[1.01, 0.5]]
        with self.assertRaises(ValueError):
            build_series_exports(c)

    def test_unavailable_series_has_no_svg_and_source_metadata(self):
        c = catalog({"series": [], "unavailable_series": [{"id": "not-read", "label": "Not read", "unit": "%"}]})
        files = build_series_exports(c)
        item = json.loads(files["series/chart-one--not-read.json"])
        self.assertEqual(item["data_status"], "unavailable")
        self.assertIsNone(item["svg_file"])
        self.assertEqual(item["source"]["document"]["title"], "Документ <A>")
        self.assertIsNone(item["digitization"])
        self.assertNotIn("series/chart-one--not-read.svg", files)


if __name__ == "__main__":
    unittest.main()
