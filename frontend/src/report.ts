import type { Company, FeedItem, FeedKind } from './api/types';
export const DISCLAIMER = 'Материал носит информационно-аналитический характер и не является инвестиционной рекомендацией';
export const KIND_LABELS: Record<FeedKind, string> = { event: 'Событие', risk: 'Риск', opportunity: 'Возможность' };
export const BANK_UNKNOWN = 'Сведения об использовании аналитики Альфа-Банка не переданы сервером.';
export const BANK_NOT_USED = 'Аналитика Альфа-Банка не использована в этом разборе';
export function sourceUrl(value?: string): string | undefined {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; }
}
export function sourceLabel(item: FeedItem): string | undefined {
  const url = sourceUrl(item.news.url);
  return item.news.sourceId?.trim() || (url ? new URL(url).hostname : undefined);
}
export function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }) : 'Дата не передана';
}
export function relevance(score: number): string {
  return Number.isFinite(score) && score >= 0 && score <= 1 ? Math.round(score * 100) + '%' : 'не передана';
}
export function assignedFeed(items: readonly FeedItem[] | null | undefined, roles: readonly string[]): FeedItem[] {
  return (items ?? []).filter(item => roles.includes(item.role));
}
export function dailySummary(items: readonly FeedItem[], now: number) {
  const start = now - 24 * 60 * 60 * 1000;
  const recent = items.filter(item => { const time = Date.parse(item.news.publishedAt); return Number.isFinite(time) && time >= start && time <= now; });
  // The backend creates a separate FeedItem per role. Count a news event once,
  // representing it by its most relevant analysis across the assigned roles.
  const unique = new Map<string, FeedItem>();
  for (const item of recent) {
    const key = item.news.id > 0 ? 'news:' + item.news.id : 'feed:' + item.id;
    const previous = unique.get(key);
    if (!previous || item.score > previous.score || (item.score === previous.score && item.id < previous.id)) unique.set(key, item);
  }
  const events = [...unique.values()];
  const counts = { event: 0, risk: 0, opportunity: 0 };
  events.forEach(item => { if (item.kind in counts) counts[item.kind]++; });
  return { items: events, counts, start, end: now };
}
export function exportReport(item: FeedItem, context: { company?: Company; roleName: string; demo: boolean }): string {
  return [
    'Сигнал — разбор события',
    context.demo ? 'ДЕМО: синтетические данные, не использовать для принятия решений.' : 'Данные получены из API; готовность и качество аналитики определяются сервером.',
    item.news.title || 'Без заголовка',
    'Компания: ' + (context.company?.name ?? 'не указана'),
    'Ракурс: ' + context.roleName,
    'Тип: ' + (KIND_LABELS[item.kind] ?? 'неизвестен'),
    'Релевантность: ' + relevance(item.score),
    'Опубликовано: ' + dateLabel(item.news.publishedAt),
    '', 'Что произошло [Сообщение источника / news.summary]', item.news.summary || 'Сообщение источника не передано.',
    '', 'Значение для бизнеса [Интерпретация / insight]', item.insight || 'Интерпретация не передана.',
    '', 'Что может измениться [Гипотеза]', 'Отдельные гипотезы, сценарии и расчёты сервером не переданы.',
    '', 'Документы компании [Основания]', 'API не сообщает, какие документы использованы в разборе. Наличие загруженного файла не подтверждает его анализ.',
    '', 'Аналитика от Альфа-Банка [Основания]', context.demo ? BANK_NOT_USED : BANK_UNKNOWN,
    '', 'Источник: ' + (item.news.sourceId || 'не указан'), 'Ссылка: ' + (sourceUrl(item.news.url) ?? 'не передана или имеет неподдерживаемый формат'),
    'Элементы профиля: ' + ((item.elements ?? []).join(', ') || 'не переданы'),
    '', 'Чат, закладки, графики и предложения банка — отдельные локальные демофункции; их данные не включены в выводы этого разбора.',
    '', DISCLAIMER,
  ].join('\n');
}
