import { expect, type BrowserContext, type Page } from '@playwright/test';

export const DEMO_PASSWORD = 'SignalDemo2026!';
export const DEMO_ACCOUNTS = {
  finance: {
    email: 'finance@signal.demo',
    company: 'ООО «Сигнал Технологии»',
    event: 'Банк России сохранил ключевую ставку',
  },
  operations: {
    email: 'operations@signal.demo',
    company: 'АО «Северная мануфактура»',
    event: 'Перевозчик предупредил об изменении сроков доставки промышленных грузов',
  },
} as const;

export async function loginDemo(page: Page, account: keyof typeof DEMO_ACCOUNTS = 'finance') {
  const details = DEMO_ACCOUNTS[account];
  await page.goto('/login');
  await page.getByLabel('Электронная почта').fill(details.email);
  await page.getByLabel('Пароль тестового аккаунта').fill(DEMO_PASSWORD);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: 'Обзор событий', level: 1 })).toBeVisible();
  return details;
}

export function monitorBrowserErrors(context: BrowserContext) {
  const errors: string[] = [];
  const attach = (page: Page) => {
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
  };
  context.pages().forEach(attach);
  context.on('page', attach);
  return errors;
}
