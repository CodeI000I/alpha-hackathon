import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ReportChart } from "./components/ReportChart";
import { parseReportChartCatalog, type ReportChartCatalog } from "./reportCharts";
import "./styles/tokens.css";
import "./styles/base.css";
import "./report-charts.css";

function ReportChartsPreview() {
  const [catalog, setCatalog] = useState<ReportChartCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [chartId, setChartId] = useState("");

  useEffect(() => {
    let active = true;
    fetch("/report-charts/catalog.json")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then((value) => {
        const parsed = parseReportChartCatalog(value);
        if (active) {
          setCatalog(parsed);
          setDocumentId(parsed.documents[0]?.id ?? "");
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Не удалось загрузить каталог графиков.");
      });
    return () => { active = false; };
  }, []);

  const documents = catalog?.documents ?? [];
  const charts = useMemo(() => catalog?.charts.filter((chart) => chart.document_id === documentId) ?? [], [catalog, documentId]);
  const selectedChart = charts.find((chart) => chart.id === chartId) ?? charts[0];

  useEffect(() => {
    if (!charts.some((chart) => chart.id === chartId)) setChartId(charts[0]?.id ?? "");
  }, [charts, chartId]);

  if (error) return <main className="report-preview"><div className="report-preview__state" role="alert"><h1>Не удалось открыть каталог</h1><p>{error}</p><p>Проверьте файл report-charts/catalog.json.</p></div></main>;
  if (!catalog) return <main className="report-preview"><p className="report-preview__state" role="status" aria-busy="true">Загружаем каталог графиков…</p></main>;

  return (
    <main className="report-preview">
      <header className="report-preview__intro">
        <p className="report-preview__eyebrow">Alfa · PDF отчёты</p>
        <h1>Графики из отчётов</h1>
        <p>Оригинальный фрагмент и только явно подписанные в источнике значения.</p>
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
          : <ReportChart chart={selectedChart} />}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<ReportChartsPreview />);
