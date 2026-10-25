import { expect, test } from "@playwright/test";

const catalog = {
  schema_version: 1,
  documents: [{ id: "report-1", file: "report.pdf", sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", pages: 2, title: "Отчёт Альфа" }],
  charts: [
    {
      id: "numeric-chart", document_id: "report-1", page: 1, title: "Выручка", kind: "bar",
      crop: [0.1, 0.2, 0.8, 0.7], data_status: "labelled_values",
      x_axis: { label: "Год", kind: "time" },
      series: [
        { id: "actual", label: "Факт", unit: "млрд руб.", points: [{ label: "2023", value: 10 }, { label: "2024", value: 12, forecast: true }] },
        { id: "margin", label: "Маржа", unit: "%", points: [{ label: "2023", value: -4 }, { label: "2024", value: 8 }] },
      ],
      note: "Прогноз на 2024 год", image: "images/numeric-chart.jpg",
    },
    {
      id: "image-chart", document_id: "report-1", page: 2, title: "Рынок", kind: "mixed",
      crop: [0.1, 0.2, 0.8, 0.7], data_status: "image_only", x_axis: { label: "Год", kind: "time" },
      series: [], note: "Числа не подписаны", image: "images/image-chart.jpg",
    },
  ],
};

test("preview shows exact labelled values and clearly marks image-only charts", async ({ page }) => {
  await page.route("**/report-charts/catalog.json", route => route.fulfill({ json: catalog }));
  await page.route("**/report-charts/images/*.jpg", route => route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=", "base64") }));
  await page.goto("/report-charts.html");

  await expect(page.getByRole("heading", { name: "Графики из отчётов" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Оригинальный график: Выручка" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Сравнение подписанных значений: Факт · млрд руб." })).toBeVisible();
  const marginPlot = page.getByRole("img", { name: "Сравнение подписанных значений: Маржа · %" });
  await expect(marginPlot).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(2);
  expect(await marginPlot.evaluate((plot) => {
    const zero = parseFloat((plot.querySelector(".report-chart__zero") as HTMLElement).style.left);
    const negativeBar = parseFloat((plot.querySelector(".report-chart__bar") as HTMLElement).style.left);
    return negativeBar < zero;
  })).toBe(true);
  await expect(page.getByRole("table").first()).toContainText("10 млрд руб.");
  await expect(page.getByRole("table").first()).toContainText("12 млрд руб.");
  await expect(page.getByRole("table").nth(0).getByRole("row", { name: /2023/ })).toContainText("Значение из отчёта");
  await expect(page.getByRole("table").nth(0).getByRole("row", { name: /2024/ })).toContainText("Прогноз");
  await expect(page.locator("img[alt='Оригинальный график: Выручка']")).toHaveJSProperty("naturalWidth", 1);

  await page.getByLabel("График", { exact: true }).selectOption("image-chart");
  await expect(page.getByText("числовой ряд не восстановлен", { exact: false })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("invalid catalogs show an error instead of rendering unvalidated data", async ({ page }) => {
  await page.route("**/report-charts/catalog.json", route => route.fulfill({ json: { schema_version: 2, documents: [], charts: [] } }));
  await page.goto("/report-charts.html");
  await expect(page.getByRole("alert")).toContainText("Не удалось открыть каталог");
});

test("shipped report catalog and every chart image load offline on desktop and mobile", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const response = await request.get("/report-charts/catalog.json");
  expect(response.ok()).toBe(true);
  const real = await response.json();
  expect(real.documents).toHaveLength(9);
  expect(real.charts).toHaveLength(97);
  await page.goto("/report-charts.html");
  await expect(page.getByRole("heading", { name: "Графики из отчётов" })).toBeVisible();
  const imageSizes = await page.evaluate(async (paths: string[]) => Promise.all(paths.map(path => new Promise<number>((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image.naturalWidth);
    image.onerror = () => resolve(0);
    image.src = `/report-charts/${path}`;
  }))), real.charts.map((chart: { image: string }) => chart.image));
  expect(imageSizes.every(width => width > 0)).toBe(true);
  await page.getByLabel("Отчёт", { exact: true }).selectOption("gold-digest-august-2026");
  await page.getByLabel("График", { exact: true }).selectOption("gold-aug26-gold-vs-dollar-returns");
  await expect(page.getByRole("table")).toContainText("-0.5 %");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const picture = page.locator("figure img");
    await expect(picture).toBeVisible();
    const bounds = await picture.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
  }
  expect(errors).toEqual([]);
});
