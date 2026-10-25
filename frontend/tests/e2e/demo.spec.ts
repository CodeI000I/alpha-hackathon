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
  await expect(page.getByRole('heading', { name: 'Доступный остаток', exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Создать платёж' }).click();
  await expect(page.getByRole('status')).toContainText('Банковские операции здесь недоступны');

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
  await page.getByRole('textbox', { name: 'Пароль', exact: true }).fill('not-a-demo-password');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('alert')).toContainText('Неверная электронная почта или пароль');
});

for (const account of ['finance', 'operations'] as const) {
  test(`logs into the exact ${account} demo account and shows its own company scenario`, async ({ page }) => {
    const expected = await loginDemo(page, account);

    await expect(page.getByText(expected.company, { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: account === 'finance' ? 'Расширена программа поддержки технологических компаний' : 'Производитель представил локальную замену импортным комплектующим' })).toBeVisible();
    const storedUserId = await page.evaluate(() => localStorage.getItem('signal.session.v2.demo.userId'));
    expect(storedUserId).toBe(account === 'finance' ? '1' : '2');
  });
}

test('completes the required two-step company and role setup with a password', async ({ page }) => {
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
  await page.getByLabel('Пароль · не менее 10 символов').fill('demo-registration-password');
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
  const summary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  await summary.getByText('О сводке', { exact: true }).click();
  await expect(summary).toContainText('События подготовлены для примера и не отражают актуальную ленту.');
  await expect(page.locator('.w-event')).toHaveCount(1);

  const dailySummary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  await expect(dailySummary.locator('.daily-total')).toHaveText('3');
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('cfo');
  await expect(page.locator('.w-event')).toHaveCount(2);
  await expect(dailySummary.locator('.daily-total')).toHaveText('3');
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('strategy');
  await expect(page.locator('.w-event')).toHaveCount(1);

  await page.getByLabel('Поиск по событиям').fill('программа поддержки');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'Расширена программа поддержки технологических компаний' })).toBeVisible();

  await page.getByLabel('Поиск по событиям').fill('');
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('cfo');
  await page.getByRole('button', { name: 'Риски', exact: true }).click();
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event })).toBeVisible();

  await page.getByRole('button', { name: 'Все', exact: true }).click();
  const eventCard = page.locator('.w-event').filter({ hasText: DEMO_ACCOUNTS.finance.event });
  await eventCard.getByRole('button', { name: 'Сохранить в закладки' }).click();
  await page.getByRole('link', { name: /Закладки/ }).click();
  await expect(page).toHaveURL(/\/dashboard\?saved=1$/);
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event })).toBeVisible();

  await page.reload();
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Убрать из закладок' })).toBeVisible();
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
      if (path === '/bank.html') await expect(page.getByRole('heading', { name: 'Доступный остаток', exact: true })).toBeVisible();
      else await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
      if (path === '/dashboard') await expect(page.locator('.w-event')).toHaveCount(1);
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
  await page.locator('.w-event').first().getByRole('button', { name: 'Сохранить в закладки' }).click();
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('cfo');
  await page.getByRole('button', { name: 'Как это влияет на мою роль?' }).click();
  await expect(page.locator('.w-message-user')).toHaveCount(1);
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('strategy');
  await expect(page.locator('.w-message-user')).toHaveCount(0);
  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await loginDemo(page, 'operations');
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveValue('procurement');
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
  await expect(page.getByRole('heading', { name: 'Доступный остаток', exact: true })).toBeVisible();
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
  const sendButton = page.getByRole('button', { name: 'Отправить' });
  await input.focus();
  await page.locator('dialog.w-source-dialog').dispatchEvent('close');
  await expect(input).toBeFocused();
  await page.keyboard.type('Что проверить?');
  await expect(input).toHaveValue('Что проверить?');
  await expect(sendButton).toBeEnabled();
  await page.keyboard.press('Tab');
  await expect(sendButton).toBeFocused();
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
  await expect(page.getByRole('option', { name: 'Все роли', exact: true })).toHaveCount(0);
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

test('header shows a named role, preserves its choice, and falls back after that role is removed', async ({ page }) => {
  await loginDemo(page, 'finance');
  const header = page.locator('.w-topbar');
  const selector = header.getByRole('combobox', { name: 'Ваша роль' });
  await expect(selector).toHaveValue('strategy');
  await expect(selector.getByRole('option')).toHaveText(['Директор по стратегии и развитию', 'Финансовый директор']);
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveCount(1);
  await expect(page.getByRole('option', { name: 'Все роли', exact: true })).toHaveCount(0);
  await expect(page.locator('.signal-page-heading select')).toHaveCount(0);
  await expect(page.locator('.w-sidebar-bottom').getByRole('link', { name: /роли/ })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Сводка за 24 часа' }).getByRole('link', { name: 'Мои роли' })).toHaveCount(0);

  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 520 }]) {
    await page.setViewportSize(viewport);
    await expect(selector).toBeVisible();
    const roleBox = await selector.boundingBox();
    const avatarBox = await header.getByRole('button', { name: 'Меню пользователя' }).boundingBox();
    const headerBox = await header.boundingBox();
    expect(roleBox!.x + roleBox!.width).toBeLessThanOrEqual(avatarBox!.x);
    expect(roleBox!.y).toBeGreaterThanOrEqual(headerBox!.y);
    expect(roleBox!.y + roleBox!.height).toBeLessThanOrEqual(headerBox!.y + headerBox!.height);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: `node_modules/.cache/header-role-${viewport.width}.png` });
  }

  await selector.selectOption('cfo');
  await expect(page.locator('.w-event')).toHaveCount(2);
  await expect(page.locator('.daily-total')).toHaveText('3');
  await page.reload();
  await expect(selector).toHaveValue('cfo');
  await page.goto('/profile?tab=roles');
  await expect(selector).toHaveValue('cfo');
  await page.getByRole('button', { name: 'Изменить роли' }).click();
  const dialog = page.getByRole('dialog', { name: 'Роли в компании', exact: true });
  await dialog.getByRole('checkbox', { name: /^Финансовый директор/ }).uncheck({ force: true });
  await dialog.getByRole('button', { name: 'Сохранить роли' }).click();
  await expect(dialog).toBeHidden();
  await expect(selector).toHaveCount(0);
  await expect(header).toContainText('Директор по стратегии и развитию');
  await page.goto('/dashboard');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.locator('.daily-total')).toHaveText('1');
  await expect(page.getByRole('heading', { name: DEMO_ACCOUNTS.finance.event })).toHaveCount(0);
  await page.reload();
  await expect(header).toContainText('Директор по стратегии и развитию');
  expect(await page.evaluate(() => localStorage.getItem('alpha.insights.v2.demo.company.1.user.1.activeRole'))).toBe('"strategy"');
});

test('summary arrows filter real events across roles and clear incompatible local filters', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.getByRole('link', { name: /Закладки/ }).click();
  await page.getByLabel('Поиск по событиям').fill('нет совпадений');

  const summary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  await expect(summary.locator('.daily-trend-down')).toBeVisible();
  await expect(summary.locator('.daily-trend-up')).toBeVisible();
  await summary.getByRole('button', { name: '1 риск', exact: true }).focus();
  await page.keyboard.press('Enter');

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveValue('cfo');
  await expect(page.getByLabel('Поиск по событиям')).toHaveValue('');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'События для вас' })).toBeFocused();
  await expect(summary.locator('.daily-total')).toHaveText('3');
  await expect(summary.locator('.daily-focus')).toContainText('Ключевая ставка');

  await summary.getByRole('link', { name: /Самый релевантный разбор/ }).click();
  await expect(page).toHaveURL(/\/news\/\d+$/);
  await expect(page.locator('.w-detail h1')).toBeVisible();
});

test('profile role editing is a small gray pencil action beside the role heading', async ({ page }) => {
  await loginDemo(page, 'finance');
  await page.goto('/profile?tab=roles');
  const row = page.locator('.profile-role-summary-heading');
  const trigger = row.getByRole('button', { name: 'Изменить роли' });
  await expect(trigger).toHaveText('Изменить');
  await expect(trigger.locator('svg')).toBeVisible();
  await expect(trigger).toHaveCSS('font-size', '12px');
  await expect(trigger).toHaveCSS('color', 'rgb(170, 170, 180)');
  await expect(trigger).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  const chips = page.locator('.profile-current-roles');
  const chip = chips.getByRole('listitem').first();
  await expect(chips).toHaveCSS('margin-top', '8px');
  await expect(chips).toHaveCSS('margin-bottom', '0px');
  await expect(page.locator('.profile-role-summary')).toHaveCSS('padding-top', '16px');
  await expect(chip.locator('button, a, input, [tabindex]')).toHaveCount(0);
  await expect(chip).not.toHaveAttribute('tabindex');
  await expect(chip).toHaveCSS('cursor', 'default');
  const selectedRole = await page.getByRole('combobox', { name: 'Ваша роль' }).inputValue();
  await chip.click();
  await expect(page.getByRole('dialog', { name: 'Роли в компании', exact: true })).toBeHidden();
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveValue(selectedRole);
  await chip.hover();
  await expect(chip).toHaveCSS('background-color', 'rgb(77, 51, 54)');
  await expect(chip).toHaveCSS('color', 'rgb(255, 170, 163)');
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 520 }]) {
    await page.setViewportSize(viewport);
    const heading = await row.getByRole('heading').boundingBox();
    const action = await trigger.boundingBox();
    expect(action!.height).toBeGreaterThanOrEqual(32);
    expect(action!.width).toBeLessThan(120);
    expect(Math.abs(action!.y - heading!.y)).toBeLessThan(55);
    const chipsBox = await chips.boundingBox();
    const nextSectionBox = await page.locator('.profile-demo-section').boundingBox();
    expect(nextSectionBox!.y - chipsBox!.y - chipsBox!.height).toBeCloseTo(22, 0);
    await row.scrollIntoViewIfNeeded();
    await chip.hover();
    await expect(chip).toHaveCSS('background-color', 'rgb(77, 51, 54)');
    await page.screenshot({ path: `node_modules/.cache/role-spacing-hover-${viewport.width}.png` });
    await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog', { name: 'Роли в компании', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
  }
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
  await expect(page.locator('.widget-catalog-card')).toHaveCount(8);
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

test('bank solutions keep the small red letter from widgets and stay below the analytics heading', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginDemo(page, 'finance');
  const widgetLabel = page.locator('.market-widget > .bank-offers > .bank-offers-label').first();
  const widgetMark = widgetLabel.locator('.bank-offers-mark');
  const reference = await widgetMark.evaluate(element => {
    const style = getComputedStyle(element);
    return { color: style.color, background: style.backgroundColor, fontSize: style.fontSize };
  });
  await page.goto('/news/101');
  const offers = page.locator('.signal-feed-detail > .bank-offers');
  const label = offers.locator(':scope > .bank-offers-label');
  const mark = label.locator('.bank-offers-mark');
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(label).toContainText('Решения Альфа-Банка');
    await expect(label).toHaveCSS('font-size', '12px');
    await expect(page.locator('#analysis-bank-title')).toHaveCSS('font-size', '20px');
    await expect(mark).toHaveText('А');
    await expect(mark).toHaveCSS('color', reference.color);
    await expect(mark).toHaveCSS('background-color', reference.background);
    await expect(mark).toHaveCSS('font-size', reference.fontSize);
    await expect(mark).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    expect((await mark.boundingBox())!.height).toBeLessThan(20);
    await page.locator('.signal-feed-detail > .w-bank').evaluate(element => window.scrollTo(0, scrollY + element.getBoundingClientRect().top - 100));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `node_modules/.cache/solutions-hierarchy-${viewport.width}.png` });
  }
  const trigger = page.getByRole('button', { name: 'Посмотреть финансирование', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Овердрафт и кредитная линия' });
  await expect(dialog.locator('.bank-offers-mark')).toHaveCSS('color', reference.color);
  await expect(dialog.locator('.bank-offers-mark')).toHaveCSS('background-color', reference.background);
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('interface omits demo badges and profile codes while keeping local-feature explanations', async ({ page }) => {
  await loginDemo(page, 'finance');
  const paths = ['/dashboard', '/news/101', '/profile?tab=roles', '/profile?tab=company', '/profile?tab=keywords', '/profile?tab=documents', '/landing', '/bank.html'];
  for (const path of paths) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
    await page.locator('details.data-note').evaluateAll(details => details.forEach(detail => { detail.setAttribute('open', ''); }));
    expect(await page.locator('body').innerText(), path).not.toMatch(/демо/i);
    await expect(page.locator('.ui-badge--demo, .w-demo, .bank-demo-label')).toHaveCount(0);
    if (path === '/dashboard') {
      await expect(page.locator('.w-card-foot')).not.toContainText(/Контекст|Элементы профиля|Б[0-9]|С[0-9]/);
      await expect(page.getByText('Серверные бизнес-ситуации в этом режиме недоступны.', { exact: false })).toBeVisible();
      await expect(page.getByText('Здесь используются подготовленные ответы, а не аналитика ИИ.', { exact: false })).toBeVisible();
      const reportWidget = page.locator('.widget-board .report-widget').first();
      await expect(reportWidget.getByText('Архивный отчёт · не текущие котировки', { exact: true })).toBeVisible();
      await expect(reportWidget).toContainText('FI_Strategy_3Q26_22072026.pdf');
      await reportWidget.locator('details').evaluate(detail => detail.setAttribute('open', ''));
      await expect(reportWidget.getByText(/Оценка погрешности ±.+не является гарантией точности/)).toBeVisible();
    }
  }
});

test('saved chat answers lose only the old presentation prefix without rewriting history', async ({ page }) => {
  await loginDemo(page, 'finance');
  const key = 'alpha.insights.v2.demo.company.1.user.1.chat:101';
  const history = [{ question: 'Что обсудить с командой?', answer: 'Демо-подсказка: обсудите первоисточник с командой. Документы компании не анализировались.' }];
  await page.evaluate(({ key, history }) => localStorage.setItem(key, JSON.stringify(history)), { key, history });
  await page.goto('/news/101');
  await expect(page.locator('.w-message-answer')).toHaveText('Обсудите первоисточник с командой. Документы компании не анализировались.');
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? '[]'), key)).toEqual(history);
});

test('fixed account refresh gives feedback and its role counter never mixes the three summary events', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginDemo(page, 'finance');
  await expect(page.locator('.daily-total')).toHaveText('3');
  await expect(page.locator('.feed-refresh > span')).toHaveText('1 из 1');
  await page.screenshot({ path: 'node_modules/.cache/signal-final-overview.png' });
  await page.locator('.daily-segment-risk').hover();
  await expect(page.locator('.daily-count-opportunity')).toHaveClass(/is-muted/);
  await page.locator('.daily-summary').screenshot({ path: 'node_modules/.cache/signal-final-summary-hover.png' });
  await page.getByRole('button', { name: 'Обновить события' }).click();
  await expect(page.locator('.feed-refresh-notice')).toHaveText('Лента без изменений');
  await expect(page.locator('.feed-refresh > span')).toHaveText('1 из 1');
  await page.getByRole('button', { name: 'Риски', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Для этой роли рисков нет' })).toBeVisible();
  await page.getByRole('button', { name: 'Показать риски', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveValue('cfo');
  await expect(page.locator('.feed-refresh > span')).toHaveText('1 из 2');
  await expect(page.getByRole('heading', { name: 'Банк России сохранил ключевую ставку', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Все', exact: true }).click();
  await expect(page.locator('.feed-refresh > span')).toHaveText('2 из 2');
});
