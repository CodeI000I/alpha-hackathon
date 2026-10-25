# Offline report chart annotations

Contract for the extractor and widget demo. Each `*.json` annotation file contains
`documents` and `charts` arrays. Document fields: `id`, `file`, `sha256`, `pages`,
`title`. Chart fields:

- `id`: unique lower-case ASCII slug; `document_id`; `page` (1-based).
- `title`; `kind`: `line`, `bar`, `pie`, `scatter` or `mixed`.
- `crop`: `[left, top, right, bottom]`, fractions of the PDF page (0–1), including
  chart title, axes, legend and source where feasible, excluding adjacent prose.
- `data_status`: `labelled_values` or `image_only`. Use labelled_values only for
  numbers visibly printed on the chart. Never infer unlabelled curve heights.
- `x_axis`: `{label, kind: "time" | "category"}`.
- `series`: `[{id, label, unit, points: [{label, value, forecast?}]}]`.
  Each series keeps its own labels: missing observations are omitted, never zero
  filled. Forecast is per point. Years/dates and source units are kept verbatim.
- `note`: extraction limitations, partial coverage, ambiguous dates or labels.

Every chart is visually checked against the original. For image_only, series is
empty. A chart with only some explicitly labelled points must explain that the
series is partial. Tables and decorative illustrations are outside this chart
catalog. Document records include PDFs without charts so coverage is explicit.

`python scripts/prepare_report_charts.py --input /path/to/reports` validates the
source SHA-256 and generates the checked-in catalog and chart crops in
`frontend/public/report-charts`. Original reports and OCR are not committed.
