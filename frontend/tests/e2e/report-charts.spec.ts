import { expect, test, type Page } from "@playwright/test";

const catalog = {
  schema_version: 1,
  documents: [{ id: "report-1", file: "report.pdf", sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", pages: 2, title: "Отчёт Альфа" }],
  charts: [
    { id: "numeric-chart", document_id: "report-1", page: 1, title: "Выручка", kind: "bar", crop: [0.1, 0.2, 0.8, 0.7], data_status: "labelled_values", x_axis: { label: "Год", kind: "time" }, series: [{ id: "actual", label: "Факт", unit: "млрд руб.", points: [{ label: "2023", value: 10 }, { label: "2024", value: 12, forecast: true }] }, { id: "margin", label: "Маржа", unit: "%", points: [{ label: "2023", value: -4 }, { label: "2024", value: 8 }] }], unavailable_series: [], note: "Прогноз на 2024 год", image: "images/numeric-chart.jpg", image_sha256: "a".repeat(64) },
    { id: "image-chart", document_id: "report-1", page: 2, title: "Рынок", kind: "mixed", crop: [0.1, 0.2, 0.8, 0.7], data_status: "image_only", x_axis: { label: "Год", kind: "time" }, series: [], unavailable_series: [{ id: "line-a", label: "Индекс спроса", unit: "пункты" }], note: "Числа не подписаны", image: "images/image-chart.jpg", image_sha256: "b".repeat(64) },
  ],
};
const items = [
  { id: "numeric-chart--actual", chart_id: "numeric-chart", series_id: "actual", label: "Факт", unit: "млрд руб.", data_status: "labelled_values", json_file: "series/numeric-chart--actual.json", svg_file: "series/numeric-chart--actual.svg" },
  { id: "numeric-chart--margin", chart_id: "numeric-chart", series_id: "margin", label: "Маржа", unit: "%", data_status: "digitized", json_file: "series/numeric-chart--margin.json", svg_file: "series/numeric-chart--margin.svg" },
  { id: "image-chart--line-a", chart_id: "image-chart", series_id: "line-a", label: "Индекс спроса", unit: "пункты", data_status: "unavailable", json_file: "series/image-chart--line-a.json", svg_file: null },
];
const records: Record<string, unknown> = {
  "numeric-chart--actual": { schema_version: 1, id: items[0].id, chart_id: items[0].chart_id, series_id: items[0].series_id, label: items[0].label, unit: items[0].unit, data_status: items[0].data_status, note: "Подписи в отчёте", source: { document: catalog.documents[0], chart_title: "Выручка", page: 1, crop: [0.1, 0.2, 0.8, 0.7], image: "images/numeric-chart.jpg", image_sha256: "a".repeat(64) }, exact_points: [{ label: "2023", value: 10 }, { label: "2024", value: 12, forecast: true }], points: [{ x: "2023", value: 10, source_index: 0 }, { x: "2024", value: 12, source_index: 1, forecast: true }], json_file: items[0].json_file, svg_file: items[0].svg_file, digitization: null },
  "numeric-chart--margin": { schema_version: 1, id: items[1].id, chart_id: items[1].chart_id, series_id: items[1].series_id, label: items[1].label, unit: items[1].unit, data_status: items[1].data_status, note: "Визуальная оценка", source: { document: catalog.documents[0], chart_title: "Выручка", page: 1, crop: [0.1, 0.2, 0.8, 0.7], image: "images/numeric-chart.jpg", image_sha256: "a".repeat(64) }, exact_points: [{ label: "2023", value: -4 }, { label: "2024", value: 8 }], points: [{ x: 0, value: -4 }, { x: 1, value: 8 }], json_file: items[1].json_file, svg_file: items[1].svg_file, digitization: { image_sha256: "a".repeat(64), plot: [20, 20, 100, 80], x_ticks: [{ position: 0, label: "2023" }, { position: 1, label: "2024" }], series: [{ id: "margin", mode: "line", anchors: [[0, 0.9333333333333333], [1, 0.13333333333333333]], y_axis: { min: -5, max: 10 }, estimated_error: 0.5, note: "Линия размыта." }] } },
  "image-chart--line-a": { schema_version: 1, id: items[2].id, chart_id: items[2].chart_id, series_id: items[2].series_id, label: items[2].label, unit: items[2].unit, data_status: items[2].data_status, note: "Серия указана в легенде, но точные значения не напечатаны.", source: { document: catalog.documents[0], chart_title: "Рынок", page: 2, crop: [0.1, 0.2, 0.8, 0.7], image: "images/image-chart.jpg", image_sha256: "b".repeat(64) }, exact_points: [], points: [], json_file: items[2].json_file, svg_file: null, digitization: null },
};
const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect width="200" height="100" fill="white"/><text x="10" y="30">reconstructed</text></svg>';
const pixelPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=", "base64");

async function fixture(page: Page) {
  await page.route("**/report-charts/catalog.json", route => route.fulfill({ json: catalog }));
  await page.route("**/report-charts/series-index.json", route => route.fulfill({ json: { schema_version: 1, items } }));
  await page.route("**/report-charts/series/*.json", route => {
    const name = route.request().url().split("/").pop()!.replace(/\.json$/, "");
    const data = records[name];
    return data ? route.fulfill({ json: { ...(data as Record<string, unknown>), x_axis: { label: "Год", kind: "time" } } }) : route.fulfill({ status: 404 });
  });
  await page.route("**/report-charts/series/*.svg", route => route.fulfill({ status: 200, contentType: "image/svg+xml", body: svg }));
  await page.route("**/report-charts/images/*.jpg", route => route.fulfill({ status: 200, contentType: "image/png", body: pixelPng }));
}

test("one independent series is compared at a time with exact and approximate states", async ({ page }) => {
  await fixture(page);
  await page.goto("/report-charts.html");
  await expect(page.getByRole("heading", { name: "Сравнение рядов из отчётов" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Оригинальный график: Выручка" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Ряд: Факт · млрд руб." })).toBeVisible();
  await expect(page.getByRole("img", { name: "Ряд: Маржа · %" })).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Сравнение подписанных значений: Факт · млрд руб." })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Скачать JSON ряда" })).toHaveAttribute("href", "/report-charts/series/numeric-chart--actual.json");

  await page.getByLabel("Ряд", { exact: true }).selectOption("numeric-chart--margin");
  await expect(page.getByTestId("approx-badge")).toHaveText("Приблизительно");
  await expect(page.getByText(/оценка погрешности ±0\.5 %/)).toBeVisible();
  await expect(page.getByText(/Погрешность оценочная и не является гарантией точности/)).toBeVisible();
  await expect(page.getByText(/2023: -4 %/)).toBeVisible();
  await page.getByLabel("Показать опорные точки на оригинале").check();
  await expect(page.getByRole("img", { name: "Опорные точки оцифровки" }).locator("circle")).toHaveCount(2);
  await expect(page.getByRole("img", { name: "Ряд: Маржа · %" })).toBeVisible();
  await page.getByLabel("График", { exact: true }).selectOption("image-chart");
  await expect(page.getByRole("status")).toContainText("Числовой ряд недоступен");
  await expect(page.getByRole("img", { name: /^Ряд:/ })).toHaveCount(0);
});

test("selected-series fetch errors are visible", async ({ page }) => {
  await fixture(page);
  await page.route("**/report-charts/series/numeric-chart--margin.json", route => route.fulfill({ status: 503 }));
  await page.goto("/report-charts.html");
  await page.getByLabel("Ряд", { exact: true }).selectOption("numeric-chart--margin");
  await expect(page.getByRole("alert")).toContainText("Не удалось загрузить ряд");
});

test("shipped series index and chart assets load offline without horizontal overflow", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const [catalogResponse, indexResponse] = await Promise.all([request.get("/report-charts/catalog.json"), request.get("/report-charts/series-index.json")]);
  expect(catalogResponse.ok()).toBe(true);
  expect(indexResponse.ok()).toBe(true);
  const realCatalog = await catalogResponse.json();
  const realIndex = await indexResponse.json();
  expect(Array.isArray(realIndex.items)).toBe(true);
  expect(realIndex.items.length).toBeGreaterThan(0);
  expect(realIndex.items.every((item: { chart_id: string }) => realCatalog.charts.some((chart: { id: string }) => chart.id === item.chart_id))).toBe(true);
  await page.goto("/report-charts.html");
  await expect(page.getByRole("heading", { name: "Сравнение рядов из отчётов" })).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const source = page.locator(".series-comparison__image-wrap > img");
    await expect(source).toBeVisible();
    const bounds = await source.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    const panels = await page.locator(".series-comparison__grid").evaluate((grid) => [...grid.children].map((child) => child.getBoundingClientRect().width));
    if (width >= 1000) expect(Math.abs(panels[0] - panels[1])).toBeLessThan(10);
    else expect(panels[0]).toBeCloseTo(panels[1], 0);
  }
  expect(errors).toEqual([]);
});
