import { describe, expect, it } from "vitest";
import { parseReportChartCatalog } from "../../src/reportCharts";

const catalog = {
  schema_version: 1,
  documents: [{ id: "report-1", file: "report.pdf", sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", pages: 2, title: "Отчёт" }],
  charts: [{
    id: "chart-1",
    document_id: "report-1",
    page: 1,
    title: "Выручка",
    kind: "line",
    crop: [0.1, 0.2, 0.8, 0.7],
    data_status: "labelled_values",
    x_axis: { label: "Год", kind: "time" },
    series: [{ id: "series-1", label: "Выручка", unit: "млрд руб.", points: [{ label: "2024", value: 12, forecast: true }] }],
    note: "Прогноз",
    image: "images/chart-1.jpg",
  }],
};

describe("parseReportChartCatalog", () => {
  it("preserves chart labels, units, independent points, and forecast marks", () => {
    const result = parseReportChartCatalog(catalog);
    expect(result.charts[0].series[0].points).toEqual([{ label: "2024", value: 12, forecast: true }]);
    expect(result.charts[0].series[0].unit).toBe("млрд руб.");
  });

  it("rejects image paths outside the chart image directory", () => {
    expect(() => parseReportChartCatalog({
      ...catalog,
      charts: [{ ...catalog.charts[0], image: "../../secret.jpg" }],
    })).toThrow(/image/i);
  });

  it("rejects numerical series on an image-only chart", () => {
    expect(() => parseReportChartCatalog({
      ...catalog,
      charts: [{ ...catalog.charts[0], data_status: "image_only" }],
    })).toThrow(/image_only/i);
  });

  it("rejects fractional document and chart pages and malformed checksums", () => {
    expect(() => parseReportChartCatalog({ ...catalog, documents: [{ ...catalog.documents[0], pages: 2.5 }] })).toThrow(/documents\[0\]/i);
    expect(() => parseReportChartCatalog({ ...catalog, charts: [{ ...catalog.charts[0], page: 1.5 }] })).toThrow(/charts\[0\]/i);
    expect(() => parseReportChartCatalog({ ...catalog, documents: [{ ...catalog.documents[0], sha256: "not-a-checksum" }] })).toThrow(/documents\[0\]/i);
  });

  it("rejects empty or duplicate series identifiers and empty point lists", () => {
    const series = catalog.charts[0].series[0];
    expect(() => parseReportChartCatalog({ ...catalog, charts: [{ ...catalog.charts[0], series: [{ ...series, id: " " }] }] })).toThrow(/series\[0\]/i);
    expect(() => parseReportChartCatalog({ ...catalog, charts: [{ ...catalog.charts[0], series: [series, series] }] })).toThrow(/series\[1\]/i);
    expect(() => parseReportChartCatalog({ ...catalog, charts: [{ ...catalog.charts[0], series: [{ ...series, points: [] }] }] })).toThrow(/series\[0\]/i);
  });

  it("rejects chart identifiers that could escape the image directory", () => {
    expect(() => parseReportChartCatalog({
      ...catalog,
      charts: [{ ...catalog.charts[0], id: "../chart", image: "images/../chart.jpg" }],
    })).toThrow(/charts\[0\]/i);
  });
});
