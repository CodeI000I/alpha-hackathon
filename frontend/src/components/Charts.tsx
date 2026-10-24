import { useId } from "react";

export interface TrendPoint {
  label: string;
  value: number;
}

export interface TrendChartProps {
  title?: string;
  value?: string | number;
  change?: string;
  points?: Array<TrendPoint | number>;
  unit?: string;
  compact?: boolean;
  demo?: boolean;
}

const DEFAULT_TREND: TrendPoint[] = [
  { label: "Май", value: 32 },
  { label: "Июн", value: 35 },
  { label: "Июл", value: 33 },
  { label: "Авг", value: 39 },
  { label: "Сен", value: 42 },
  { label: "Окт", value: 45 },
];

function trendData(points?: Array<TrendPoint | number>) {
  if (!points?.length) return DEFAULT_TREND;
  return points.map((point, index) =>
    typeof point === "number" ? { label: String(index + 1), value: point } : point,
  );
}

function displayNumber(value: number, unit: string) {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value)}${unit}`;
}

export function TrendChart({
  title = "Динамика показателя",
  value,
  change,
  points,
  unit = "",
  compact = false,
  demo = true,
}: TrendChartProps) {
  const data = trendData(points);
  const gradientId = `trend-${useId().replace(/:/g, "")}`;
  const chart = { width: 640, height: 250, left: 16, right: 54, top: 18, bottom: 38 };
  const values = data.map((point) => point.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = maxValue - minValue || Math.max(Math.abs(maxValue), 1);
  const paddedMin = minValue - span * 0.18;
  const paddedMax = maxValue + span * 0.18;
  const plotWidth = chart.width - chart.left - chart.right;
  const plotHeight = chart.height - chart.top - chart.bottom;
  const x = (index: number) => chart.left + (data.length === 1 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth);
  const y = (pointValue: number) => chart.top + ((paddedMax - pointValue) / (paddedMax - paddedMin)) * plotHeight;
  const line = data.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = `${chart.left},${chart.height - chart.bottom} ${line} ${chart.left + plotWidth},${chart.height - chart.bottom}`;
  const currentValue = value ?? displayNumber(data[data.length - 1].value, unit);
  const gridValues = [paddedMax, (paddedMax + paddedMin) / 2, paddedMin];

  return (
    <section className={`trend-chart${compact ? " trend-chart--compact" : ""}`}>
      <div className="chart-heading">
        <h2>{title}</h2>
      </div>
      <strong className="trend-chart__value">{currentValue}</strong>
      {change && <span className="trend-chart__change">{change}</span>}
      <svg viewBox={`0 0 ${chart.width} ${chart.height}`} role="img" aria-label={`${title}: ${currentValue}`}>
        <title>{`${title}: ${currentValue}`}</title>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#4f91ff" stopOpacity="0.25" />
            <stop offset="1" stopColor="#4f91ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        {gridValues.map((gridValue) => {
          const gridY = y(gridValue);
          return (
            <g key={gridValue}>
              <line className="trend-chart__grid" x1={chart.left} x2={chart.left + plotWidth} y1={gridY} y2={gridY} />
              <text className="trend-chart__axis" x={chart.left + plotWidth + 12} y={gridY + 4}>
                {displayNumber(gridValue, unit)}
              </text>
            </g>
          );
        })}
        <polygon points={area} fill={`url(#${gradientId})`} />
        <polyline className="trend-chart__line" points={line} />
        {data.map((point, index) => (
          <circle key={`${point.label}-${index}`} className="trend-chart__point" cx={x(index)} cy={y(point.value)} r="4">
            <title>{`${point.label}: ${displayNumber(point.value, unit)}`}</title>
          </circle>
        ))}
        <text className="trend-chart__label" x={chart.left} y={chart.height - 10}>
          {data[0].label}
        </text>
        <text className="trend-chart__label" textAnchor="end" x={chart.left + plotWidth} y={chart.height - 10}>
          {data[data.length - 1].label}
        </text>
      </svg>
      {demo && <><p className="chart-note">Источник данных не подключён</p><details className="data-note"><summary>О данных</summary><p>Подготовленный набор для примера. График не подключён к рыночным данным или показателям компании.</p></details></>}
    </section>
  );
}

export interface RadarAxis {
  label: string;
  value: number;
}

export interface RadarChartProps {
  title?: string;
  axes?: RadarAxis[];
  demo?: boolean;
}

const DEFAULT_AXES: RadarAxis[] = [
  { label: "Финансы", value: 84 },
  { label: "Операции", value: 68 },
  { label: "Стратегия", value: 74 },
  { label: "Команда", value: 52 },
  { label: "Рынок", value: 63 },
];

export function RadarChart({ title = "Направления внимания", axes = DEFAULT_AXES, demo = true }: RadarChartProps) {
  const data = axes.length >= 3 ? axes : DEFAULT_AXES;
  const center = { x: 250, y: 190 };
  const radius = 116;
  const position = (index: number, scale = 1) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / data.length;
    return {
      x: center.x + Math.cos(angle) * radius * scale,
      y: center.y + Math.sin(angle) * radius * scale,
    };
  };
  const polygon = (scale: number) => data.map((_, index) => {
    const point = position(index, scale);
    return `${point.x},${point.y}`;
  }).join(" ");
  const values = data.map((axis, index) => {
    const point = position(index, Math.max(0, Math.min(axis.value, 100)) / 100);
    return `${point.x},${point.y}`;
  }).join(" ");

  return (
    <section className="radar-chart">
      <div className="chart-heading">
        <h2>{title}</h2>
      </div>
      <svg viewBox="0 0 500 380" role="img" aria-label={`${title}: ${data.map((axis) => `${axis.label} ${axis.value}%`).join(", ")}`}>
        <title>{title}</title>
        {[0.25, 0.5, 0.75, 1].map((scale) => (
          <polygon key={scale} className="radar-chart__grid" points={polygon(scale)} />
        ))}
        {data.map((_, index) => {
          const point = position(index);
          return <line key={index} className="radar-chart__grid" x1={center.x} y1={center.y} x2={point.x} y2={point.y} />;
        })}
        <polygon className="radar-chart__area" points={values} />
        {data.map((axis, index) => {
          const point = position(index, Math.max(0, Math.min(axis.value, 100)) / 100);
          const label = position(index, 1.32);
          const anchor = label.x < center.x - 8 ? "end" : label.x > center.x + 8 ? "start" : "middle";
          return (
            <g key={axis.label}>
              <circle className="radar-chart__point" cx={point.x} cy={point.y} r="4" />
              <text className="radar-chart__label" x={label.x} y={label.y} textAnchor={anchor}>
                <tspan x={label.x} dy="0">{axis.label}</tspan>
                <tspan className="radar-chart__value" x={label.x} dy="18">{axis.value}%</tspan>
              </text>
            </g>
          );
        })}
      </svg>
      {demo && <><p className="chart-note">Источник данных не подключён</p><details className="data-note"><summary>О данных</summary><p>Показаны направления внимания, а не оценка риска компании.</p></details></>}
    </section>
  );
}
