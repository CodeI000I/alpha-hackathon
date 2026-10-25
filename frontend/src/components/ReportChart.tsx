import { useId } from "react";
import type { ReportChart as ReportChartData, ReportChartSeries } from "../reportCharts";

function SeriesBars({ series }: { series: ReportChartSeries }) {
  const scale = Math.max(...series.points.map((point) => Math.abs(point.value))) || 1;
  const min = Math.min(0, ...series.points.map((point) => point.value / scale));
  const max = Math.max(0, ...series.points.map((point) => point.value / scale));
  const span = max - min || 1;
  const x = (value: number) => ((value / scale - min) / span) * 100;
  const zero = x(0);

  return (
    <div className="report-chart__bars" role="img" aria-label={`Сравнение подписанных значений: ${series.label}${series.unit ? ` · ${series.unit}` : ""}`}>
      {series.points.map((point, index) => {
        const valueX = x(point.value);
        return (
          <div className="report-chart__bar-row" key={`${point.label}-${index}`}>
            <div className="report-chart__bar-caption"><span>{point.label}</span><strong>{point.value}{series.unit ? ` ${series.unit}` : ""}{point.forecast ? " · Прогноз" : ""}</strong></div>
            <div className="report-chart__track">
              <span className="report-chart__zero" style={{ left: `${zero}%` }} />
              <span className={`report-chart__bar${point.forecast ? " report-chart__bar--forecast" : ""}`} style={{ left: `${Math.min(zero, valueX)}%`, width: `${Math.abs(valueX - zero)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ReportChart({ chart }: { chart: ReportChartData }) {
  const titleId = `report-chart-title-${useId()}`;
  return (
    <article className="report-chart" aria-labelledby={titleId}>
      <header className="report-chart__header">
        <div>
          <p className="report-chart__eyebrow">Страница {chart.page} · {chart.kind}</p>
          <h2 id={titleId}>{chart.title}</h2>
        </div>
        <span className="report-chart__status">
          {chart.data_status === "image_only" ? "Только изображение" : "Подписанные значения"}
        </span>
      </header>

      <figure className="report-chart__figure">
        <img src={`/report-charts/${chart.image}`} alt={`Оригинальный график: ${chart.title}`} />
        <figcaption>Фрагмент страницы исходного PDF</figcaption>
      </figure>

      {chart.data_status === "image_only" ? (
        <p className="report-chart__unavailable" role="status">числовой ряд не восстановлен</p>
      ) : (
        <section className="report-chart__data" aria-label="Подписанные значения">
          <p className="report-chart__axis">Ось X: {chart.x_axis.label}</p>
          <h3 className="report-chart__comparison-title">Сравнение подписанных значений</h3>
          <p className="report-chart__comparison-note">Каждый ряд масштабирован отдельно; исходный график выше.</p>
          {chart.series.map((series) => (
            <div className="report-chart__series" key={series.id}>
              <h4>{series.label}{series.unit ? ` · ${series.unit}` : ""}</h4>
              <SeriesBars series={series} />
              <table>
                <thead><tr><th scope="col">{chart.x_axis.label}</th><th scope="col">Значение</th><th scope="col">Тип</th></tr></thead>
                <tbody>{series.points.map((point, index) => (
                  <tr key={`${point.label}-${index}`}>
                    <th scope="row">{point.label}</th>
                    <td>{point.value}{series.unit ? ` ${series.unit}` : ""}</td>
                    <td>{point.forecast ? <span className="report-chart__forecast">Прогноз</span> : "Значение из отчёта"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ))}
        </section>
      )}
      {chart.note && <p className="report-chart__note">{chart.note}</p>}
    </article>
  );
}
