export type ReportChartKind = "line" | "bar" | "pie" | "scatter" | "mixed";
export type ReportChartDataStatus = "labelled_values" | "image_only";

export interface ReportChartPoint {
  label: string;
  value: number;
  forecast?: boolean;
}

export interface ReportChartSeries {
  id: string;
  label: string;
  unit: string;
  points: ReportChartPoint[];
}

export interface ReportChartUnavailableSeries {
  id: string;
  label: string;
  unit: string;
}

export interface ReportDocument {
  id: string;
  file: string;
  sha256: string;
  pages: number;
  title: string;
}

export interface ReportChart {
  id: string;
  document_id: string;
  page: number;
  title: string;
  kind: ReportChartKind;
  crop: [number, number, number, number];
  data_status: ReportChartDataStatus;
  x_axis: { label: string; kind: "time" | "category" };
  series: ReportChartSeries[];
  unavailable_series: ReportChartUnavailableSeries[];
  note: string;
  image: string;
  image_sha256?: string;
}

export interface ReportChartCatalog {
  schema_version: 1;
  documents: ReportDocument[];
  charts: ReportChart[];
}

const chartKinds = new Set<ReportChartKind>(["line", "bar", "pie", "scatter", "mixed"]);
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isFiniteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function fail(path: string): never {
  throw new Error(`Некорректный каталог графиков: ${path}`);
}

export function parseReportChartCatalog(value: unknown): ReportChartCatalog {
  if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.documents) || !Array.isArray(value.charts)) {
    return fail("ожидается schema_version 1, documents и charts");
  }

  const documents = value.documents.map((item, index): ReportDocument => {
    const path = `documents[${index}]`;
    if (!isRecord(item) || !isString(item.id) || !isString(item.file) || !isString(item.sha256) || !/^[a-f0-9]{64}$/.test(item.sha256) || !isFiniteNumber(item.pages) || !Number.isInteger(item.pages) || item.pages < 1 || !isString(item.title)) return fail(path);
    return { id: item.id, file: item.file, sha256: item.sha256, pages: item.pages, title: item.title };
  });
  const documentIds = new Set(documents.map((document) => document.id));
  if (documentIds.size !== documents.length) return fail("documents.id должны быть уникальны");

  const chartIds = new Set<string>();
  const charts = value.charts.map((item, index): ReportChart => {
    const path = `charts[${index}]`;
    if (!isRecord(item) || !isString(item.id) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(item.id) || chartIds.has(item.id) || !documentIds.has(String(item.document_id)) || !isFiniteNumber(item.page) || !Number.isInteger(item.page) || item.page < 1 || !isString(item.title) || !chartKinds.has(item.kind as ReportChartKind)) return fail(path);
    chartIds.add(item.id);
    const document = documents.find((entry) => entry.id === item.document_id);
    if (!document || item.page > document.pages) return fail(`${path}.page`);
    if (!Array.isArray(item.crop) || item.crop.length !== 4 || !item.crop.every((part) => isFiniteNumber(part) && part >= 0 && part <= 1) || item.crop[0] >= item.crop[2] || item.crop[1] >= item.crop[3]) return fail(`${path}.crop`);
    if (item.data_status !== "labelled_values" && item.data_status !== "image_only") return fail(`${path}.data_status`);
    if (!isRecord(item.x_axis) || !isString(item.x_axis.label) || (item.x_axis.kind !== "time" && item.x_axis.kind !== "category")) return fail(`${path}.x_axis`);
    if (!Array.isArray(item.series) || !isString(item.note)) return fail(path);

    const seriesIds = new Set<string>();
    const series = item.series.map((entry, seriesIndex): ReportChartSeries => {
      if (!isRecord(entry) || !isString(entry.id) || !entry.id.trim() || seriesIds.has(entry.id) || !isString(entry.label) || !isString(entry.unit) || !Array.isArray(entry.points) || entry.points.length === 0) return fail(`${path}.series[${seriesIndex}]`);
      seriesIds.add(entry.id);
      const points = entry.points.map((point, pointIndex): ReportChartPoint => {
        if (!isRecord(point) || !isString(point.label) || !isFiniteNumber(point.value) || (point.forecast !== undefined && typeof point.forecast !== "boolean")) return fail(`${path}.series[${seriesIndex}].points[${pointIndex}]`);
        return point.forecast === undefined
          ? { label: point.label, value: point.value }
          : { label: point.label, value: point.value, forecast: point.forecast };
      });
      return { id: entry.id, label: entry.label, unit: entry.unit, points };
    });
    const unavailableSeries = item.unavailable_series === undefined ? [] : item.unavailable_series;
    if (!Array.isArray(unavailableSeries)) return fail(`${path}.unavailable_series`);
    const unavailableIds = new Set<string>();
    const parsedUnavailable = unavailableSeries.map((entry, unavailableIndex): ReportChartUnavailableSeries => {
      if (!isRecord(entry) || !isString(entry.id) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(entry.id) || seriesIds.has(entry.id) || unavailableIds.has(entry.id) || !isString(entry.label) || !isString(entry.unit)) return fail(`${path}.unavailable_series[${unavailableIndex}]`);
      unavailableIds.add(entry.id);
      return { id: entry.id, label: entry.label, unit: entry.unit };
    });
    if (item.data_status === "image_only" && series.length) return fail(`${path}.image_only требует пустой series`);
    if (item.data_status === "labelled_values" && !series.length) return fail(`${path}.labelled_values требует series`);
    if (!isString(item.image) || item.image !== `images/${item.id}.jpg`) return fail(`${path}.image`);
    if (item.image_sha256 !== undefined && (!isString(item.image_sha256) || !/^[a-f0-9]{64}$/.test(item.image_sha256))) return fail(`${path}.image_sha256`);

    return {
      id: item.id,
      document_id: String(item.document_id),
      page: item.page,
      title: item.title,
      kind: item.kind as ReportChartKind,
      crop: item.crop as ReportChart["crop"],
      data_status: item.data_status,
      x_axis: { label: item.x_axis.label, kind: item.x_axis.kind },
      series,
      unavailable_series: parsedUnavailable,
      note: item.note,
      image: item.image,
      ...(item.image_sha256 !== undefined ? { image_sha256: item.image_sha256 as string } : {}),
    };
  });

  return { schema_version: 1, documents, charts };
}
