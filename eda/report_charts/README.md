# Offline report chart annotations

Each JSON file contains `documents` and `charts`. Document fields: `id`, `file`,
`sha256`, `pages`, `title`. The source PDFs are raster pages. Annotations are
reviewed against their images; this is a reproducible curated dataset, not a
universal PDF recognizer.

Chart fields:

- `id`, `document_id`, `page` (1-based), `title`, `kind`.
- `crop`: `[left, top, right, bottom]`, fractions of the PDF page (0–1).
- `data_status`: `labelled_values` or `image_only`, describing printed numbers
  only. This legacy chart-level status does not describe digitization coverage.
- `x_axis`: `{label, kind: "time" | "category"}`.
- `series`: `[{id, label, unit, points: [{label, value, forecast?}]}]` contains
  only numbers printed on the plot. Axis ticks are not observations. Partial
  series retain gaps; rounded percentages are not renormalized.
- `unavailable_series`: `[{id, label, unit}]` inventories series without printed
  values, including series subsequently digitized. IDs cannot duplicate `series`.
- `note`: limitations or ambiguous dates/labels.

## Approximate digitization

`digitization` is optional and contains:

- `image_sha256`: hash of the exact exported JPEG used for measurement. A changed
  crop or renderer requires reviewing the calibration, not just updating its hash.
- `plot`: `[left, top, right, bottom]` in pixels of that JPEG, calibrated to ticks.
- `x_ticks`: `[{position, label}]`, normalized positions (0–1) and source labels.
  These are reference ticks, not dates assigned to every point.
- `series`: one profile per digitized or unreadable series:

```json
{
  "id": "series-id",
  "mode": "line",
  "y_axis": {"min": 90, "max": 120},
  "anchors": [[0.05, 0.3], [0.5, 0.7]],
  "estimated_error": 0.5,
  "note": "Approximate anchors from the raster image."
}
```

Modes: `line`, `scatter`, `bar`, `stacked`, `band`, or `unreadable` with a reason.
Each series has its own Y scale, including right-hand axes. Coordinates are
normalized to `plot`: x increases rightward, y downward. Ordinary anchors are
`[x,y]`, converted by `value = max - y * (max - min)`.

`stacked` and `band` use `[x,top,bottom]`. Bands preserve lower/upper bounds.
Stacked values are segment thicknesses, negative below the zero line; a segment
cannot cross zero. Their individual SVGs draw these values from zero, while
source overlays retain the original stacked positions. Sorting scatter anchors
by x does not imply connecting those points.

Optional `forecast_from` in a profile marks x positions from this threshold as
forecasts. Existing exact per-point flags remain unchanged. Errors are visual
estimates in the series' Y units, not measured confidence intervals or guarantees.
X calibration and interpolation uncertainty are not quantified. Missing or
occluded sections must be disclosed; never invent zero values. Unreadable rows
still get an individual JSON with an explanation and no SVG.

## Generated artifacts

`python scripts/prepare_report_charts.py --input /path/to/reports` verifies every
PDF and produces crops, the legacy exact-value CSV, `catalog.json`,
`series-index.json`, and `series/<chart-id>--<series-id>.json` plus an SVG when
numeric data exists. Approximate Y values use
`round(value, max(0, 1 - floor(log10(estimated_error))))`; the rounding step is
smaller than the stated visual error. SVGs plot these same exported values.
Decimal places do not establish measurement accuracy. Exact points remain verbatim in
`exact_points`, even when a partial series also has approximate points.

`python scripts/prepare_report_charts.py --check` verifies image hashes and
byte-for-byte agreement of all JSON/SVG/CSV exports with the annotations.
`series/` is owned by the generator: stale generated JSON/SVG files are removed
on successful regeneration. Keep original reports and OCR outside the repository.
