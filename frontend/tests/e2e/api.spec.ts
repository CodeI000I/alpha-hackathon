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

function summaryFeed(): typeof API_FEED {
  return ['risk', 'risk', 'opportunity', 'opportunity'].map((kind, index) => ({
    ...structuredClone(API_FEED[0]), id: 601 + index, kind, score: .95 - index * .1,
    news: { ...API_FEED[0].news, id: 1001 + index, title: ['Партнёр изменил условия оплаты', 'Обновлены сроки поставки', 'Открыта новая программа поддержки', 'Представлены локальные комплектующие'][index] },
  }));
}

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
    if (method === 'GET' && path === '/api/v1/auth/me') return json(route, user);
    if (method === 'POST' && path === '/api/v1/auth/login') return json(route, user);
    if (method === 'POST' && path === '/api/v1/auth/logout') return route.fulfill({ status: 204 });
    if (method === 'GET' && path === '/api/v1/analytics/documents') return json(route, []);
    if (method === 'GET' && path === '/api/v1/analytics/situation') return json(route, { snapshot: null, current: false, status: 'pending' });
    if (method === 'GET' && path === '/api/v1/analytics/issues') return json(route, []);
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

test('API mode logs in and restores a cookie-backed session through auth endpoints', async ({ page }) => {
  expectedHttpStatuses = [401];
  const state = await installApiMocks(page);
  const authRequests: string[] = [];
  await page.route('**/api/v1/auth/me', route => json(route, { error: 'unauthenticated' }, 401));
  await page.route('**/api/v1/auth/login', async route => { authRequests.push(route.request().method() + ' ' + route.request().url()); return json(route, API_USER); });
  await page.goto('/login');

  await expect(page.getByRole('heading', { name: 'Войти в аккаунт', level: 1 })).toBeVisible();
  await page.getByLabel('Электронная почта').fill(API_USER.email);
  await page.getByLabel('Пароль', { exact: true }).fill('password-for-api-test');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(authRequests).toHaveLength(1);
  expect(state.unknown).toEqual([]);
});

test('keeps the session visible when server logout fails', async ({ page }) => {
  expectedHttpStatuses = [503];
  const state = await installApiMocks(page);
  await page.route('**/api/v1/auth/logout', route => json(route, { error: 'выход временно недоступен' }, 503));
  await openApiSession(page);

  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('button', { name: 'Выйти' }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('alert')).toContainText('выход временно недоступен');
  await expect(page.getByRole('button', { name: 'Меню пользователя' })).toBeVisible();
  expect(state.unknown).toEqual([]);
});

test('renders the deduplicated 24-hour overview across desktop, tablet, mobile and short screens', async ({ page }) => {
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
  }
  await summary.getByText('О сводке', { exact: true }).click();
  await expect(summary).toContainText('последние 200 записей');
  await expect(summary).toContainText('Это не резюме ИИ');
  expect(state.unknown).toEqual([]);
});

test('deduplicates role analyses and excludes old, future, and unassigned events from the overview', async ({ page }) => {
  const values = summaryFeed();
  values[2].kind = 'event';
  values[3].news.publishedAt = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
  const future = { ...structuredClone(values[3]), id: 610, news: { ...values[3].news, id: 1010, publishedAt: new Date(Date.now() + 3600_000).toISOString() } };
  const otherRole = { ...structuredClone(values[0]), id: 611, role: 'strategy', score: 1, kind: 'opportunity' as const };
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

test('keeps the empty overview compact and refreshes after the backend fills the feed', async ({ page }) => {
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
  }
  const requestsBeforeRefresh = state.requests.filter(value => value.includes('/feed?limit=200')).length;
  feed.push(...API_FEED);
  await page.getByRole('button', { name: 'Обновить события' }).click();
  await expect(summary.locator('.daily-total')).toHaveText('1');
  await expect(page.locator('.w-event')).toHaveCount(1);
  expect(state.requests.filter(value => value.includes('/feed?limit=200'))).toHaveLength(requestsBeforeRefresh + 1);
  expect(state.unknown).toEqual([]);
});

test('rechecks an empty API feed four times and stops without inventing a finished analysis', async ({ page }) => {
  await page.clock.install();
  const state = await installApiMocks(page, { feed: [] });
  await openApiSession(page);
  await expect(page.getByRole('heading', { name: 'За сутки новых событий нет' })).toBeVisible();
  const initialRequests = state.requests.filter(value => value.includes('/feed?limit=200')).length;
  for (let attempt = 0; attempt < 4; attempt++) {
    const response = page.waitForResponse(value => value.url().includes('/feed?limit=200'));
    await page.clock.fastForward(15_001);
    await (await response).finished();
    await expect.poll(() => state.requests.filter(value => value.includes('/feed?limit=200')).length).toBe(initialRequests + attempt + 1);
  }
  await page.clock.fastForward(60_000);
  expect(state.requests.filter(value => value.includes('/feed?limit=200'))).toHaveLength(initialRequests + 4);
  await expect(page.getByText('Анализ завершён', { exact: true })).toHaveCount(0);
});

test('refreshes an empty active role while other assigned roles have events', async ({ page }) => {
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
  await page.clock.fastForward(15_001);
  await (await response).finished();
  await expect(page.getByRole('heading', { name: 'Новое событие для стратегии' })).toBeVisible();
  await expect(page.locator('.daily-total')).toHaveText('2');
  expect(state.unknown).toEqual([]);
});

test('treats a successful HTML response as an API error instead of an empty overview', async ({ page }) => {
  await installApiMocks(page);
  await page.route('**/api/v1/users/41/feed?*', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Proxy fallback</title>' }));
  await openApiSession(page);
  await expect(page.getByRole('heading', { name: 'Лента не загрузилась' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Сводка за 24 часа' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'В ленте пока нет событий' })).toHaveCount(0);
});

test('does not claim an interpretation in sources when the API omitted it', async ({ page }) => {
  await installApiMocks(page, { feed: [{ ...API_FEED[0], insight: '' }] });
  await openApiSession(page, '/news/501');
  await page.getByRole('button', { name: 'Источники и основания', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Источники и основания' });
  await expect(dialog).toContainText('Интерпретация не передана.');
  await expect(dialog).not.toContainText('Для разбора доступна интерпретация события.');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
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

test('shows company situations with evidence, history, issue state, chat, and refresh job status', async ({ page }) => {
  expectedHttpStatuses = [404];
  const state = await installApiMocks(page);
  const issue = {
    issue_id: 'issue-1', title: 'Поставки компонента под риском', summary: 'Изменения могут повлиять на сроки поставок компании.',
    overall_effect: 'risk', evidence_sufficiency: 'conditional', key_unknowns: ['Неизвестен запас компонентов.'],
    conditions: ['Если сроки ограничений сохранятся.'], suggested_action: 'Уточнить резервный запас у поставщика.',
    business_factors: ['supply_availability'], exposure: 'Компания использует импортный компонент.', horizon: 'short',
    event_ids: ['event-1'], impact_ids: ['impact-1'], impact_versions: { 'impact-1': 1 }, status: 'active',
    urgency: 'soon', impact_magnitude: 'medium', version: 2, as_of: '2026-10-24T10:00:00Z',
  };
  const stateValue = { issue_id: 'issue-1', workflow: 'open', pinned: false, read_version: null, unread: true };
  const replies: Array<Record<string, unknown>> = [];
  let stateValueCurrent = stateValue;
  let jobStatus = 'completed';
  await page.route('**/api/v1/analytics/situation**', route => json(route, { snapshot: {
    snapshot_id: 'snapshot-1', as_of: '2026-10-24T10:00:00Z', overall: { summary: 'Проверьте риск задержки поставок.', actions: ['Связаться с поставщиком.'], key_unknowns: ['Срок поставки не подтверждён.'] },
    priority_issues: [], changes_since_previous: [],
  }, current: true, status: 'ready' }));
  await page.route('**/api/v1/analytics/issues?**', route => json(route, [issue]));
  await page.route('**/api/v1/analytics/issues/issue-1?**', route => json(route, issue));
  await page.route('**/api/v1/analytics/issues/issue-1/evidence**', route => json(route, [{
    event: { event_id: 'event-1', summary: 'Экспортные ограничения расширены.', evidence_quote: 'Ограничения вступают в силу в ноябре.', source_news_ids: ['news-1'], modality: 'announcement' },
    news: [{ title: 'Новые ограничения экспорта', content: 'Поставки компонента могут задержаться.', source_url: 'https://example.test/source', published_at: '2026-10-23T09:00:00Z' }],
    company_facts: [{ fact_id: 'fact-1', text: 'Компания использует импортный компонент.', source_quote: 'Доля импортных компонентов составляет 40%.', source_refs: ['budget.pdf:p.4'], verification_status: 'source_supported' }],
    chunks: [{ chunk_id: 'chunk-1', document_id: 'budget-1', locator: 'budget.pdf, стр. 4', text: 'Компания использует импортный компонент в ключевом продукте.' }],
    candidate_paths: [{ path_id: 'path-1', node_ids: ['supplier', 'component'], relation_types: ['supplies'], evidence_refs: ['fact-1'], status: 'supported' }],
  }]));
  await page.route('**/api/v1/analytics/issues/issue-1/history**', route => json(route, [{ ...issue, version: 1, summary: 'Предыдущая версия ситуации.' }, issue]));
  await page.route('**/api/v1/analytics/issues/issue-1/state**', async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON() as { workflow: string; pinned: boolean; mark_read?: boolean };
      stateValueCurrent = { ...stateValueCurrent, ...body, read_version: body.mark_read ? issue.version : stateValueCurrent.read_version, unread: false };
      return json(route, stateValueCurrent);
    }
    return json(route, stateValueCurrent);
  });
  await page.route('**/api/v1/analytics/conversations/**', route => replies.length
    ? json(route, { issue_id: 'issue-1', issue_version: issue.version, replies })
    : json(route, { detail: 'not found' }, 404));
  await page.route('**/api/v1/analytics/issues/issue-1/questions**', async route => {
    const body = route.request().postDataJSON() as { question: string; request_id: string };
    const reply = { request_id: body.request_id, question: body.question, answer: { text: 'Проверьте сроки и договорные условия.', evidence_ids: ['fact-1'], missing_facts: ['Сроки поставщика'] }, created_at: '2026-10-24T10:10:00Z' };
    replies.push(reply);
    return json(route, reply);
  });
  await page.route('**/api/v1/analytics/refresh**', route => json(route, { job_id: 'job-1', status: 'queued' }, 202));
  await page.route('**/api/v1/analytics/jobs/job-1**', route => json(route, { job_id: 'job-1', status: jobStatus }));

  await openApiSession(page);
  await expect(page.getByText('Проверьте риск задержки поставок.')).toBeVisible();
  await expect(page.getByRole('link', { name: /Поставки компонента под риском/ })).toBeVisible();
  await page.getByRole('button', { name: 'Обновить анализ' }).click();
  await expect(page.getByText('Обновление: завершено')).toBeVisible();
  await page.getByRole('link', { name: /Поставки компонента под риском/ }).click();
  await expect(page.getByRole('heading', { name: 'Поставки компонента под риском', level: 1 })).toBeVisible();
  await expect(page.getByText('Ограничения вступают в силу в ноябре.')).toBeVisible();
  await page.getByText('Факт компании · source_supported').click();
  await expect(page.getByText('Доля импортных компонентов составляет 40%.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'История изменений' })).toBeVisible();
  await page.getByRole('button', { name: 'Закрепить ситуацию' }).click();
  await expect(page.getByRole('button', { name: 'Снять закрепление' })).toBeVisible();
  await page.getByLabel('Вопрос об этой ситуации').fill('Какие сроки стоит проверить?');
  await page.getByRole('button', { name: 'Задать вопрос' }).click();
  await expect(page.getByText('Проверьте сроки и договорные условия.')).toBeVisible();
  expect(replies).toHaveLength(1);
  expect(state.unknown).toEqual([]);
});

test('starts a fresh pinned conversation when the issue version has changed', async ({ page }) => {
  expectedHttpStatuses = [404];
  const state = await installApiMocks(page);
  const staleConversationId = 'conversation-v1';
  const postedQuestions: Array<{ question: string; conversation_id: string; request_id: string; version: number }> = [];
  const newReplies: Array<Record<string, unknown>> = [];
  await page.addInitScript(() => {
    localStorage.setItem('alpha.insights.v2.api.company.9.user.41.issue-chat-issue-versioned-cfo', JSON.stringify('conversation-v1'));
  });
  const issue = {
    issue_id: 'issue-versioned', title: 'Ситуация с новой версией', summary: 'Обновлённый разбор.',
    overall_effect: 'risk', evidence_sufficiency: 'conditional', key_unknowns: [], conditions: [], suggested_action: 'Проверить изменения.',
    business_factors: [], exposure: '', horizon: 'short', event_ids: [], impact_ids: [], impact_versions: {}, status: 'active',
    urgency: 'soon', impact_magnitude: 'medium', version: 2, as_of: '2026-10-24T10:00:00Z',
  };
  await page.route('**/api/v1/analytics/issues/issue-versioned?**', route => json(route, issue));
  await page.route('**/api/v1/analytics/issues/issue-versioned/evidence**', route => json(route, []));
  await page.route('**/api/v1/analytics/issues/issue-versioned/history**', route => json(route, [issue]));
  await page.route('**/api/v1/analytics/issues/issue-versioned/state**', route => json(route, { issue_id: issue.issue_id, workflow: 'open', pinned: false, read_version: 2, unread: false }));
  await page.route('**/api/v1/analytics/conversations/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/' + staleConversationId)) {
      return json(route, { issue_id: issue.issue_id, issue_version: 1, replies: [] });
    }
    if (newReplies.length) return json(route, { issue_id: issue.issue_id, issue_version: 2, replies: newReplies });
    return json(route, { detail: 'not found' }, 404);
  });
  await page.route('**/api/v1/analytics/issues/issue-versioned/questions**', async route => {
    postedQuestions.push(route.request().postDataJSON() as typeof postedQuestions[number]);
    const reply = { request_id: postedQuestions.at(-1)?.request_id, question: postedQuestions.at(-1)?.question, answer: { text: 'Ответ для версии 2.', evidence_ids: [], missing_facts: [] }, created_at: '2026-10-24T10:10:00Z' };
    newReplies.push(reply);
    return json(route, reply);
  });

  await page.goto('/issues/issue-versioned');
  await expect(page.getByRole('heading', { name: issue.title, level: 1 })).toBeVisible();
  await expect(page.getByText(/Этот диалог относится к версии 1/)).toBeVisible();
  await expect(page.getByLabel('Вопрос об этой ситуации')).toBeDisabled();
  await page.getByRole('button', { name: 'Начать новый диалог для версии 2' }).click();
  await expect(page.getByText('Новый диалог для версии 2')).toBeVisible();
  const question = page.getByLabel('Вопрос об этой ситуации');
  await expect(question).toBeEnabled();
  await question.fill('Что изменилось?');
  await page.getByRole('button', { name: 'Задать вопрос' }).click();
  await expect(page.getByText('Ответ для версии 2.')).toBeVisible();
  expect(postedQuestions).toHaveLength(1);
  expect(postedQuestions[0]).toMatchObject({ question: 'Что изменилось?', version: 2 });
  expect(postedQuestions[0].conversation_id).not.toBe(staleConversationId);
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

test('shows server document analysis status and retries failed files through a role-scoped job', async ({ page }) => {
  const state = await installApiMocks(page);
  const refreshBodies: unknown[] = [];
  await page.route('**/api/v1/analytics/documents?**', route => json(route, [
    { file_id: 'file-1', filename: 'budget-api.xlsx', document_id: 'doc-1', status: 'failed', attempts: 2, error: 'Не удалось извлечь текст', retry_at: null },
  ]));
  await page.route('**/api/v1/analytics/refresh?**', async route => {
    refreshBodies.push(route.request().postDataJSON());
    return json(route, { job_id: 'retry-job', status: 'queued' }, 202);
  });
  await page.route('**/api/v1/analytics/jobs/retry-job?**', route => json(route, { job_id: 'retry-job', status: 'completed' }));

  await openApiSession(page, '/profile?tab=documents');
  await expect(page.getByText('Ошибка анализа', { exact: true })).toBeVisible();
  await expect(page.getByText('Не удалось извлечь текст')).toBeVisible();
  await page.getByRole('button', { name: 'Повторить сбойные' }).click();
  await expect(page.getByText('Повторная обработка: завершена')).toBeVisible();
  expect(refreshBodies).toEqual([{ reason: 'retry_failed_documents', retry_failed: true }]);
  expect(state.unknown).toEqual([]);
});

test('onboarding retries the atomic endpoint with a persisted key and never stores the password', async ({ page }) => {
  expectedHttpStatuses = [401, 503];
  const state = await installApiMocks(page);
  const requests: Array<{ key: string | undefined; body: unknown }> = [];
  await page.route('**/api/v1/auth/me', route => json(route, { error: 'unauthenticated' }, 401));
  await page.route('**/api/v1/onboarding', async route => {
    requests.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() });
    return requests.length === 1
      ? json(route, { error: 'результат регистрации пока не подтверждён' }, 503)
      : json(route, { company: API_COMPANY, user: API_USER }, 201);
  });

  await page.goto('/register');
  await page.getByLabel('Как вас зовут').fill('  Алексей Серверов  ');
  await page.getByLabel('Электронная почта').fill('api-user@example.test');
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await page.getByLabel('Название компании').fill(API_COMPANY.name);
  await page.getByLabel('ИНН компании').fill(API_COMPANY.inn);
  await page.getByLabel(/Пароль/).fill('password-for-api-test');
  await page.getByRole('checkbox', { name: /^Финансовый директор/ }).check({ force: true });
  await page.getByRole('button', { name: 'Завершить настройку' }).click();
  await expect(page.getByRole('alert')).toContainText('результат регистрации пока не подтверждён');
  const key = requests[0].key;
  expect(key).toMatch(/^[0-9a-f-]{36}$/i);
  expect(await page.evaluate(() => localStorage.getItem('signal.registration-request.v1.api'))).toBe(key);
  expect(await page.evaluate(() => sessionStorage.getItem('signal.registration-draft.v1.api'))).not.toContain('password-for-api-test');

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Настройте профиль' })).toBeVisible();
  await page.getByLabel(/Пароль/).fill('password-for-api-test');
  await page.getByRole('button', { name: 'Завершить настройку' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(requests).toHaveLength(2);
  expect(requests[1].key).toBe(key);
  expect(requests[1].body).toEqual({
    company: { name: API_COMPANY.name, inn: API_COMPANY.inn },
    user: { fullName: API_USER.fullName, email: API_USER.email, roles: ['cfo'], password: 'password-for-api-test' },
  });
  expect(await page.evaluate(() => localStorage.getItem('signal.registration-request.v1.api'))).toBeNull();
  expect(await page.evaluate(() => sessionStorage.getItem('signal.registration-draft.v1.api'))).toBeNull();
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
    { name: 'too-large.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(12 * 1024 * 1024 + 1) },
  ]);
  await expect(page.locator('.signal-upload-result.is-error')).toHaveCount(2);
  await expect(page.getByText('Допустимы только PDF, TXT, DOCX и XLSX.', { exact: true })).toBeVisible();
  await expect(page.getByText('Файл больше 12 МБ. Выберите файл меньшего размера.', { exact: true })).toBeVisible();
  expect(state.uploadContentTypes).toEqual([]);
  expect(state.unknown).toEqual([]);
});
