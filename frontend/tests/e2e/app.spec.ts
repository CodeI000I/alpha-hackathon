import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

let browserErrors: string[] = [];

test.beforeEach(async ({ page }) => {
  browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
});

test.afterEach(() => {
  expect(browserErrors, "browser console and runtime errors").toEqual([]);
});

async function openAsDemoUser(page: Page, path = "/feed") {
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("alpha.userId", "1"));
  await page.goto(path);
}

test("landing → onboarding → personalized feed", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "События, которые важны именно вашему бизнесу" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Настроить ленту" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByText("Деморежим", { exact: true })).toBeVisible();

  await page.getByLabel("Как вас зовут").fill("Анна Петрова");
  await page.getByLabel("Электронная почта").fill("anna@example.ru");
  await page.getByLabel("Название компании").fill("ООО Север");
  await page.getByLabel("ИНН компании").fill("7707083893");
  await page.getByRole("checkbox", { name: /Финансовый директор/ }).check({ force: true });
  await page.getByRole("button", { name: "Перейти к событиям" }).click();

  await expect(page).toHaveURL(/\/feed$/);
  await expect(page.getByRole("heading", { name: "Обзор событий", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Банк России сохранил ключевую ставку" })).toBeVisible();
});

test("restores a session and supports search, kind filters, and saved items", async ({ page }) => {
  await openAsDemoUser(page);

  await expect(page).toHaveURL(/\/feed$/);
  await expect(page.getByRole("heading", { name: "Обзор событий", level: 1 })).toBeVisible();
  await expect(page.locator(".event-card")).toHaveCount(3);

  await page.getByLabel("Поиск по событиям").fill("информационным системам");
  await expect(page.locator(".event-card")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Опубликованы новые требования к информационным системам" })).toBeVisible();

  await page.getByLabel("Поиск по событиям").fill("");
  await page.getByRole("button", { name: "Риски", exact: true }).click();
  await expect(page.locator(".event-card")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Банк России сохранил ключевую ставку" })).toBeVisible();

  await page.getByRole("button", { name: "Все события", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить: Банк России сохранил ключевую ставку" }).click();
  await page.getByRole("button", { name: /Сохранённые/ }).click();
  await expect(page.locator(".event-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Убрать из сохранённых: Банк России сохранил ключевую ставку" })).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: /Сохранённые/ }).click();
  await expect(page.locator(".event-card")).toHaveCount(1);
});

test("opens a feed item directly and persists local demo chat", async ({ page }) => {
  await openAsDemoUser(page, "/feed/101");

  await expect(
    page.getByRole("heading", { name: "Банк России сохранил ключевую ставку", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Релевантность")).toBeVisible();

  await page.getByRole("button", { name: "Какие данные нужно проверить?" }).click();
  await expect(page.getByText(/проверьте сроки, суммы, действующие обязательства/i)).toBeVisible();

  await page.reload();
  await expect(page.locator(".demo-chat__history .demo-chat__question")).toHaveText(
    "Какие данные нужно проверить?",
  );
  await expect(page.getByText(/проверьте сроки, суммы, действующие обязательства/i)).toBeVisible();
});

test("changes roles and keeps the server-backed demo result", async ({ page }) => {
  await openAsDemoUser(page, "/company?tab=roles");

  const marketing = page.getByRole("checkbox", { name: /Директор по маркетингу/ });
  await expect(marketing).not.toBeChecked();
  await marketing.check({ force: true });
  await page.getByRole("button", { name: "Сохранить роли" }).click();
  await expect(page.getByRole("status")).toContainText("Роли сохранены");

  await page.getByRole("link", { name: "Обзор событий", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Бизнес увеличил расходы на отечественные цифровые сервисы" })).toBeVisible();

  await page.goto("/company?tab=roles");
  await expect(page.getByRole("checkbox", { name: /Директор по маркетингу/ })).toBeChecked();
});

test("shows an explicit empty state when the selected role has no events", async ({ page }) => {
  await openAsDemoUser(page, "/company?tab=roles");

  const checkboxes = page.getByRole("checkbox");
  for (let index = 0; index < (await checkboxes.count()); index += 1) {
    const checkbox = checkboxes.nth(index);
    if (await checkbox.isChecked()) await checkbox.uncheck({ force: true });
  }
  await page.getByRole("checkbox", { name: /Директор по закупкам/ }).check({ force: true });
  await page.getByRole("button", { name: "Сохранить роли" }).click();
  await expect(page.getByRole("status")).toContainText("Роли сохранены");

  await page.goto("/feed");
  await expect(page.getByRole("heading", { name: "В ленте пока нет событий" })).toBeVisible();
});

test("uploads a document in demo mode", async ({ page }) => {
  await openAsDemoUser(page, "/company?tab=documents");
  await expect(page.getByText(/Демо-файлы сохраняются только локально/)).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: "бюджет-2027.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("demo document"),
  });

  await expect(page.getByRole("status")).toContainText("Документ загружен");
  await expect(page.getByText("бюджет-2027.pdf", { exact: true })).toBeVisible();
});

test("logout clears the local session", async ({ page }) => {
  await openAsDemoUser(page);

  await page.getByRole("button", { name: "Открыть меню профиля" }).click();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: "События, которые важны именно вашему бизнесу" }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("alpha.userId"))).toBeNull();
});

test("key pages have no horizontal overflow at supported widths", async ({ page }) => {
  await openAsDemoUser(page);

  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/feed", "/feed/101", "/company?tab=documents"]) {
      await page.goto(path);
      await expect(page.locator(".landing-page, .app-main").first()).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
        `${path} should fit within a ${width}px viewport`,
      ).toBe(true);
    }
  }
});
