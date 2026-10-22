import { expect, test } from '@playwright/test';
import { DEMO_ACCOUNTS, DEMO_PASSWORD, loginDemo, monitorBrowserErrors } from './helpers';

let browserErrors: string[] = [];
let serverRequests: string[] = [];

test.beforeEach(async ({ context }) => {
  browserErrors = monitorBrowserErrors(context);
  serverRequests = [];
  context.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) serverRequests.push(request.url()); });
});

test.afterEach(() => {
  expect(browserErrors, 'browser console and runtime errors').toEqual([]);
  expect(serverRequests, 'demo mode must not send API requests').toEqual([]);
});

test('bank demo opens registration in an isolated new tab', async ({ page, context }) => {
  await page.goto('/bank.html');
  await expect(page.getByText('Демонстрационный прототип', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Создать платёж' }).click();
  await expect(page.getByRole('status')).toContainText('Банковские операции недоступны в демоверсии');

  const nextPagePromise = context.waitForEvent('page');
  await page.getByRole('link', { name: 'Сигнал — откроется в новой вкладке' }).click();
  const nextPage = await nextPagePromise;
  await nextPage.waitForLoadState('domcontentloaded');

  await expect(nextPage).toHaveURL(/\/register$/);
  await expect(nextPage.getByRole('heading', { name: 'Создать аккаунт', level: 1 })).toBeVisible();
  expect(await nextPage.evaluate(() => window.opener)).toBeNull();
});

test('rejects arbitrary demo credentials', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Электронная почта').fill('someone@example.test');
  await page.getByLabel('Пароль тестового аккаунта').fill('not-a-demo-password');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('alert')).toContainText('Неверная электронная почта или пароль');
});

for (const account of ['finance', 'operations'] as const) {
  test(`logs into the exact ${account} demo account and shows its own company scenario`, async ({ page }) => {
    const expected = await loginDemo(page, account);

    await expect(page.getByText(expected.company, { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: expected.event })).toBeVisible();
    const storedUserId = await page.evaluate(() => localStorage.getItem('signal.session.v2.demo.userId'));
    expect(storedUserId).toBe(account === 'finance' ? '1' : '2');
  });
}

test('completes the required two-step company and role setup without a password', async ({ page }) => {
  await page.goto('/register');
  await expect(page.getByText('Шаг 1 из 2 · Данные пользователя', { exact: true })).toBeVisible();
  await page.getByLabel('Как вас зовут').fill('Анна Петрова');
  await page.getByLabel('Электронная почта').fill('anna@example.test');
  await expect(page.getByLabel('Название компании')).toHaveCount(0);
  await page.getByRole('button', { name: 'Продолжить' }).click();

  await expect(page.getByRole('heading', { name: 'Настройте профиль', level: 1 })).toBeFocused();
  await expect(page.getByText('Шаг 2 из 2 · Компания и роли', { exact: true })).toBeVisible();
  await page.getByLabel('Название компании').fill('ООО «Новый профиль»');
  await page.getByLabel('ИНН компании').fill('7707083893');
  await page.getByRole('checkbox', { name: /Финансовый директор/ }).check({ force: true });
  await page.getByRole('checkbox', { name: /Директор по стратегии и развитию/ }).check({ force: true });
  await page.getByRole('button', { name: 'Завершить настройку' }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText('ООО «Новый профиль»', { exact: true })).toBeVisible();
  await expect(page.getByRole('option', { name: 'Финансовый директор' })).toBeAttached();
  await expect(page.getByRole('option', { name: 'Директор по стратегии и развитию' })).toBeAttached();
  await expect(page.getByRole('heading', { name: 'В ленте пока нет событий' })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem('signal.registration-draft.v1.demo'))).toBeNull();
});

test('restores and then clears the local demo session', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Обзор событий', level: 1 })).toBeVisible();

  await page.goto('/profile?tab=company');
  await expect(page.getByRole('heading', { name: 'Личный кабинет', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();

  await expect(page).toHaveURL(/\/login$/);
  expect(await page.evaluate(() => localStorage.getItem('signal.session.v2.demo.userId'))).toBeNull();
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/register$/);
});

test('filters, searches, and persists local bookmarks', async ({ page }) => {
  await loginDemo(page, 'finance');
  await expect(page.locator('.w-event')).toHaveCount(3);

  const dailySummary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  await expect(dailySummary.locator('.daily-balance > strong')).toHaveText('3');
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('cfo');
  await expect(page.locator('.w-event')).toHaveCount(2);
  await expect(dailySummary.locator('.daily-balance > strong')).toHaveText('3');
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('');
  await expect(page.locator('.w-event')).toHaveCount(3);

  await page.getByLabel('Поиск по событиям').fill('программа поддержки');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'Расширена программа поддержки технологических компаний' })).toBeVisible();

  await page.getByLabel('Поиск по событиям').fill('');
  await page.getByRole('button', { name: 'Риски', exact: true }).click();
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event })).toBeVisible();

  await page.getByRole('button', { name: 'Все', exact: true }).click();
  const eventCard = page.locator('.w-event').filter({ hasText: DEMO_ACCOUNTS.finance.event });
  await eventCard.getByRole('button', { name: 'Сохранить в закладки (демо)' }).click();
  await page.getByRole('link', { name: /Закладки/ }).click();
  await expect(page).toHaveURL(/\/dashboard\?saved=1$/);
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event })).toBeVisible();

  await page.reload();
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Убрать из закладок (демо)' })).toBeVisible();
});

test('removing an assigned role updates the feed and role selection persists', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.goto('/profile?tab=roles');
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await page.getByRole('button', { name: 'Изменить роли' }).click();

  const strategy = page.getByRole('checkbox', { name: /Директор по стратегии и развитию/ });
  const cfo = page.getByRole('checkbox', { name: /^Финансовый директор/ });
  await expect(strategy).toBeChecked();
  await expect(cfo).toBeChecked();
  await strategy.uncheck({ force: true });
  await page.getByRole('button', { name: 'Сохранить роли' }).click();
  await expect(page.getByRole('status')).toContainText('Роли сохранены');

  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Расширена программа поддержки технологических компаний' })).toHaveCount(0);

  await page.goto('/profile?tab=roles');
  await page.getByRole('button', { name: 'Изменить роли' }).click();
  await expect(strategy).not.toBeChecked();
  await expect(cfo).toBeChecked();
});

test('uploads and restores a browser-local demo document', async ({ page }) => {
  await loginDemo(page, 'operations');
  await page.goto('/profile?tab=documents');
  await expect(page.getByRole('heading', { name: 'Документы компании', exact: true })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: 'план-поставок-ноябрь.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('local demo document'),
  });
  await expect(page.locator('.signal-upload-result.is-success')).toContainText('Загружен');
  const uploadedDocument = page.locator('.signal-document').filter({ hasText: 'план-поставок-ноябрь.pdf' });
  await expect(uploadedDocument).toBeVisible();

  await page.reload();
  await expect(uploadedDocument).toBeVisible();
});

test('detail source dialog restores focus on Escape and local chat persists', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.goto('/news/101');
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event, level: 1 })).toBeVisible();

  const sourceTrigger = page.getByRole('button', { name: /Источник: S015/ });
  await sourceTrigger.click();
  const sourceDialog = page.getByRole('dialog', { name: 'Источники и основания' });
  await expect(sourceDialog).toBeVisible();
  await expect(sourceDialog.getByRole('link', { name: /Открыть первоисточник/ })).toHaveAttribute('href', 'https://www.cbr.ru/press/keypr/');
  await page.keyboard.press('Escape');
  await expect(sourceDialog).toBeHidden();
  await expect(sourceTrigger).toBeFocused();

  await page.getByRole('button', { name: 'Какие данные нужно проверить?' }).click();
  await expect(page.getByText(/проверьте первоисточник.*сроки и действующие обязательства/i)).toBeVisible();
  await page.reload();
  await expect(page.locator('.w-message-user')).toContainText('Какие данные нужно проверить?');
  await expect(page.getByText(/проверьте первоисточник.*сроки и действующие обязательства/i)).toBeVisible();
});

test('key pages have no horizontal overflow at desktop, tablet, mobile, and low height', async ({ page }) => {
  await loginDemo(page, 'finance');
  const viewports = [
    { width: 1440, height: 900 },
    { width: 768, height: 900 },
    { width: 390, height: 844 },
    { width: 390, height: 520 },
    { width: 1440, height: 500 },
  ];
  const paths = ['/landing', '/dashboard', '/news/101', '/profile?tab=documents', '/bank.html'];

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    for (const path of paths) {
      await page.goto(path);
      if (path === '/bank.html') await expect(page.getByText('Демонстрационный прототип', { exact: true })).toBeVisible();
      else await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
      if (path === '/dashboard') await expect(page.locator('.w-event')).toHaveCount(3);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
        `${path} should fit ${viewport.width}×${viewport.height}`,
      ).toBe(true);
    }
  }
});

test('registration validates identity first, restores its draft, and cannot skip required setup', async ({ page }) => {
  await page.goto('/register');
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect(page.getByLabel('Как вас зовут')).toBeFocused();
  await page.getByLabel('Как вас зовут').fill('Ирина Настройка');
  await page.getByLabel('Электронная почта').fill('irina@example.test');
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await page.getByLabel('Название компании').fill('ООО Черновик');
  await page.getByLabel('ИНН компании').fill('7707083893');
  await page.getByRole('button', { name: 'Назад к данным пользователя' }).click();
  await expect(page.getByLabel('Как вас зовут')).toHaveValue('Ирина Настройка');
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect(page.getByLabel('Название компании')).toHaveValue('ООО Черновик');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Настройте профиль' })).toBeVisible();
  await expect(page.getByLabel('Название компании')).toHaveValue('ООО Черновик');
  await page.getByRole('button', { name: 'Завершить настройку' }).click();
  await expect(page.getByText('Выберите хотя бы одну роль.', { exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('signal.session.v2.demo.userId'))).toBeNull();
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole('heading', { name: 'Настройте профиль' })).toBeVisible();
});

test('saved items and role-scoped chats never carry into another demo company', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.locator('.w-event').first().getByRole('button', { name: 'Сохранить в закладки (демо)' }).click();
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('cfo');
  await page.getByRole('button', { name: 'Как это влияет на мою роль?' }).click();
  await expect(page.locator('.w-message-user')).toHaveCount(1);
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('strategy');
  await expect(page.locator('.w-message-user')).toHaveCount(0);
  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await loginDemo(page, 'operations');
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveValue('');
  await expect(page.locator('.w-message-user')).toHaveCount(0);
  await page.getByRole('link', { name: /Закладки/ }).click();
  await expect(page.locator('.w-event')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Ничего не найдено' })).toBeVisible();
});

test('legacy hash routes retain real event IDs and the bank remains a separate document', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.goto('/#/feed/101');
  await expect(page).toHaveURL(/\/news\/101$/);
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event, level: 1 })).toBeVisible();
  await page.goto('/#/news');
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto('/#/company?tab=analytics');
  await expect(page).toHaveURL(/\/profile\?tab=company$/);
  await expect(page.getByRole('heading', { name: 'Аналитика компании' })).toBeVisible();
  await page.goto('/#/bank');
  await expect(page).toHaveURL(/\/bank\.html$/);
  await expect(page.getByText('Демонстрационный прототип', { exact: true })).toBeVisible();
});

test('source modal and chat composer remain keyboard reachable in a low window', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 500 });
  await loginDemo(page, 'finance');
  await page.goto('/news/101');
  const sourceTrigger = page.getByRole('button', { name: 'Источники и основания', exact: true });
  await sourceTrigger.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Источники и основания' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'К разбору новости' })).toBeFocused();
  const modalHeader = dialog.locator('.w-source-header');
  const before = await modalHeader.boundingBox();
  await dialog.locator('.w-source-content').evaluate(el => { el.scrollTop = el.scrollHeight; });
  const after = await modalHeader.boundingBox();
  expect(Math.round(after!.y)).toBe(Math.round(before!.y));
  await page.keyboard.press('Escape');
  await expect(sourceTrigger).toBeFocused();
  const input = page.getByRole('textbox', { name: 'Вопрос по событию' });
  await input.focus();
  await page.keyboard.type('Что проверить?');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Отправить' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('.w-message-user')).toContainText('Что проверить?');
});

test('test credentials are collapsed by default and remain available on request', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByText(DEMO_ACCOUNTS.finance.email, { exact: true })).toBeHidden();
  await page.getByText('Тестовые аккаунты', { exact: true }).click();
  await expect(page.getByText(DEMO_ACCOUNTS.finance.email, { exact: true })).toBeVisible();
  await expect(page.getByText(DEMO_ACCOUNTS.operations.email, { exact: true })).toBeVisible();
  await expect(page.getByText(DEMO_PASSWORD, { exact: true })).toHaveCount(2);
});

test('auth screens stay concise and both home links lead to Signal, not the bank demo', async ({ page }) => {
  for (const path of ['/register', '/login']) {
    await page.goto(path);
    await expect(page.locator('.auth-mode, .auth-note, .auth-intro')).toHaveCount(0);
    await expect(page.getByText('Деморежим', { exact: true })).toHaveCount(0);
    await expect(page.locator('.auth-box > .w-brand')).toHaveAttribute('href', '/landing');
    await page.getByRole('link', { name: 'На главную', exact: true }).click();
    await expect(page).toHaveURL(/\/landing$/);
    await page.goto(path);
    await page.locator('.auth-box > .w-brand').click();
    await expect(page).toHaveURL(/\/landing$/);
  }
});

test('avatar restores prototype sections and workspace logo returns to the Signal overview', async ({ page }) => {
  await loginDemo(page, 'finance');
  await expect(page.locator('.w-topbar').getByText('Деморежим', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Активный ракурс', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('option', { name: 'Все роли', exact: true })).toBeAttached();
  const trigger = page.getByRole('button', { name: 'Меню пользователя' });
  await trigger.click();
  const menu = page.locator('.w-profile-menu');
  await expect(menu).toBeVisible();
  for (const name of ['Личный кабинет', 'Моя роль', 'Компания', 'Ключевые слова', 'Документы']) {
    await expect(menu.getByRole('link', { name, exact: true })).toBeVisible();
  }
  await expect(menu.getByText(DEMO_ACCOUNTS.finance.email, { exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
  for (const [name, tab] of [['Моя роль', 'roles'], ['Компания', 'company'], ['Ключевые слова', 'keywords'], ['Документы', 'documents']]) {
    await trigger.click();
    await menu.getByRole('link', { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp('/profile\\?tab=' + tab + '$'));
    await expect(menu).toBeHidden();
  }
  await page.locator('.w-topbar > .w-brand').click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test('role editor is optional, discards cancelled drafts, and supports keyboard and short screens', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.goto('/profile?tab=roles');
  const trigger = page.getByRole('button', { name: 'Изменить роли' });
  const dialog = page.getByRole('dialog', { name: 'Роли в компании', exact: true });
  const strategy = dialog.getByRole('checkbox', { name: /Директор по стратегии и развитию/ });
  const cfo = dialog.getByRole('checkbox', { name: /^Финансовый директор/ });
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await trigger.click();
  await expect(dialog).toBeVisible();
  await strategy.uncheck({ force: true });
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(strategy).toBeChecked();
  await strategy.uncheck({ force: true });
  await cfo.uncheck({ force: true });
  await expect(dialog.getByRole('button', { name: 'Сохранить роли', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  for (const viewport of [{ width: 390, height: 520 }, { width: 768, height: 640 }, { width: 1440, height: 500 }]) {
    await page.setViewportSize(viewport);
    await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveCSS('padding', '0px');
    await expect(strategy).toBeChecked();
    await expect(cfo).toBeChecked();
    const rect = await dialog.boundingBox();
    expect(rect).not.toBeNull();
    expect(rect!.x).toBeGreaterThanOrEqual(0);
    expect(rect!.y).toBeGreaterThanOrEqual(0);
    expect(rect!.x + rect!.width).toBeLessThanOrEqual(viewport.width);
    expect(rect!.y + rect!.height).toBeLessThanOrEqual(viewport.height);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    for (let index = 0; index < 15; index++) {
      await page.keyboard.press('Tab');
      // Native dialogs may send one Tab stop to browser chrome (BODY), but never to background controls.
      expect(await dialog.evaluate(element => element.contains(document.activeElement) || document.activeElement === document.body)).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  }
});

test('widget catalog and bank offer dialogs close with Escape and restore their triggers', async ({ page }) => {
  await loginDemo(page, 'finance');
  const trigger = page.getByRole('button', { name: 'Добавить виджет', exact: true });
  await trigger.click();
  await expect(page.getByRole('dialog', { name: 'Добавить виджет' })).toBeVisible();
  await expect(page.locator('.widget-catalog-card')).toHaveCount(7);
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  const bankTrigger = page.getByRole('button', { name: 'Подобрать размещение', exact: true });
  await bankTrigger.click();
  const bankDialog = page.getByRole('dialog', { name: 'Депозиты и овернайт' });
  await expect(bankDialog).toBeVisible();
  await expect(bankDialog.getByText('Ставка задана для примера', { exact: false })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(bankTrigger).toBeFocused();
});
