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

test('API mode exposes no fictitious password login', async ({ page }) => {
  const state = await installApiMocks(page);
  await page.goto('/login');

  await expect(page.getByRole('heading', { name: 'Войти в аккаунт', level: 1 })).toBeVisible();
  await expect(page.getByText('Серверный вход пока не подключён.')).toBeVisible();
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

  await page.getByRole('checkbox', { name: /Директор по стратегии и развитию/ }).check({ force: true });
  await page.getByRole('button', { name: 'Сохранить роли' }).click();

  await expect(page.getByRole('status')).toContainText('Роли сохранены');
  expect(state.roleBodies).toEqual([{ roles: ['cfo', 'strategy'] }]);
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
  await expect(page.getByRole('heading', { name: 'Компания не привязана' })).toBeVisible();
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
