// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parseReportChartCatalog } from "../../src/reportCharts";
import { parseReportSeries, parseReportSeriesIndex, reportAssetUrl, type ReportSeriesIndexItem } from "../../src/reportSeries";

const document = { id: "doc", file: "report.pdf", sha256: "a".repeat(64), pages: 1, title: "Report" };
const imageHash = "b".repeat(64);
const catalog = parseReportChartCatalog({
  schema_version: 1,
  documents: [document],
  charts: [{ id: "chart", document_id: "doc", page: 1, title: "Chart", kind: "line", crop: [0, 0, 1, 1], data_status: "labelled_values", x_axis: { label: "Year", kind: "time" }, series: [{ id: "exact", label: "Exact", unit: "%", points: [{ label: "2025", value: 3 }] }], unavailable_series: [{ id: "line-b", label: "Line B", unit: "%" }, { id: "series-unavailable", label: "No values", unit: "%" }], note: "Source note", image: "images/chart.jpg", image_sha256: imageHash }],
});
const indexValue = { schema_version: 1, items: [
  { id: "chart--exact", chart_id: "chart", series_id: "exact", label: "Exact", unit: "%", data_status: "labelled_values", json_file: "series/chart--exact.json", svg_file: "series/chart--exact.svg" },
  { id: "chart--line-b", chart_id: "chart", series_id: "line-b", label: "Line B", unit: "%", data_status: "digitized", json_file: "series/chart--line-b.json", svg_file: "series/chart--line-b.svg" },
  { id: "chart--series-unavailable", chart_id: "chart", series_id: "series-unavailable", label: "No values", unit: "%", data_status: "unavailable", json_file: "series/chart--series-unavailable.json", svg_file: null },
] } as const;

function record(item: ReportSeriesIndexItem, overrides: Record<string, unknown> = {}) {
  const exact = item.data_status === "labelled_values";
  const digitized = item.data_status === "digitized";
  return {
    schema_version: 1, id: item.id, chart_id: item.chart_id, series_id: item.series_id,
    label: item.label, unit: item.unit, data_status: item.data_status, note: "visual estimate",
    x_axis: { label: "Year", kind: "time" },
    source: { document, chart_title: "Chart", page: 1, crop: [0, 0, 1, 1], image: "images/chart.jpg", image_sha256: imageHash },
    exact_points: exact ? [{ label: "2025", value: 3 }] : [],
    points: exact ? [{ x: "2025", value: 3, source_index: 0 }] : digitized ? [{ x: 0.5, value: 4, forecast: true }] : [],
    json_file: item.json_file, svg_file: item.svg_file,
    digitization: digitized ? { image_sha256: imageHash, plot: [1, 2, 99, 100], x_ticks: [{ position: 0.5, label: "2025" }], series: [{ id: item.series_id, mode: "line", y_axis: { min: 0, max: 10 }, estimated_error: 0.5, forecast_from: 0.4, note: "visual estimate", anchors: [[0.5, 0.6]] }] } : null,
    ...overrides,
  };
}

describe("report series runtime validation", () => {
  it("accepts exact, digitized partial, and unavailable rows linked to catalog identities", () => {
    const parsed = parseReportSeriesIndex(indexValue, catalog);
    expect(parsed.items.map((item) => item.id)).toEqual(indexValue.items.map((item) => item.id));
    expect(parsed.items[0].expected_source.image_sha256).toBe(imageHash);
  });

  it("rejects unlisted exact rows and mismatched labels or units", () => {
    const unknown = structuredClone(indexValue);
    unknown.items[0].series_id = "invented";
    unknown.items[0].id = "chart--invented";
    unknown.items[0].json_file = "series/chart--invented.json";
    unknown.items[0].svg_file = "series/chart--invented.svg";
    expect(() => parseReportSeriesIndex(unknown, catalog)).toThrow(/catalog|series/i);

    const wrongLabel = structuredClone(indexValue);
    wrongLabel.items[0].label = "Invented label";
    expect(() => parseReportSeriesIndex(wrongLabel, catalog)).toThrow(/catalog|series/i);

    const wrongUnit = structuredClone(indexValue);
    wrongUnit.items[1].unit = "руб.";
    expect(() => parseReportSeriesIndex(wrongUnit, catalog)).toThrow(/catalog|series/i);
  });

  it("rejects unavailable status for a catalog exact row", () => {
    const invalidStatus = structuredClone(indexValue);
    invalidStatus.items[0].data_status = "unavailable";
    invalidStatus.items[0].svg_file = null;
    expect(() => parseReportSeriesIndex(invalidStatus, catalog)).toThrow(/catalog|series/i);
  });

  it("rejects unsafe paths, mismatched IDs, and non-finite anchors", () => {
    const unsafe = structuredClone(indexValue);
    unsafe.items[0].json_file = "series/../../private.json";
    expect(() => parseReportSeriesIndex(unsafe, catalog)).toThrow(/items\[0\]/);
    expect(() => reportAssetUrl("series/../../x.svg")).toThrow(/путь/);
    const item = parseReportSeriesIndex(indexValue, catalog).items[1];
    expect(() => parseReportSeries({ ...record(item), digitization: { image_sha256: imageHash, plot: [1, 1, 99, 99], x_ticks: [{ position: 0, label: "2025" }], series: [{ id: "line-b", mode: "line", y_axis: { min: 0, max: 10 }, estimated_error: 1, note: "rough", anchors: [[0, Number.NaN]] }] } }, item)).toThrow(/anchors/);
  });

  it("rejects source image, page, and document metadata that does not match the selected chart", () => {
    const item = parseReportSeriesIndex(indexValue, catalog).items[1];
    for (const source of [
      { ...record(item).source, image_sha256: "c".repeat(64) },
      { ...record(item).source, page: 2 },
      { ...record(item).source, document: { ...document, id: "other" } },
    ]) {
      expect(() => parseReportSeries(record(item, { source }), item)).toThrow(/source/i);
    }
  });

  it("preserves per-point forecast flags and normalized x values", () => {
    const item = parseReportSeriesIndex(indexValue, catalog).items[1];
    const value = record(item, { points: [{ x: 0.5, value: 4, forecast: true }] });
    const parsed = parseReportSeries(value, item);
    expect(parsed.points[0]).toEqual({ x: 0.5, value: 4, forecast: true });
    expect(parsed.exact_points).toEqual([]);
    expect(parsed.x_axis).toEqual({ label: "Year", kind: "time" });
    expect(parsed.digitization?.series[0].forecast_from).toBe(0.4);
  });

  it("rejects malformed per-point forecast flags", () => {
    const item = parseReportSeriesIndex(indexValue, catalog).items[1];
    expect(() => parseReportSeries(record(item, { points: [{ x: 0.5, value: 4, forecast: "yes" }] }), item)).toThrow(/points\[0\]/);
  });
});


describe("report series numeric consistency", () => {
  const items = parseReportSeriesIndex(indexValue, catalog).items;

  it("rejects changed catalog labels, exact values, or forecasts", () => {
    const item = items[0];
    for (const exact_points of [
      [{ label: "2025", value: -99999 }],
      [{ label: "2024", value: 3 }],
      [{ label: "2025", value: 3, forecast: true }],
      [],
    ]) expect(() => parseReportSeries(record(item, { exact_points }), item)).toThrow(/exact_points/);
    expect(parseReportSeries(record(item), item).exact_points).toEqual(item.expected_exact_points);
  });

  it("rejects exact graph points that differ from the printed values or source indices", () => {
    const item = items[0];
    for (const points of [
      [{ x: "2025", value: -99999, source_index: 0 }],
      [{ x: "2025", value: 3, source_index: 1 }],
      [{ x: "2025", value: 3 }],
      [{ x: "2025", value: 3, source_index: 0, forecast: true }],
      [{ x: "2024", value: 3, source_index: 0 }],
      [{ x: "2025", value_low: 3, value_high: 3, source_index: 0 }],
      [],
    ]) expect(() => parseReportSeries(record(item, { points }), item)).toThrow(/points|значения/);
    expect(parseReportSeries(record(item), item).points[0].value).toBe(3);
  });

  it("rejects digitized values, normalized x, count, or forecast inconsistent with the profile", () => {
    const item = items[1];
    for (const points of [
      [{ x: 0.5, value: -99999, forecast: true }],
      [{ x: 0.6, value: 4, forecast: true }],
      [{ x: "0.5", value: 4, forecast: true }],
      [{ x: 0.5, value: 4, forecast: false }],
      [{ x: 0.5, value: 4 }],
      [{ x: 0.5, value: 4, forecast: true }, { x: 0.5, value: 4, forecast: true }],
    ]) expect(() => parseReportSeries(record(item, { points }), item)).toThrow(/points|значения/);
    expect(parseReportSeries(record(item), item).points[0].value).toBe(4);
  });

  it("accepts rounding to the export precision and rejects a changed final digit", () => {
    const item = items[1];
    const value = record(item);
    value.digitization!.series[0].anchors = [[0.5, 0.52625]]; // axis0–10 =>4.7375
    value.digitization!.series[0].estimated_error = 0.03;
    expect(parseReportSeries({ ...value, points: [{ x: 0.5, value: 4.738, forecast: true }] }, item).points[0].value).toBe(4.738);
    expect(() => parseReportSeries({ ...value, points: [{ x: 0.5, value: 4.739, forecast: true }] }, item)).toThrow(/points/);
  });

  it("validates signed stacked values and both bounds of range points", () => {
    const item = items[1];
    const profile = {
      image_sha256: imageHash, plot: [1, 2, 99, 100], x_ticks: [{ position: 0.5, label: "2025" }],
      series: [{ id: item.series_id, mode: "stacked", y_axis: { min: -10, max: 10 }, estimated_error: 0.1, note: "segments", anchors: [[0.25, 0.1, 0.3], [0.75, 0.7, 0.9]] }],
    };
    const value = record(item, { digitization: profile, points: [{ x: 0.25, value: 4 }, { x: 0.75, value: -4 }] });
    expect(parseReportSeries(value, item).points.map((point) => point.value)).toEqual([4, -4]);
    expect(() => parseReportSeries({ ...value, points: [{ x: 0.25, value: 4 }, { x: 0.75, value: 4 }] }, item)).toThrow(/points/);
    profile.series[0].mode = "band";
    const range = { ...value, points: [{ x: 0.25, value_low: 4, value_high: 8 }, { x: 0.75, value_low: -8, value_high: -4 }] };
    expect(parseReportSeries(range, item).points[1].value_low).toBe(-8);
    expect(() => parseReportSeries({ ...range, points: [{ x: 0.25, value_low: 8, value_high: 4 }, range.points[1]] }, item)).toThrow(/range|points/);
    expect(() => parseReportSeries({ ...range, points: [{ x: 0.25, value_low: 3, value_high: 8 }, range.points[1]] }, item)).toThrow(/points/);
  });
});


it("parses every saved series artifact against the current catalog and index", () => {
  const root = fileURLToPath(new URL("../../public/report-charts/", import.meta.url));
  const read = (path: string): unknown => JSON.parse(readFileSync(`${root}/${path}`, "utf8"));
  const savedCatalog = parseReportChartCatalog(read("catalog.json"));
  const savedIndex = parseReportSeriesIndex(read("series-index.json"), savedCatalog);
  const files = readdirSync(`${root}/series`).filter((name) => name.endsWith(".json"));
  expect(savedIndex.items.map((item) => item.json_file.slice("series/".length)).sort()).toEqual(files.sort());
  for (const item of savedIndex.items) {
    expect(() => parseReportSeries(read(item.json_file), item), item.id).not.toThrow();
  }
});
