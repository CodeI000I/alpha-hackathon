import type { ReportChartCatalog, ReportChartPoint } from "./reportCharts";

export type SeriesStatus = "labelled_values" | "digitized" | "unavailable";
export interface ReportSeriesIndexItem {
  id: string;
  chart_id: string;
  series_id: string;
  label: string;
  unit: string;
  data_status: SeriesStatus;
  json_file: string;
  svg_file: string | null;
  expected_source: SeriesSourceMetadata;
  expected_exact_points: ReportChartPoint[];
}
export interface SeriesSourceMetadata {
  document: { id: string; file: string; sha256: string; pages: number; title: string };
  chart_title: string;
  page: number;
  crop: [number, number, number, number];
  image: string;
  image_sha256?: string;
}
export interface ReportSeriesIndex {
  schema_version: 1;
  items: ReportSeriesIndexItem[];
}
export interface SeriesPoint {
  x: string | number;
  value?: number;
  value_low?: number;
  value_high?: number;
  source_index?: number;
  forecast?: boolean;
}
export interface DigitizationEntry {
  id: string;
  mode: "line" | "bar" | "scatter" | "stacked" | "band" | "unreadable";
  anchors?: number[][];
  y_axis?: { min: number; max: number };
  estimated_error?: number;
  forecast_from?: number;
  note: string;
}
export interface SeriesRecord {
  schema_version: 1;
  id: string;
  chart_id: string;
  series_id: string;
  label: string;
  unit: string;
  data_status: SeriesStatus;
  note: string;
  x_axis: { label: string; kind: "time" | "category" };
  source: SeriesSourceMetadata;
  exact_points: Array<{ label: string; value: number; forecast?: boolean }>;
  points: SeriesPoint[];
  json_file: string;
  svg_file: string | null;
  digitization: null | {
    image_sha256: string;
    plot: [number, number, number, number];
    x_ticks: Array<{ position: number; label: string }>;
    series: DigitizationEntry[];
  };
}

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const string = (value: unknown): value is string => typeof value === "string";
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const slug = (value: unknown): value is string => typeof value === "string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
function invalid(path: string): never { throw new Error(`Некорректные данные ряда: ${path}`); }
function safeFile(value: unknown, extension: "json" | "svg"): value is string {
  return typeof value === "string" && value.startsWith("series/") && value === value.replace(/\\/g, "/") && !value.split("/").some((part) => part === ".." || part === ".") && new RegExp(`^series/[a-z0-9-]+\\.${extension}$`).test(value);
}

export function parseReportSeriesIndex(value: unknown, catalog: ReportChartCatalog): ReportSeriesIndex {
  if (!object(value) || value.schema_version !== 1 || !Array.isArray(value.items)) return invalid("ожидается schema_version 1 и items");
  const seen = new Set<string>();
  const items = value.items.map((entry, i): ReportSeriesIndexItem => {
    const chart = object(entry) ? catalog.charts.find((candidate) => candidate.id === entry.chart_id) : undefined;
    const document = chart ? catalog.documents.find((candidate) => candidate.id === chart.document_id) : undefined;
    if (!object(entry) || !string(entry.id) || seen.has(entry.id) || !slug(entry.chart_id) || !chart || !document || !slug(entry.series_id) || !string(entry.label) || !string(entry.unit) || !["labelled_values", "digitized", "unavailable"].includes(String(entry.data_status)) || !safeFile(entry.json_file, "json") || (entry.svg_file !== null && !safeFile(entry.svg_file, "svg"))) return invalid(`items[${i}]`);
    if (!slug(entry.id.split("--")[0]) || !slug(entry.id.split("--")[1]) || entry.id !== `${entry.chart_id}--${entry.series_id}`) return invalid(`items[${i}].series_id`);
    if (entry.id !== `${entry.chart_id}--${entry.series_id}` || entry.json_file !== `series/${entry.id}.json` || (entry.svg_file !== null && entry.svg_file !== `series/${entry.id}.svg`)) return invalid(`items[${i}] file/id mismatch`);
    const exact = chart.series.find((series) => series.id === entry.series_id);
    const unavailable = chart.unavailable_series.find((series) => series.id === entry.series_id);
    const matches = (series: { label: string; unit: string } | undefined) => series !== undefined && series.label === entry.label && series.unit === entry.unit;
    if (entry.data_status === "labelled_values" ? !matches(exact) : entry.data_status === "digitized" ? !(matches(exact) || matches(unavailable)) : !matches(unavailable)) return invalid(`items[${i}] catalog series mismatch`);
    seen.add(entry.id);
    return { id: entry.id, chart_id: entry.chart_id, series_id: entry.series_id, label: entry.label, unit: entry.unit, data_status: entry.data_status as SeriesStatus, expected_exact_points: exact?.points ?? [], json_file: entry.json_file, svg_file: entry.svg_file, expected_source: { document, chart_title: chart.title, page: chart.page, crop: chart.crop, image: chart.image, ...(chart.image_sha256 ? { image_sha256: chart.image_sha256 } : {}) } };
  });
  return { schema_version: 1, items };
}

function validatePoints(value: unknown, path: string): SeriesPoint[] {
  if (!Array.isArray(value)) return invalid(path);
  return value.map((entry, i) => {
    if (!object(entry) || !(string(entry.x) || finite(entry.x)) || (entry.value !== undefined && !finite(entry.value)) || (entry.value_low !== undefined && !finite(entry.value_low)) || (entry.value_high !== undefined && !finite(entry.value_high)) || (entry.source_index !== undefined && (!finite(entry.source_index) || !Number.isInteger(entry.source_index))) || (entry.forecast !== undefined && typeof entry.forecast !== "boolean")) return invalid(`${path}[${i}]`);
    if ((entry.value_low === undefined) !== (entry.value_high === undefined) || (finite(entry.value_low) && finite(entry.value_high) && entry.value_low > entry.value_high)) return invalid(`${path}[${i}] range`);
    if (entry.value === undefined && entry.value_low === undefined) return invalid(`${path}[${i}] value`);
    return { x: entry.x, ...(entry.value !== undefined ? { value: entry.value } : {}), ...(entry.value_low !== undefined ? { value_low: entry.value_low as number, value_high: entry.value_high as number } : {}), ...(entry.source_index !== undefined ? { source_index: entry.source_index as number } : {}), ...(entry.forecast !== undefined ? { forecast: entry.forecast as boolean } : {}) };
  });
}

function validateSource(value: unknown, expected: SeriesSourceMetadata): SeriesSourceMetadata {
  if (!object(value) || !object(value.document)) return invalid("source");
  const doc = value.document;
  if (doc.id !== expected.document.id || doc.file !== expected.document.file || doc.sha256 !== expected.document.sha256 || doc.pages !== expected.document.pages || doc.title !== expected.document.title || value.chart_title !== expected.chart_title || value.page !== expected.page || !Array.isArray(value.crop) || value.crop.length !== 4 || !value.crop.every(finite) || value.crop.some((part, i) => part !== expected.crop[i]) || value.image !== expected.image || !string(value.image_sha256) || !/^[a-f0-9]{64}$/.test(value.image_sha256) || (expected.image_sha256 !== undefined && value.image_sha256 !== expected.image_sha256)) return invalid("source does not match catalog");
  return { document: expected.document, chart_title: expected.chart_title, page: expected.page, crop: expected.crop, image: expected.image, image_sha256: value.image_sha256 };
}

export function parseReportSeries(value: unknown, item: ReportSeriesIndexItem): SeriesRecord {
  if (!object(value) || value.schema_version !== 1 || value.id !== item.id || value.chart_id !== item.chart_id || value.series_id !== item.series_id || value.label !== item.label || value.unit !== item.unit || value.data_status !== item.data_status || value.json_file !== item.json_file || value.svg_file !== item.svg_file || !string(value.note) || !Array.isArray(value.exact_points)) return invalid("record identity/shape");
  const source = validateSource(value.source, item.expected_source);
  if (!object(value.x_axis) || !string(value.x_axis.label) || (value.x_axis.kind !== "time" && value.x_axis.kind !== "category")) return invalid("x_axis");
  const xAxis = { label: value.x_axis.label, kind: value.x_axis.kind } as SeriesRecord["x_axis"];
  if (value.exact_points.some((point) => !object(point) || !string(point.label) || !finite(point.value) || (point.forecast !== undefined && typeof point.forecast !== "boolean"))) return invalid("exact_points");
  const exactPoints = value.exact_points.map((point) => ({ label: (point as {label:string}).label, value: (point as {value:number}).value, ...((point as {forecast?:boolean}).forecast !== undefined ? { forecast: (point as {forecast:boolean}).forecast } : {}) }));
  if (exactPoints.length !== item.expected_exact_points.length || exactPoints.some((point, i) => {
    const expected = item.expected_exact_points[i];
    return point.label !== expected.label || point.value !== expected.value || point.forecast !== expected.forecast;
  })) return invalid("exact_points do not match catalog");
  const points = validatePoints(value.points, "points");
  let digitization: SeriesRecord["digitization"] = null;
  if (value.digitization !== null) {
    const profile = value.digitization;
    if (!object(profile) || typeof profile.image_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(profile.image_sha256) || !Array.isArray(profile.plot) || profile.plot.length !== 4 || !profile.plot.every(finite) || profile.plot[0] < 0 || profile.plot[1] < 0 || profile.plot[0] >= profile.plot[2] || profile.plot[1] >= profile.plot[3] || !Array.isArray(profile.x_ticks) || !Array.isArray(profile.series)) return invalid("digitization");
    const xTicks = profile.x_ticks.map((tick, i) => {
      if (!object(tick) || !finite(tick.position) || tick.position < 0 || tick.position > 1 || !string(tick.label)) return invalid(`digitization.x_ticks[${i}]`);
      return { position: tick.position, label: tick.label };
    });
    const series = profile.series.map((entry, i): DigitizationEntry => {
      if (!object(entry) || !slug(entry.id) || !["line", "bar", "scatter", "stacked", "band", "unreadable"].includes(String(entry.mode)) || !string(entry.note)) return invalid(`digitization.series[${i}]`);
      const mode = entry.mode as DigitizationEntry["mode"];
      if (entry.forecast_from !== undefined && (!finite(entry.forecast_from) || entry.forecast_from < 0 || entry.forecast_from > 1)) return invalid(`digitization.series[${i}].forecast_from`);
      if (mode === "unreadable") return { id: entry.id, mode, note: entry.note };
      if (!Array.isArray(entry.anchors) || !entry.anchors.length || !object(entry.y_axis) || !finite(entry.y_axis.min) || !finite(entry.y_axis.max) || entry.y_axis.min >= entry.y_axis.max || !finite(entry.y_axis.max - entry.y_axis.min) || !finite(entry.estimated_error) || entry.estimated_error <= 0) return invalid(`digitization.series[${i}] values`);
      const anchorLength = mode === "stacked" || mode === "band" ? 3 : 2;
      if (!entry.anchors.every((anchor) => Array.isArray(anchor) && anchor.length === anchorLength && anchor.every((n) => finite(n) && n >= 0 && n <= 1))) return invalid(`digitization.series[${i}].anchors`);
      const anchors = entry.anchors as number[][];
      if (anchors.some((anchor, j) => (j > 0 && anchor[0] < anchors[j - 1][0]) || (anchorLength === 3 && anchor[1] > anchor[2]))) return invalid(`digitization.series[${i}].anchors order`);
      const zero = entry.y_axis.max / (entry.y_axis.max - entry.y_axis.min);
      if (mode === "stacked" && anchors.some((anchor) => anchor[1] < zero && zero < anchor[2])) return invalid(`digitization.series[${i}].anchors cross zero`);
      return { id: entry.id, mode, note: entry.note, anchors: entry.anchors as number[][], y_axis: { min: entry.y_axis.min, max: entry.y_axis.max }, estimated_error: entry.estimated_error, ...(entry.forecast_from !== undefined ? { forecast_from: entry.forecast_from as number } : {}) };
    });
    if (series.length !== 1 || series[0].id !== item.series_id || (item.expected_source.image_sha256 && profile.image_sha256 !== item.expected_source.image_sha256)) return invalid("digitization.series identity/source image");
    digitization = { image_sha256: profile.image_sha256, plot: profile.plot as [number, number, number, number], x_ticks: xTicks, series };
  }
  if (item.data_status === "unavailable" && (points.length || item.svg_file !== null)) return invalid("unavailable содержит график");
  if (item.data_status === "digitized" && (!digitization || digitization.series[0]?.mode === "unreadable" || !points.length || item.svg_file === null)) return invalid("digitized требует точки и профиль");
  if (item.data_status === "labelled_values" && (!exactPoints.length || !points.length || item.svg_file === null)) return invalid("labelled_values требует значения и SVG");
  if (item.data_status === "labelled_values") {
    if (points.length !== exactPoints.length || points.some((point, i) => {
      const exact = exactPoints[i];
      return point.x !== exact.label || point.value !== exact.value || point.source_index !== i || point.forecast !== exact.forecast || point.value_low !== undefined;
    })) return invalid("points do not match exact_points");
  }
  if (item.data_status === "digitized") {
    const entry = digitization!.series[0];
    const anchors = entry.anchors!;
    const { min, max } = entry.y_axis!;
    const span = max - min;
    // The exporter rounds values to this precision; allow half of the final decimal place.
    const digits = Math.max(0, 1 - Math.floor(Math.log10(entry.estimated_error!)));
    const rounding = 0.5 * 10 ** -digits;
    const matches = (value: number | undefined, expected: number) => value !== undefined && Math.abs(value - expected) <= rounding + 1e-9 * Math.max(1, Math.abs(expected));
    if (points.length !== anchors.length || points.some((point, i) => {
      const anchor = anchors[i];
      const forecast = entry.forecast_from === undefined ? undefined : anchor[0] >= entry.forecast_from;
      if (typeof point.x !== "number" || point.x !== anchor[0] || point.x < 0 || point.x > 1 || point.forecast !== forecast || point.source_index !== undefined) return true;
      if (entry.mode === "band") return point.value !== undefined || !matches(point.value_low, max - anchor[2] * span) || !matches(point.value_high, max - anchor[1] * span);
      const expected = entry.mode === "stacked"
        ? ((anchor[1] + anchor[2]) / 2 > max / span ? -1 : 1) * (anchor[2] - anchor[1]) * span
        : max - anchor[1] * span;
      return point.value_low !== undefined || !matches(point.value, expected);
    })) return invalid("points do not match digitization profile");
  }
  if (item.svg_file !== null && !safeFile(item.svg_file, "svg")) return invalid("svg_file");
  return { schema_version: 1, id: item.id, chart_id: item.chart_id, series_id: item.series_id, label: item.label, unit: item.unit, data_status: item.data_status, note: value.note, source, x_axis: xAxis, exact_points: exactPoints, points, json_file: item.json_file, svg_file: item.svg_file, digitization };
}

export function reportAssetUrl(path: string): string {
  if (!/^series\/[a-z0-9-]+\.(?:json|svg)$/.test(path) && !/^images\/[a-z0-9-]+\.jpg$/.test(path)) throw new Error("Недопустимый путь файла графика.");
  return `/report-charts/${path}`;
}
