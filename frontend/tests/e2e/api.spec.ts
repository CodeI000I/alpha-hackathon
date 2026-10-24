import { expect, test, type Page, type Route } from '@playwright/test';
import { monitorBrowserErrors } from './helpers';

const API_ROLE = {
  id: 1,
  code: 'cfo',
  name: 'Финансовый директор',
  question: 'Как событие повлияет на финансы?',
  focus: 'Денежный поток и риски',
  elements: ['finance.revenue'],
};

const API_STRATEGY_ROLE = {
  id: 2,
  code: 'strategy',
  name: 'Директор по стратегии и развитию',
  question: 'Какие рыночные возможности открываются?',
  focus: 'Рост и конкурентная среда',
  elements: ['strategy.markets'],
};

const API_USER = {
  id: 41,
  companyId: 9,
  email: 'api-user@example.test',
  fullName: 'Алексей Серверов',
  roles: ['cfo'],
  createdAt: '2026-10-20T08:00:00Z',
};

const API_COMPANY = {
  id: 9,
  inn: '7707083893',
  ogrn: '1027700067328',
  name: 'ООО «АПИ Контракт»',
  profile: { 'finance.revenue': '125000000' },
  createdAt: '2026-10-20T08:00:00Z',
  updatedAt: '2026-10-22T08:00:00Z',
};

const PROFILE_ELEMENTS = [{
  code: 'finance.revenue',
  block: 'Финансы',
  name: 'Выручка',
  description: 'Выручка компании',
  purpose: 'Контекст для финансового ракурса',
}];

const API_FEED = [{
  id: 501,
  role: 'cfo',
  kind: 'risk',
  score: 0.78,
  insight: 'Пересмотрите ставки в финансовой модели.',
  elements: ['finance.revenue'],
  news: {
    id: 901,
    sourceId: 'api-source-901',
    url: 'https://example.test/api-source-901',
    title: 'Сервер передал изменение ставки',
    summary: 'Проверяемое сообщение из API.',
    publishedAt: new Date().toISOString(),
  },
  createdAt: new Date().toISOString(),
  readAt: null,
}];

const EXISTING_FILE = {
  id: 70,
  companyId: 9,
  filename: 'budget-api.xlsx',
  contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  sizeBytes: 4096,
  createdAt: '2026-10-22T08:00:00Z',
};

interface MockOptions {
  roles?: typeof API_ROLE[] | null;
  feed?: typeof API_FEED | null;
  feedFailure?: { status: number; message: string };
}

function summaryFeed(): typeof API_FEED {
  return ['risk', 'risk', 'opportunity', 'opportunity'].map((kind, index) => ({
    ...structuredClone(API_FEED[0]), id: 601 + index, kind, score: .95 - index * .1,
    news: { ...API_FEED[0].news, id: 1001 + index, title: ['Партнёр изменил условия оплаты', 'Обновлены сроки поставки', 'Открыта новая программа поддержки', 'Представлены локальные комплектующие'][index] },
  }));
}

interface MockState {
  requests: string[];
  unknown: string[];
  roleBodies: unknown[];
  uploadContentTypes: string[];
  uploadBodies: Buffer[];
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installApiMocks(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    requests: [],
    unknown: [],
    roleBodies: [],
    uploadContentTypes: [],
    uploadBodies: [],
  };
  let user = structuredClone(API_USER);
  let files = [EXISTING_FILE];

  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    state.requests.push(`${method} ${path}${url.search}`);

    if (method === 'GET' && path === '/api/v1/roles') {
      return json(route, options.roles === undefined ? [API_ROLE, API_STRATEGY_ROLE] : options.roles);
    }
    if (method === 'GET' && path === '/api/v1/profile-elements') {
      return json(route, PROFILE_ELEMENTS);
    }
    if (method === 'GET' && path === '/api/v1/users/41') {
      return json(route, user);
    }
    if (method === 'PUT' && path === '/api/v1/users/41/roles') {
      const body = request.postDataJSON() as { roles?: string[] };
      state.roleBodies.push(body);
      user = { ...user, roles: Array.isArray(body.roles) ? body.roles : [] };
      return json(route, user);
    }
    if (method === 'GET' && path === '/api/v1/users/41/feed') {
      if (options.feedFailure) {
        return json(route, { error: options.feedFailure.message }, options.feedFailure.status);
      }
      return json(route, options.feed === undefined ? API_FEED : options.feed);
    }
    if (method === 'GET' && path === '/api/v1/companies/9') {
      return json(route, API_COMPANY);
    }
    if (method === 'GET' && path === '/api/v1/companies/9/files') {
      return json(route, files);
    }
    if (method === 'POST' && path === '/api/v1/companies/9/files') {
      state.uploadContentTypes.push(request.headers()['content-type'] ?? '');
      state.uploadBodies.push(request.postDataBuffer() ?? Buffer.alloc(0));
      const uploaded = {
        id: 71,
        companyId: 9,
        filename: 'api-contract.txt',
        contentType: 'text/plain',
        sizeBytes: 23,
        createdAt: '2026-10-22T12:00:00Z',
      };
      files = [...files, uploaded];
      return json(route, uploaded, 201);
    }

    state.unknown.push(`${method} ${path}`);
    return json(route, { error: `Unexpected API request: ${method} ${path}` }, 500);
  });

  return state;
}

async function openApiSession(page: Page, path = '/dashboard') {
  await page.goto('/landing');
  await page.evaluate(() => localStorage.setItem('signal.session.v2.api.userId', '41'));
  await page.goto(path);
  await expect(page.getByRole('button', { name: 'Меню пользователя' })).toBeVisible();
}

let browserErrors: string[] = [];
let expectedHttpStatuses: number[] = [];

test.beforeEach(async ({ context }) => {
  browserErrors = monitorBrowserErrors(context);
  expectedHttpStatuses = [];
});

test.afterEach(() => {
  const unexpected = browserErrors.filter(error => !expectedHttpStatuses.some(status =>
    error.startsWith('Failed to load resource: the server responded with a status of ' + status + ' ')));
  expect(unexpected, 'unexpected browser console and runtime errors').toEqual([]);
});

test('restores the four-event overview design at desktop, tablet, mobile and low height', async ({ page }) => {
  const state = await installApiMocks(page, { feed: summaryFeed() });
  await openApiSession(page);
  const summary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  const refresh = page.getByRole('button', { name: 'Обновить события' });
  await expect(refresh).toHaveText('');
  await expect(refresh.locator('svg')).toHaveAttribute('width', '20');
  await expect(refresh.locator('svg')).toHaveAttribute('aria-hidden', 'true');
  await expect(refresh.locator('svg path')).toHaveCount(2);
  await expect(summary.locator('.daily-total')).toHaveText('4');
  await expect(summary.getByRole('button', { name: '2 риска', exact: true })).toBeVisible();
  await expect(summary.getByRole('button', { name: '2 возможности', exact: true })).toBeVisible();
  await expect(summary.locator('.daily-trend-down')).toBeVisible();
  await expect(summary.locator('.daily-trend-up')).toBeVisible();
  await expect(summary.locator('.daily-trend-down')).toHaveCSS('color', 'rgb(231, 139, 130)');
  await expect(summary.locator('.daily-trend-up')).toHaveCSS('color', 'rgb(134, 199, 173)');
  await expect(summary.locator('.daily-segment-risk')).toHaveCSS('flex-grow', '2');
  await expect(summary.locator('.daily-segment-opportunity')).toHaveCSS('flex-grow', '2');
  await expect(summary.locator('.daily-story')).toHaveCount(2);
  await expect(summary).toContainText('Требует внимания');
  await expect(summary).toContainText('Открывает возможности');
  await expect(summary.locator('.daily-focus')).toContainText(API_ROLE.focus);
  await expect(summary).not.toContainText('Поставки меняются. Есть альтернативы.');
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }, { width: 768, height: 400 }]) {
    await page.setViewportSize(viewport);
    await summary.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const headingBox = (await page.getByRole('heading', { name: 'События для вас', exact: true }).boundingBox())!;
    const controlsBox = (await page.locator('.feed-refresh').boundingBox())!;
    expect(controlsBox.x - headingBox.x - headingBox.width).toBeCloseTo(16, 0);
    expect(Math.abs(controlsBox.y + controlsBox.height / 2 - headingBox.y - headingBox.height / 2)).toBeLessThan(1);
    await expect(summary.locator('.daily-story').first()).toBeVisible();
    await expect(summary.locator('.daily-next-action')).toBeVisible();
    if (viewport.width === 1440) await page.screenshot({ path: 'node_modules/.cache/summary-final-desktop.png' });
    await page.screenshot({ path: `node_modules/.cache/summary-restored-${viewport.width}-${viewport.height}.png`, fullPage: true });
  }
  await summary.getByText('О сводке', { exact: true }).click();
  await expect(summary).toContainText('последние 200 записей');
  await expect(summary).toContainText('Это не резюме ИИ');
  expect(state.unknown).toEqual([]);
});

test('shows all three real types, deduplicates news across roles and excludes old, future and unassigned items', async ({ page }) => {
  const values = summaryFeed();
  values[2].kind = 'event';
  values[3].news.publishedAt = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
  const future = { ...structuredClone(values[3]), id: 610, news: { ...values[3].news, id: 1010, publishedAt: new Date(Date.now() + 3600_000).toISOString() } };
  const otherRole = { ...structuredClone(values[0]), id: 611, role: 'strategy', score: 1, kind: 'opportunity' };
  const unassigned = { ...structuredClone(values[0]), id: 612, role: 'not-assigned', news: { ...values[0].news, id: 1012 } };
  await installApiMocks(page, { feed: [...values, future, otherRole, unassigned] });
  await page.route('**/api/v1/users/41', route => json(route, { ...API_USER, roles: ['cfo', 'strategy'] }));
  await openApiSession(page);
  const summary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  await expect(summary.locator('.daily-total')).toHaveText('3');
  await expect(summary.getByRole('button', { name: '1 риск', exact: true })).toBeVisible();
  await expect(summary.getByRole('button', { name: '1 возможность', exact: true })).toBeVisible();
  await expect(summary.getByRole('button', { name: '1 событие', exact: true })).toBeVisible();
  await expect(summary.locator('.daily-balance-bar i')).toHaveCount(3);
  await expect(summary.locator('.daily-next-action')).toHaveAttribute('href', '/news/611');
  await expect(page.locator('.w-event')).toHaveCount(5);
});

test('counts the active role consistently and offers an explicit switch for a missing category', async ({ page }) => {
  const values = summaryFeed().slice(0, 3);
  values[0].role = 'strategy'; values[0].kind = 'opportunity';
  values[2].kind = 'event';
  await installApiMocks(page, { feed: [...values, { ...values[0], id: 700, role: 'unassigned' }] });
  await page.route('**/api/v1/users/41', route => json(route, { ...API_USER, roles: ['strategy', 'cfo'] }));
  await openApiSession(page);
  await expect(page.locator('.daily-total')).toHaveText('3');
  await expect(page.locator('.feed-refresh > span')).toHaveText('1 из 1');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await page.getByRole('button', { name: 'Риски', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Для этой роли рисков нет' })).toBeVisible();
  await expect(page.locator('.state-panel')).toContainText('Финансовый директор');
  await expect(page.locator('.feed-refresh > span')).toHaveText('0 из 1');
  await page.getByRole('button', { name: 'Показать риски', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveValue('cfo');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.locator('.feed-refresh > span')).toHaveText('1 из 2');
  await page.getByRole('button', { name: 'Все', exact: true }).click();
  await expect(page.locator('.feed-refresh > span')).toHaveText('2 из 2');
  await expect(page.locator('.w-event')).toHaveCount(2);
  await expect(page.locator('.daily-total')).toHaveText('3');
});

test('summary segments highlight matching categories, align numbers and support keyboard filtering', async ({ page }) => {
  const values = summaryFeed().slice(0, 3);
  values[1].kind = 'event';
  await installApiMocks(page, { feed: values });
  await openApiSession(page);
  const summary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  const balance = summary.locator('.daily-balance');
  for (const kind of ['risk', 'opportunity', 'event']) {
    const segment = summary.locator('.daily-segment-' + kind);
    await segment.hover();
    await expect(balance).toHaveAttribute('data-highlighted-kind', kind);
    await expect(summary.locator('.daily-count-' + kind)).toHaveClass(/is-highlighted/);
    await expect(summary.locator('.daily-counts .is-muted')).toHaveCount(2);
    await expect(summary.locator('.daily-counts .is-muted svg').first()).toHaveCSS('color', 'rgb(119, 119, 131)');
    await expect(summary.locator('.daily-balance-bar .is-muted > i').first()).toHaveCSS('background-color', 'rgb(119, 119, 131)');
    if (kind === 'risk') await summary.screenshot({ path: 'node_modules/.cache/summary-hover-risk.png' });
  }
  await page.getByRole('heading', { name: 'Обзор событий' }).hover();
  await expect(balance).not.toHaveAttribute('data-highlighted-kind', /.+/);
  const starts = await summary.locator('.daily-counts button').evaluateAll(buttons => buttons.map(button => {
    const textNode = [...button.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent?.trim());
    const range = document.createRange(); range.selectNodeContents(textNode!);
    return range.getBoundingClientRect().x;
  }));
  expect(Math.max(...starts) - Math.min(...starts)).toBeLessThan(1);
  await expect(summary.locator('.daily-event-icon')).toHaveAttribute('width', '18');
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await summary.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const buttons = await summary.locator('.daily-balance-bar button').all();
    for (const button of buttons) {
      expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(24);
      await expect(button).toBeVisible();
    }
    await summary.screenshot({ path: `node_modules/.cache/summary-three-types-${viewport.width}.png` });
  }
  await summary.locator('.daily-segment-risk').focus();
  await expect(balance).toHaveAttribute('data-highlighted-kind', 'risk');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Риски', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'События для вас' })).toBeFocused();
});

test('manual refresh shows progress and confirms unchanged data without hiding API errors', async ({ page }) => {
  const options: MockOptions = {};
  await installApiMocks(page, options);
  await openApiSession(page);
  await expect(page.locator('.w-event')).toHaveCount(1);
  const refresh = page.getByRole('button', { name: 'Обновить события' });
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const holdResponse = async (route: Route) => { await gate; await json(route, API_FEED); };
  await page.route('**/api/v1/users/41/feed?*', holdResponse);
  await refresh.click();
  await expect(refresh).toBeDisabled();
  await expect(refresh).toHaveAttribute('aria-busy', 'true');
  release();
  await expect(page.locator('.feed-refresh-notice')).toHaveText('Лента актуальна');
  await expect(refresh).toBeEnabled();
  await page.unroute('**/api/v1/users/41/feed?*', holdResponse);
  expectedHttpStatuses = [503]; options.feedFailure = { status: 503, message: 'не удалось обновить данные' };
  await refresh.click();
  await expect(page.getByRole('alert')).toContainText('Обновление ленты не удалось');
  await expect(page.locator('.feed-refresh-notice')).toHaveCount(0);
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(refresh).toBeEnabled();
});

test('keeps an empty overview compact and refreshes when the backend finishes preparing events', async ({ page }) => {
  const feed: typeof API_FEED = [];
  const state = await installApiMocks(page, { feed });
  await openApiSession(page);
  const summary = page.getByRole('region', { name: 'Сводка за 24 часа' });
  await expect(summary).toContainText('За сутки новых событий нет');
  await expect(summary.locator('.daily-balance')).toHaveCount(0);
  await expect(summary.locator('.daily-story')).toHaveCount(0);
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect((await summary.boundingBox())!.height).toBeLessThan(300);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `node_modules/.cache/summary-empty-${viewport.width}.png`, fullPage: true });
  }
  const requestsBeforeRefresh = state.requests.filter(value => value.includes('/feed?limit=200')).length;
  feed.push(...API_FEED);
  await page.getByRole('button', { name: 'Обновить события' }).click();
  await expect(summary.locator('.daily-total')).toHaveText('1');
  await expect(page.locator('.w-event')).toHaveCount(1);
  await expect(page.locator('.feed-refresh-notice')).toHaveText('Лента обновлена');
  expect(state.requests.filter(value => value.includes('/feed?limit=200'))).toHaveLength(requestsBeforeRefresh + 1);
  expect(state.unknown).toEqual([]);
});

test('rechecks an empty API feed four times then stops without inventing an analysis status', async ({ page }) => {
  await page.clock.install();
  const state = await installApiMocks(page, { feed: [] });
  await openApiSession(page);
  await expect(page.getByRole('heading', { name: 'За сутки новых событий нет' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Обновить события' })).toBeEnabled();
  const initialRequests = state.requests.filter(value => value.includes('/feed?limit=200')).length;
  for (let attempt = 0; attempt < 4; attempt++) {
    const response = page.waitForResponse(value => value.url().includes('/feed?limit=200'));
    await page.clock.fastForward(15001);
    await (await response).finished();
    await expect.poll(() => state.requests.filter(value => value.includes('/feed?limit=200')).length).toBe(initialRequests + attempt + 1);
    await expect(page.getByRole('button', { name: 'Обновить события' })).toBeEnabled();
  }
  await page.clock.fastForward(60000);
  expect(state.requests.filter(value => value.includes('/feed?limit=200'))).toHaveLength(initialRequests + 4);
  await expect(page.getByText('Анализ завершён', { exact: true })).toHaveCount(0);
});

test('an empty active role refreshes even when other assigned roles already have events', async ({ page }) => {
  await page.clock.install();
  const feed = structuredClone(API_FEED);
  const state = await installApiMocks(page, { feed });
  await page.route('**/api/v1/users/41', route => json(route, { ...API_USER, roles: ['cfo', 'strategy'] }));
  await openApiSession(page);
  await expect(page.locator('.w-event')).toHaveCount(1);
  await page.getByRole('combobox', { name: 'Ваша роль' }).selectOption('strategy');
  await expect(page.getByRole('heading', { name: 'Для этой роли пока нет событий' })).toBeVisible();
  feed.push({ ...structuredClone(API_FEED[0]), id: 502, role: 'strategy', news: { ...API_FEED[0].news, id: 902, title: 'Новое событие для стратегии' } });
  const response = page.waitForResponse(value => value.url().includes('/feed?limit=200'));
  await page.clock.fastForward(15001);
  await (await response).finished();
  await expect(page.getByRole('heading', { name: 'Новое событие для стратегии' })).toBeVisible();
  await expect(page.locator('.daily-total')).toHaveText('2');
  expect(state.unknown).toEqual([]);
});

test('an HTML response is an API error, not a fabricated empty overview', async ({ page }) => {
  await installApiMocks(page);
  await page.route('**/api/v1/users/41/feed?*', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Proxy fallback</title>' }));
  await openApiSession(page);
  await expect(page.getByRole('heading', { name: 'Лента не загрузилась' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Сводка за 24 часа' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'В ленте пока нет событий' })).toHaveCount(0);
});

test('sources do not claim an interpretation when the API did not provide one', async ({ page }) => {
  await installApiMocks(page, { feed: [{ ...API_FEED[0], insight: '' }] });
  await openApiSession(page, '/news/501');
  await page.getByRole('button', { name: 'Источники и основания', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Источники и основания' });
  await expect(dialog).toContainText('Интерпретация не передана.');
  await expect(dialog).not.toContainText('Для разбора доступна интерпретация события.');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('source and Alfa analytics blocks keep their icons, balanced edges and keyboard access', async ({ page }) => {
  await installApiMocks(page);
  await openApiSession(page, '/news/501');
  const source = page.getByRole('button', { name: /^Источник:/ });
  await expect(source.locator('.source-logo svg')).toBeVisible();
  await expect(page.locator('.signal-feed-detail .w-bank-icon')).toHaveText('А');
  await expect(page.locator('.signal-feed-detail .w-bank')).toContainText('Аналитика от Альфа-Банка');
  await expect(page.locator('.signal-feed-detail .w-bank')).toContainText('не переданы сервером');
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }, { width: 390, height: 400 }]) {
    await page.setViewportSize(viewport);
    await source.click();
    const dialog = page.getByRole('dialog', { name: 'Источники и основания' });
    await expect(dialog.locator('.w-bank-icon')).toHaveText('А');
    await expect(dialog).toContainText('Аналитика от Альфа-Банка');
    const dialogBox = (await dialog.boundingBox())!;
    const bankBox = (await dialog.locator('.w-source-bank-card').boundingBox())!;
    expect(Math.abs(bankBox.x - dialogBox.x - (dialogBox.x + dialogBox.width - bankBox.x - bankBox.width))).toBeLessThan(2);
    await dialog.locator('.w-source-bank-card').scrollIntoViewIfNeeded();
    const close = dialog.getByRole('button', { name: 'Закрыть источники' });
    await expect(close).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `node_modules/.cache/source-dialog-final-${viewport.width}-${viewport.height}.png` });
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(source).toBeFocused();
  }
});

test('API mode exposes no fictitious password login', async ({ page }) => {
  const state = await installApiMocks(page);
  await page.goto('/login');

  await expect(page.getByRole('heading', { name: 'Войти в аккаунт', level: 1 })).toBeVisible();
  await expect(page.getByText('Вход в существующий аккаунт пока недоступен. Вы можете зарегистрировать новый профиль.')).toBeVisible();
  await expect(page.getByLabel('Электронная почта')).toHaveCount(0);
  await expect(page.getByLabel('Пароль тестового аккаунта')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Перейти к регистрации' })).toHaveAttribute('href', '/register');
  expect(state.requests).toEqual([]);
});

test('normalizes null role and feed collections without demo fallback', async ({ page }) => {
  const state = await installApiMocks(page, { roles: null, feed: null });
  await openApiSession(page);

  await expect(page.getByRole('heading', { name: 'В ленте пока нет событий' })).toBeVisible();
  await expect(page.getByText(API_FEED[0].news.title, { exact: true })).toHaveCount(0);
  expect(state.requests.some(value => value === 'GET /api/v1/roles')).toBe(true);
  expect(state.requests.some(value => value === 'GET /api/v1/users/41/feed?limit=200')).toBe(true);
  expect(state.unknown).toEqual([]);
});

test('shows an API feed failure instead of silently substituting fixtures', async ({ page }) => {
  expectedHttpStatuses = [503];
  const state = await installApiMocks(page, { feedFailure: { status: 503, message: 'лента временно недоступна' } });
  await openApiSession(page);

  await expect(page.getByRole('heading', { name: 'Лента не загрузилась' })).toBeVisible();
  await expect(page.getByText('лента временно недоступна', { exact: true })).toBeVisible();
  await expect(page.getByText(API_FEED[0].news.title, { exact: true })).toHaveCount(0);
  expect(state.requests.some(value => value === 'GET /api/v1/users/41/feed?limit=200')).toBe(true);
  expect(state.unknown).toEqual([]);
});

test('updates assigned roles through the exact PUT contract', async ({ page }) => {
  const state = await installApiMocks(page);
  await openApiSession(page, '/profile?tab=roles');

  await page.getByRole('button', { name: 'Изменить роли' }).click();
  await page.getByRole('checkbox', { name: /Директор по стратегии и развитию/ }).check({ force: true });
  await page.getByRole('button', { name: 'Сохранить роли' }).click();

  await expect(page.getByRole('status')).toContainText('Роли сохранены');
  expect(state.roleBodies).toEqual([{ roles: ['cfo', 'strategy'] }]);
  expect(state.unknown).toEqual([]);
});

test('role cancellation sends no PUT and failed saves retry while honoring the server response', async ({ page }) => {
  expectedHttpStatuses = [503];
  const state = await installApiMocks(page);
  const requests: unknown[] = [];
  let actualUser = structuredClone(API_USER);
  await page.route('**/api/v1/users/41', route => json(route, actualUser));
  await page.route('**/api/v1/users/41/roles', async route => {
    expect(route.request().method()).toBe('PUT');
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) return json(route, { error: 'сохранение временно недоступно' }, 503);
    actualUser = { ...actualUser, roles: ['strategy'] };
    return json(route, actualUser);
  });
  await openApiSession(page, '/profile?tab=roles');
  const trigger = page.getByRole('button', { name: 'Изменить роли' });
  const dialog = page.getByRole('dialog', { name: 'Роли в компании', exact: true });
  const strategy = dialog.getByRole('checkbox', { name: /Директор по стратегии и развитию/ });
  await trigger.click();
  await strategy.check({ force: true });
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  expect(requests).toEqual([]);
  await trigger.click();
  await expect(strategy).not.toBeChecked();
  await strategy.check({ force: true });
  await dialog.getByRole('button', { name: 'Сохранить роли', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('сохранение временно недоступно');
  await expect(strategy).toBeChecked();
  await dialog.getByRole('button', { name: 'Сохранить роли', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  expect(requests).toEqual([{ roles: ['cfo', 'strategy'] }, { roles: ['cfo', 'strategy'] }]);
  await trigger.click();
  await expect(strategy).toBeChecked();
  await expect(dialog.getByRole('checkbox', { name: /^Финансовый директор/ })).not.toBeChecked();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Обзор', exact: true }).click();
  await expect(page.getByRole('option', { name: 'Финансовый директор', exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Ваша роль' })).toHaveCount(0);
  await expect(page.locator('.w-topbar')).toContainText('Директор по стратегии и развитию');
  await expect(page.getByRole('heading', { name: API_FEED[0].news.title })).toHaveCount(0);
  expect(state.unknown).toEqual([]);
});

test('uploads a document as multipart to the mocked API and never contacts a live Go server', async ({ page }) => {
  const state = await installApiMocks(page);
  await openApiSession(page, '/profile?tab=documents');
  await expect(page.getByText('budget-api.xlsx', { exact: true })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: 'api-contract.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('API multipart contract'),
  });

  await expect(page.locator('.signal-upload-result.is-success')).toContainText('Загружен');
  await expect(page.getByText('api-contract.txt', { exact: true })).toHaveCount(2);
  expect(state.uploadContentTypes).toHaveLength(1);
  expect(state.uploadContentTypes[0]).toMatch(/^multipart\/form-data;\s*boundary=/i);
  expect(state.uploadBodies).toHaveLength(1);
  const multipart = state.uploadBodies[0].toString('utf8');
  expect(multipart).toContain('name="file"');
  expect(multipart).toContain('filename="api-contract.txt"');
  expect(multipart).toContain('API multipart contract');
  expect(state.unknown).toEqual([]);
});

test('creates no account on step one and resumes company creation after a partial API failure', async ({ page }) => {
  expectedHttpStatuses = [503];
  const state = await installApiMocks(page);
  const companies: unknown[] = [];
  const users: unknown[] = [];
  await page.route('**/api/v1/companies', async route => {
    expect(route.request().method()).toBe('POST');
    companies.push(route.request().postDataJSON());
    return json(route, API_COMPANY, 201);
  });
  await page.route('**/api/v1/users', async route => {
    expect(route.request().method()).toBe('POST');
    users.push(route.request().postDataJSON());
    return users.length === 1
      ? json(route, { error: 'создание пользователя временно недоступно' }, 503)
      : json(route, API_USER, 201);
  });
  await page.goto('/register');
  await page.getByLabel('Как вас зовут').fill('  Алексей Серверов  ');
  await page.getByLabel('Электронная почта').fill('api-user@example.test');
  expect(companies).toEqual([]);
  expect(users).toEqual([]);
  expect(state.requests).toEqual([]);
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await page.getByLabel('Название компании').fill(API_COMPANY.name);
  await page.getByLabel('ИНН компании').fill(API_COMPANY.inn);
  await page.getByRole('checkbox', { name: /^Финансовый директор/ }).check({ force: true });
  await page.getByRole('button', { name: 'Завершить настройку' }).click();
  await expect(page.getByRole('alert')).toContainText('создание пользователя временно недоступно');
  expect(companies).toEqual([{ name: API_COMPANY.name, inn: API_COMPANY.inn }]);
  expect(users).toEqual([{ fullName: API_USER.fullName, email: API_USER.email, companyId: 9, roles: ['cfo'] }]);
  expect(await page.evaluate(() => localStorage.getItem('signal.session.v2.api.userId'))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem('signal.session.v2.api.pendingCompanyId'))).toBe('9');

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Настройте профиль' })).toBeVisible();
  await expect(page.getByText(/Компания уже создана:/)).toContainText(API_COMPANY.name);
  await expect(page.getByLabel('Название компании')).toHaveCount(0);
  await page.getByRole('button', { name: 'Завершить настройку' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(companies).toHaveLength(1);
  expect(users).toHaveLength(2);
  expect(users[1]).toEqual(users[0]);
  expect(await page.evaluate(() => localStorage.getItem('signal.session.v2.api.pendingCompanyId'))).toBeNull();
  expect(await page.evaluate(() => sessionStorage.getItem('signal.registration-draft.v1.api'))).toBeNull();
  expect(state.unknown).toEqual([]);
});

test('a deleted pending company blocks submission and can be reset explicitly', async ({ page }) => {
  expectedHttpStatuses = [404];
  const state = await installApiMocks(page);
  await page.route('**/api/v1/companies/666', route => json(route, { error: 'not found' }, 404));
  await page.goto('/landing');
  await page.evaluate(() => {
    localStorage.setItem('signal.session.v2.api.pendingCompanyId', '666');
    sessionStorage.setItem('signal.registration-draft.v1.api', JSON.stringify({
      step: 2,
      form: { fullName: 'Алексей Серверов', email: 'api-user@example.test', companyName: 'Старая компания', inn: '7707083893' },
      selectedRoles: ['cfo'],
    }));
  });
  await page.goto('/register');
  await expect(page.getByRole('alert')).toContainText('Сохранённая компания больше не найдена');
  await expect(page.getByRole('button', { name: 'Завершить настройку' })).toBeDisabled();
  expect(state.requests.filter(request => request.startsWith('POST '))).toEqual([]);
  await page.getByRole('button', { name: 'Начать настройку компании заново' }).click();
  await expect(page.getByLabel('Название компании')).toHaveValue('Старая компания');
  expect(await page.evaluate(() => localStorage.getItem('signal.session.v2.api.pendingCompanyId'))).toBeNull();
  expect(state.unknown).toEqual([]);
});

test('loads a direct real-ID report, handles absent sources, and exports provenance', async ({ page }) => {
  const record = structuredClone(API_FEED[0]);
  record.news.sourceId = '';
  record.news.url = '';
  record.elements = null as unknown as string[];
  const state = await installApiMocks(page, { feed: [record] });
  await openApiSession(page, '/news/501');
  await expect(page.getByRole('heading', { name: record.news.title, level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Источник:/ })).toHaveCount(0);
  await expect(page.getByText('Сведения об использовании аналитики Альфа-Банка не переданы сервером.', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('14 − 9 = 5')).toHaveCount(0);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: /Скачать разбор TXT/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('signal-501.txt');
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  if (stream) for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const text = Buffer.concat(chunks).toString('utf8');
  expect(text).toContain('Что произошло [Сообщение источника / news.summary]');
  expect(text).toContain(record.news.summary);
  expect(text).toContain('Значение для бизнеса [Интерпретация / insight]');
  expect(text).toContain(record.insight);
  expect(text).toContain('Источник: не указан');
  expect(text).toContain('Компания: ' + API_COMPANY.name);
  expect(text).toContain('Материал носит информационно-аналитический характер и не является инвестиционной рекомендацией');
  expect(text).not.toContain('ДЕМО: синтетические данные');
  await page.reload();
  await expect(page.getByRole('heading', { name: record.news.title, level: 1 })).toBeVisible();
  await page.goto('/news/999999');
  await expect(page.getByRole('heading', { name: 'Событие не найдено' })).toBeVisible();
  expect(state.requests.some(request => request === 'GET /api/v1/users/41/feed?limit=200')).toBe(true);
  expect(state.unknown).toEqual([]);
});

test('server upload failures remain visible and retry the same multipart endpoint', async ({ page }) => {
  expectedHttpStatuses = [503];
  const state = await installApiMocks(page);
  let failedOnce = false;
  await page.route('**/api/v1/companies/9/files', async route => {
    if (route.request().method() !== 'POST' || failedOnce) return route.fallback();
    failedOnce = true;
    return json(route, { error: 'хранилище временно недоступно' }, 503);
  });
  await openApiSession(page, '/profile?tab=documents');
  await page.locator('input[type="file"]').setInputFiles({ name: 'api-contract.txt', mimeType: 'text/plain', buffer: Buffer.from('API multipart contract') });
  await expect(page.locator('.signal-upload-result.is-error')).toContainText('хранилище временно недоступно');
  await page.getByRole('button', { name: 'Повторить загрузку' }).click();
  await expect(page.locator('.signal-upload-result.is-success')).toContainText('Загружен');
  expect(state.uploadContentTypes).toHaveLength(1);
  expect(state.unknown).toEqual([]);
});

test('handles a user with no company and null roles without requesting company methods', async ({ page }) => {
  const state = await installApiMocks(page, { feed: null });
  await page.route('**/api/v1/users/41', route => json(route, { ...API_USER, companyId: null, roles: null }));
  await openApiSession(page, '/profile?tab=documents');
  await expect(page.getByRole('heading', { name: 'Компания не указана' })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  expect(state.requests.filter(request => request.includes('/companies/'))).toEqual([]);
  expect(state.unknown).toEqual([]);
});

test('retains cached real feed data and labels a failed refresh', async ({ page }) => {
  expectedHttpStatuses = [503];
  const state = await installApiMocks(page);
  let fail = false;
  await page.route('**/api/v1/users/41/feed?*', route => fail
    ? json(route, { error: 'обновление недоступно' }, 503)
    : route.fallback());
  await openApiSession(page);
  await expect(page.getByRole('heading', { name: API_FEED[0].news.title })).toBeVisible();
  await page.clock.install();
  await page.clock.fastForward(31_000);
  await page.getByRole('link', { name: 'Личный кабинет', exact: true }).click();
  fail = true;
  await page.getByRole('link', { name: 'Обзор', exact: true }).click();
  await page.clock.fastForward(2_000);
  await expect(page.getByRole('alert')).toContainText('Обновление ленты не удалось');
  await expect(page.getByRole('heading', { name: API_FEED[0].news.title })).toBeVisible();
  expect(state.unknown).toEqual([]);
});

test('rejects unsupported and oversized documents before an API upload', async ({ page }) => {
  const state = await installApiMocks(page);
  await openApiSession(page, '/profile?tab=documents');
  await page.locator('input[type="file"]').setInputFiles([
    { name: 'unsafe.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('not a supported document') },
    { name: 'too-large.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(10 * 1024 * 1024 + 1) },
  ]);
  await expect(page.locator('.signal-upload-result.is-error')).toHaveCount(2);
  await expect(page.getByText('Допустимы только PDF, TXT, DOCX и XLSX.', { exact: true })).toBeVisible();
  await expect(page.getByText('Файл больше 10 МБ. Выберите файл меньшего размера.', { exact: true })).toBeVisible();
  expect(state.uploadContentTypes).toEqual([]);
  expect(state.unknown).toEqual([]);
});
