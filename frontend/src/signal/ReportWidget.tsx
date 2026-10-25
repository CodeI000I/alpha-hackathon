import { useEffect, useState } from 'react';
import { parseReportChartCatalog } from '../reportCharts';
import { parseReportSeries, parseReportSeriesIndex, reportAssetUrl, type ReportSeriesIndexItem, type SeriesRecord } from '../reportSeries';

export const defaultReportSeriesId = 'fi-monetary-policy--key-rate';

export function useReportWidgetCatalog() {
  const [items, setItems] = useState<ReportSeriesIndexItem[] | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setItems(null);
    setError(false);
    Promise.all(['/report-charts/catalog.json', '/report-charts/series-index.json'].map(async url => {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<unknown>;
    })).then(([catalog, index]) => {
      const parsed = parseReportSeriesIndex(index, parseReportChartCatalog(catalog));
      if (active) setItems(parsed.items);
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; controller.abort(); };
  }, [attempt]);
  return { items, error, retry: () => setAttempt(value => value + 1) };
}

export function ReportSeriesPicker({ items, seriesId, onChange }: { items: ReportSeriesIndexItem[]; seriesId: string; onChange: (id: string) => void }) {
  const available = items;
  const selected = available.find(item => item.id === seriesId) ?? available[0];
  if (!selected) return <p role="status">В архиве нет рядов.</p>;
  const documents = [...new Map(available.map(item => [item.expected_source.document.id, item.expected_source.document])).values()];
  const documentItems = available.filter(item => item.expected_source.document.id === selected.expected_source.document.id);
  const charts = [...new Map(documentItems.map(item => [item.chart_id, item])).values()];
  return <>
    <label>Отчёт PDF<select aria-label="Отчёт PDF" value={selected.expected_source.document.id} onChange={event => onChange(available.find(item => item.expected_source.document.id === event.target.value)!.id)}>
      {documents.map(document => <option key={document.id} value={document.id}>{document.title} · {document.file}</option>)}
    </select></label>
    <label>График PDF<select aria-label="График PDF" value={selected.chart_id} onChange={event => onChange(documentItems.find(item => item.chart_id === event.target.value)!.id)}>
      {charts.map(item => <option key={item.chart_id} value={item.chart_id}>{item.expected_source.chart_title} · стр. {item.expected_source.page}</option>)}
    </select></label>
    <label>Ряд PDF<select aria-label="Ряд PDF" value={selected.id} onChange={event => onChange(event.target.value)}>
      {documentItems.filter(item => item.chart_id === selected.chart_id).map(item => <option key={item.id} value={item.id}>{item.label}{item.unit ? ` · ${item.unit}` : ''} · {item.data_status === 'digitized' ? 'приблизительно' : item.data_status === 'labelled_values' ? 'подписи из PDF' : 'числа недоступны'}</option>)}
    </select></label>
  </>;
}

export function ReportWidget({ item }: { item: ReportSeriesIndexItem | undefined }) {
  const [record, setRecord] = useState<SeriesRecord | null>(null);
  const [error, setError] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!item) return;
    const controller = new AbortController();
    let active = true;
    setRecord(null);
    setError(false);
    setImageError(false);
    fetch(reportAssetUrl(item.json_file), { signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json() as Promise<unknown>; })
      .then(raw => { const parsed = parseReportSeries(raw, item); if (active) setRecord(parsed); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; controller.abort(); };
  }, [item, attempt]);
  if (!item) return <p role="status">Сохранённый ряд отсутствует в архиве. Выберите другой график через каталог виджетов.</p>;
  if (error || imageError) return <div role="alert"><p>Не удалось загрузить {imageError ? 'график' : 'ряд'} PDF.</p><button className="widget-back" onClick={() => setAttempt(value => value + 1)}>Повторить загрузку ряда</button></div>;
  if (!record || record.id !== item.id) return <p role="status" aria-busy="true">Загружаем ряд PDF…</p>;
  const entry = record.digitization?.series[0];
  const ticks = record.digitization?.x_ticks;
  const labels = ticks?.length ? ticks.map(tick => tick.label) : record.points.map(point => String(point.x));
  return <div className="report-widget">
    <h3>{record.label}{record.unit ? ` · ${record.unit}` : ''}</h3>
    <p className="report-widget-status">Архивный отчёт · не текущие котировки</p>
    <p className="report-widget-badge">{record.data_status === 'digitized' ? 'Приблизительно' : record.data_status === 'labelled_values' ? 'Подписанные значения' : 'Числовой ряд недоступен'}</p>
    {record.svg_file && <img src={reportAssetUrl(record.svg_file)} alt={`Ряд из PDF: ${record.label}${record.unit ? ` · ${record.unit}` : ''}`} onError={() => setImageError(true)} />}
    {labels.length > 0 && <p className="widget-footnote">Ось X из отчёта: {labels.join(' · ')}</p>}
    <p className="widget-footnote">{record.source.document.title} · {record.source.document.file} · стр. {record.source.page}</p>
    <details className="data-note"><summary>Источник и точность</summary>
      <p>{record.source.chart_title}. {record.note}</p>
      {record.data_status === 'digitized' && entry && entry.mode !== 'unreadable' && <p>Приблизительная оцифровка. Оценка погрешности ±{entry.estimated_error} {record.unit}; не является гарантией точности. {entry.note}</p>}
      {record.exact_points.length > 0 && <p>Точные подписи из PDF: {record.exact_points.map(point => `${point.label}: ${point.value} ${record.unit}${point.forecast ? ' · прогноз' : ''}`).join('; ')}.</p>}
      {record.points.some(point => point.forecast) && <p>Ряд содержит прогноз из исходного отчёта; прогнозные точки отмечены на графике.</p>}
      <p>SHA-256 PDF: {record.source.document.sha256}</p>
    </details>
    <div className="report-widget-links"><a href={reportAssetUrl(record.source.image)} target="_blank" rel="noreferrer">Исходный фрагмент PDF</a><a href={reportAssetUrl(record.json_file)} download>JSON ряда</a><a href="/report-charts.html" target="_blank" rel="noreferrer">Все графики PDF</a></div>
  </div>;
}
