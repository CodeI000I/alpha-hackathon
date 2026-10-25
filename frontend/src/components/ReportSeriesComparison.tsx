import { useEffect, useMemo, useState } from "react";
import type { ReportChart } from "../reportCharts";
import { parseReportSeries, reportAssetUrl, type ReportSeriesIndexItem, type SeriesRecord } from "../reportSeries";

interface Props { chart: ReportChart; items: ReportSeriesIndexItem[]; }

export function ReportSeriesComparison({ chart, items }: Props) {
  const [seriesId, setSeriesId] = useState(items[0]?.id ?? "");
  const [record, setRecord] = useState<SeriesRecord | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAnchors, setShowAnchors] = useState(false);
  const [imageSize, setImageSize] = useState<[number, number] | null>(null);
  const selected = items.find((item) => item.id === seriesId) ?? items[0];

  useEffect(() => {
    setSeriesId(items[0]?.id ?? "");
    setShowAnchors(false);
    setImageSize(null);
  }, [chart.id, items]);

  useEffect(() => {
    if (!selected) { setRecord(null); setLoadError(null); setLoading(false); return; }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setRecord(null);
    setLoadError(null);
    fetch(reportAssetUrl(selected.json_file), { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json() as Promise<unknown>; })
      .then((value) => { const parsed = parseReportSeries(value, selected); if (active) setRecord(parsed); })
      .catch((reason: unknown) => { if (active && !(reason instanceof DOMException && reason.name === "AbortError")) setLoadError(reason instanceof Error ? reason.message : "Не удалось загрузить данные ряда."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [selected]);

  const digitizedEntry = useMemo(() => record?.digitization?.series.find((entry) => entry.id === record.series_id), [record]);
  const anchors = digitizedEntry?.mode !== "unreadable" ? digitizedEntry?.anchors : undefined;
  const plot = record?.digitization?.plot;

  return (
    <article className="series-comparison" aria-labelledby="series-chart-title">
      <header className="series-comparison__header">
        <div><p className="report-chart__eyebrow">Страница {chart.page}</p><h2 id="series-chart-title">{chart.title}</h2></div>
        <label className="series-comparison__select">Ряд
          <select aria-label="Ряд" value={selected?.id ?? ""} onChange={(event) => setSeriesId(event.target.value)} disabled={!items.length}>
            {items.map((item) => <option key={item.id} value={item.id}>{item.label}{item.unit ? ` · ${item.unit}` : ""}</option>)}
          </select>
        </label>
      </header>
      {!items.length ? <p className="report-preview__state">Для этого графика в индексе нет рядов.</p> : (
        <>
          <div className="series-comparison__downloads">
            <a href={reportAssetUrl(selected!.json_file)} download={`${selected!.id}.json`}>Скачать JSON ряда</a>
            {selected!.svg_file && <a href={reportAssetUrl(selected!.svg_file)} download={`${selected!.id}.svg`}>Скачать SVG графика</a>}
            {record?.data_status === "digitized" && <span className="series-comparison__badge" data-testid="approx-badge">Приблизительно</span>}
            {record?.data_status === "labelled_values" && <span className="series-comparison__badge series-comparison__badge--exact">Подписанные значения</span>}
          </div>
          {loading && <p className="report-preview__state" role="status" aria-busy="true">Загружаем выбранный ряд…</p>}
          {loadError && <div className="report-preview__state" role="alert"><strong>Не удалось загрузить ряд</strong><span>{loadError}</span></div>}
          {record && !loading && (
            <>
              <div className="series-comparison__grid">
                <section className="series-comparison__panel" aria-label="Исходный график">
                  <h3>Исходный фрагмент</h3>
                  <figure className="series-comparison__source">
                    <div className="series-comparison__image-wrap">
                      <img src={reportAssetUrl(chart.image)} alt={`Оригинальный график: ${chart.title}`} onLoad={(event) => setImageSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])} />
                      {showAnchors && anchors && plot && imageSize && (
                        <svg className="series-comparison__overlay" viewBox={`0 0 ${imageSize[0]} ${imageSize[1]}`} aria-label="Опорные точки оцифровки" role="img">
                          {anchors.map((anchor, index) => {
                            const x = plot[0] + anchor[0] * (plot[2] - plot[0]);
                            const y1 = plot[1] + anchor[1] * (plot[3] - plot[1]);
                            const y2 = anchor.length === 3 ? plot[1] + anchor[2] * (plot[3] - plot[1]) : null;
                            return <g key={`${index}-${anchor[0]}`}><circle cx={x} cy={y1} r={Math.max(4, imageSize[0] / 250)} /><title>{`Точка ${index + 1}`}</title>{y2 !== null && <><line x1={x} y1={y1} x2={x} y2={y2} /><circle cx={x} cy={y2} r={Math.max(4, imageSize[0] / 250)} /></>}</g>;
                          })}
                        </svg>
                      )}
                    </div>
                    <figcaption>{chart.x_axis.label ? `Ось X: ${chart.x_axis.label}. ` : ""}{chart.note}</figcaption>
                  </figure>
                  {digitizedEntry && digitizedEntry.mode !== "unreadable" && anchors && <label className="series-comparison__toggle"><input type="checkbox" checked={showAnchors} onChange={(event) => setShowAnchors(event.target.checked)} /> Показать опорные точки на оригинале</label>}
                </section>
                <section className="series-comparison__panel" aria-label="Восстановленный ряд">
                  <h3>{record.label}{record.unit ? ` · ${record.unit}` : ""}</h3>
                  {record.data_status === "unavailable" ? <div className="series-comparison__unavailable" role="status"><strong>Числовой ряд недоступен</strong><p>{record.digitization?.series[0]?.note || record.note || chart.note || "В источнике нет читаемых подписанных значений для этого ряда."}</p></div>
                    : record.svg_file ? <figure className="series-comparison__reconstructed"><img src={reportAssetUrl(record.svg_file)} alt={`Ряд: ${record.label}${record.unit ? ` · ${record.unit}` : ""}`} /><figcaption>{record.data_status === "digitized" ? "Приблизительная визуальная оцифровка исходного графика; подписи X взяты из источника." : "Ряд из напечатанных в отчёте значений."}</figcaption></figure>
                      : <p className="series-comparison__unavailable">Для ряда нет SVG-изображения.</p>}
                </section>
              </div>
              {record.data_status === "digitized" && digitizedEntry && digitizedEntry.mode !== "unreadable" && <aside className="series-comparison__approx" aria-label="Ограничения оцифровки">
                <strong>Приблизительно · оценка погрешности ±{digitizedEntry.estimated_error} {record.unit}</strong>
                <p>Погрешность оценочная и не является гарантией точности. {digitizedEntry.note}</p>
                {record.exact_points.length > 0 && <div><h4>Точные подписи из исходника</h4><ul>{record.exact_points.map((point, index) => <li key={`${point.label}-${index}`}>{point.label}: {point.value}{record.unit ? ` ${record.unit}` : ""}{point.forecast ? " · прогноз" : ""}</li>)}</ul></div>}
                {record.points.some((point) => point.forecast) && <p>Точки прогноза: {record.points.filter((point) => point.forecast).map((point) => typeof point.x === "number" ? `x=${point.x}` : point.x).join(", ")}.</p>}
                {record.digitization?.x_ticks.length ? <p>Подписи оси X: {record.digitization.x_ticks.map((tick) => `${tick.label} (позиция ${tick.position})`).join("; ")}. Числовые x в JSON нормированы от 0 до 1.</p> : null}
              </aside>}
              <details className="series-comparison__json"><summary>Пример данных JSON</summary><pre><code>{JSON.stringify(record, null, 2)}</code></pre></details>
            </>
          )}
        </>
      )}
    </article>
  );
}
