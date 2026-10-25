import { expect, test } from '@playwright/test';
import { loginDemo } from './helpers';

test('dashboard report widgets preserve real source, series choice and account layout', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await loginDemo(page);
  const board = page.locator('.widget-board');
  const first = board.locator(':scope > .market-widget').first();
  await expect(first.getByRole('img', { name: 'Ряд из PDF: Ключевая ставка · %' })).toBeVisible();
  await expect(first).toContainText('Архивный отчёт · не текущие котировки');
  await expect(first).toContainText('Приблизительно');
  await expect(first).toContainText('FI_Strategy_3Q26_22072026.pdf');
  await expect(first.getByLabel(/^Период:/)).toHaveCount(0);

  await board.getByRole('button', { name: 'Добавить виджет', exact: true }).click();
  await page.getByRole('button', { name: /График из PDF/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Настроить виджет' });
  await dialog.getByLabel('Отчёт PDF', { exact: true }).selectOption('fi-strategy-3q26');
  await dialog.getByLabel('График PDF', { exact: true }).selectOption('fi-corporate-placements');
  await expect(dialog).toContainText('Подписанные значения');
  await dialog.getByRole('button', { name: 'Добавить на главный экран' }).click();
  const widgets = board.locator(':scope > .market-widget');
  await expect(widgets).toHaveCount(2);
  await expect(widgets.nth(1).getByRole('link', { name: 'JSON ряда' })).toHaveAttribute('href', '/report-charts/series/fi-corporate-placements--volume.json');
  await page.reload();
  await expect(widgets).toHaveCount(2);
  await expect(widgets.nth(1)).toContainText('Подписанные значения');

  await widgets.nth(1).getByLabel(/^Настройки виджета/).click();
  await widgets.nth(1).getByRole('button', { name: 'Поднять выше ↑' }).click();
  await expect(widgets.first()).toContainText('Подписанные значения');
  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await loginDemo(page, 'operations');
  await expect(widgets).toHaveCount(1);
  await expect(widgets.first()).toContainText('Ключевая ставка');
  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await loginDemo(page);
  await expect(widgets).toHaveCount(2);
  await expect(widgets.first()).toContainText('Подписанные значения');
  await widgets.first().getByLabel(/^Настройки виджета/).click();
  await widgets.first().getByRole('button', { name: 'Удалить виджет' }).click();
  await expect(widgets).toHaveCount(1);
  for (const width of [1440, 1024, 768, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(first.getByRole('img', { name: /^Ряд из PDF:/ })).toBeVisible();
    expect(await first.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test('report catalog failure is visible and can be retried', async ({ page }) => {
  await page.route('**/report-charts/catalog.json', route => route.fulfill({ status: 503 }));
  await loginDemo(page);
  const board = page.locator('.widget-board');
  await expect(board.getByRole('alert')).toContainText('Не удалось загрузить каталог PDF');
  await page.unroute('**/report-charts/catalog.json');
  await board.getByRole('button', { name: 'Повторить загрузку каталога' }).click();
  await expect(board.getByRole('img', { name: /^Ряд из PDF:/ })).toBeVisible();
});

test('failed or inconsistent series never displays a chart and can be retried', async ({ page }) => {
  await page.route('**/report-charts/series/fi-monetary-policy--key-rate.json', route => route.fulfill({ json: { schema_version: 1 } }));
  await loginDemo(page);
  const board = page.locator('.widget-board');
  await expect(board.getByRole('alert')).toContainText('Не удалось загрузить ряд PDF');
  await expect(board.getByRole('img', { name: /^Ряд из PDF:/ })).toHaveCount(0);
  await page.unroute('**/report-charts/series/fi-monetary-policy--key-rate.json');
  await board.getByRole('button', { name: 'Повторить загрузку ряда' }).click();
  await expect(board.getByRole('img', { name: /^Ряд из PDF:/ })).toBeVisible();
});

test('empty report catalog has an explicit state and cannot add an empty widget', async ({ page }) => {
  await page.route('**/report-charts/series-index.json', route => route.fulfill({ json: { schema_version: 1, items: [] } }));
  await loginDemo(page);
  const board = page.locator('.widget-board');
  await expect(board).toContainText('Сохранённый ряд отсутствует в архиве');
  await board.getByRole('button', { name: 'Добавить виджет', exact: true }).click();
  await page.getByRole('button', { name: /График из PDF/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Настроить виджет' });
  await expect(dialog).toContainText('В архиве нет рядов');
  await expect(dialog.getByRole('button', { name: 'Добавить на главный экран' })).toBeDisabled();
});

test('unavailable report series preserves its provenance without a fabricated plot', async ({ page }) => {
  await loginDemo(page);
  await page.getByRole('button', { name: 'Добавить виджет', exact: true }).click();
  await page.getByRole('button', { name: /График из PDF/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Настроить виджет' });
  await dialog.getByLabel('График PDF', { exact: true }).selectOption('fi-ofz-investors');
  await dialog.getByLabel('Ряд PDF', { exact: true }).selectOption('fi-ofz-investors--other');
  await expect(dialog).toContainText('Числовой ряд недоступен');
  await expect(dialog.getByRole('img', { name: /^Ряд из PDF:/ })).toHaveCount(0);
  await expect(dialog.getByRole('link', { name: 'JSON ряда' })).toHaveAttribute('href', '/report-charts/series/fi-ofz-investors--other.json');
});

test('report catalog loading does not show sample market data', async ({ page }) => {
  let release: () => void = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/report-charts/series-index.json', async route => { await pending; await route.continue(); });
  await loginDemo(page);
  const board = page.locator('.widget-board');
  await expect(board.getByRole('status', { name: '' }).filter({ hasText: 'Загружаем каталог PDF' })).toBeVisible();
  await expect(board.locator('.widget-number')).toHaveCount(0);
  release();
  await expect(board.getByRole('img', { name: /^Ряд из PDF:/ })).toBeVisible();
});

test('broken SVG has a retry action and never leaves a broken image', async ({ page }) => {
  await page.route('**/report-charts/series/fi-monetary-policy--key-rate.svg', route => route.fulfill({ status: 503 }));
  await loginDemo(page);
  const board = page.locator('.widget-board');
  await expect(board.getByRole('alert')).toContainText('Не удалось загрузить график PDF');
  await expect(board.getByRole('img', { name: /^Ряд из PDF:/ })).toHaveCount(0);
  await page.unroute('**/report-charts/series/fi-monetary-policy--key-rate.svg');
  await board.getByRole('button', { name: 'Повторить загрузку ряда' }).click();
  await expect(board.getByRole('img', { name: /^Ряд из PDF:/ })).toBeVisible();
});
