import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ReportSeriesComparison } from "./components/ReportSeriesComparison";
import { parseReportSeriesIndex, type ReportSeriesIndex } from "./reportSeries";
import { parseReportChartCatalog, type ReportChartCatalog } from "./reportCharts";
import "./styles/tokens.css";
import "./styles/base.css";
import "./report-charts.css";

function ReportChartsPreview() {
  const [catalog, setCatalog] = useState<ReportChartCatalog | null>(null);
  const [seriesIndex, setSeriesIndex] = useState<ReportSeriesIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [chartId, setChartId] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all(["/report-charts/catalog.json", "/report-charts/series-index.json"].map(async (url) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
      return response.json() as Promise<unknown>;
    })).then(([catalogRaw, indexRaw]) => {
      const parsedCatalog = parseReportChartCatalog(catalogRaw);
      const parsedIndex = parseReportSeriesIndex(indexRaw, parsedCatalog);
      if (active) {
        setCatalog(parsedCatalog);
        setSeriesIndex(parsedIndex);
        setDocumentId(parsedCatalog.documents[0]?.id ?? "");
      }
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Не удалось загрузить каталог графиков.");
    });
    return () => { active = false; };
  }, []);

  const documents = catalog?.documents ?? [];
  const charts = useMemo(() => catalog?.charts.filter((chart) => chart.document_id === documentId) ?? [], [catalog, documentId]);
  const selectedChart = charts.find((chart) => chart.id === chartId) ?? charts[0];
  const chartSeries = useMemo(() => seriesIndex?.items.filter((item) => item.chart_id === selectedChart?.id) ?? [], [seriesIndex, selectedChart?.id]);

  useEffect(() => {
    if (!charts.some((chart) => chart.id === chartId)) setChartId(charts[0]?.id ?? "");
  }, [charts, chartId]);

  if (error) return <main className="report-preview"><div className="report-preview__state" role="alert"><h1>Не удалось открыть каталог</h1><p>{error}</p><p>Проверьте файлы report-charts/catalog.json и series-index.json.</p></div></main>;
  if (!catalog || !seriesIndex) return <main className="report-preview"><p className="report-preview__state" role="status" aria-busy="true">Загружаем каталог графиков…</p></main>;

  return (
    <main className="report-preview">
      <header className="report-preview__intro">
        <p className="report-preview__eyebrow">Alfa · PDF отчёты</p>
        <h1>Сравнение рядов из отчётов</h1>
        <p>Слева — исходный фрагмент, справа — отдельный ряд со статусом и исходными данными.</p>
      </header>
      <section className="report-preview__controls" aria-label="Выбор отчёта и графика">
        <label>Отчёт
          <select aria-label="Отчёт" value={documentId} onChange={(event) => { setDocumentId(event.target.value); setChartId(""); }}>
            {documents.map((document) => <option key={document.id} value={document.id}>{document.title} · {document.file}</option>)}
          </select>
        </label>
        <label>График
          <select aria-label="График" value={selectedChart?.id ?? ""} onChange={(event) => setChartId(event.target.value)} disabled={!charts.length}>
            {charts.map((chart) => <option key={chart.id} value={chart.id}>{chart.title} · стр. {chart.page}</option>)}
          </select>
        </label>
      </section>
      {documents.length === 0 ? <p className="report-preview__state">В каталоге пока нет отчётов.</p>
        : !selectedChart ? <p className="report-preview__state">Для этого отчёта графики не найдены.</p>
          : <ReportSeriesComparison chart={selectedChart} items={chartSeries} />}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<ReportChartsPreview />);
