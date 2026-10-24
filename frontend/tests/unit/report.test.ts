import { describe, expect, it } from 'vitest';
import type { Company, FeedItem, FeedKind } from '../../src/api/types';
import {
  BANK_NOT_USED,
  BANK_UNKNOWN,
  DISCLAIMER,
  assignedFeed,
  dailySummary,
  exportReport,
  relevance,
  priority,
  sourceUrl,
} from '../../src/report';

const HOUR = 60 * 60 * 1_000;
const NOW = Date.parse('2026-10-22T12:00:00.000Z');

function item(id: number, role: string, publishedAt: string, kind: FeedKind = 'event'): FeedItem {
  return {
    id,
    role,
    kind,
    score: 0.874,
    insight: 'Проверяемая интерпретация события для компании.',
    elements: ['Б3', 'С4'],
    news: {
      id: 1_000 + id,
      sourceId: `S${id}`,
      url: 'https://example.test/source',
      title: `Событие ${id}`,
      summary: `Сообщение источника ${id}`,
      publishedAt,
    },
    createdAt: publishedAt,
    readAt: null,
  };
}

const company: Company = {
  id: 7,
  inn: '7707083893',
  ogrn: '1027700067328',
  name: 'ООО «Проверка»',
  profile: {},
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-22T00:00:00Z',
};

describe('24-hour summary', () => {
  it('counts one news event across roles and uses its highest-scoring analysis', () => {
    const risk = item(1, 'cfo', new Date(NOW).toISOString(), 'risk');
    const opportunity = { ...risk, id: 2, role: 'strategy', score: .95, kind: 'opportunity' as const };
    const result = dailySummary([risk, opportunity], NOW);
    expect(result.items).toEqual([opportunity]);
    expect(result.counts).toEqual({ event: 0, risk: 0, opportunity: 1 });
  });

  it('uses stable tie-breaking and never merges different events with missing news IDs', () => {
    const first = item(1, 'cfo', new Date(NOW).toISOString(), 'risk');
    const otherRole = { ...first, id: 2, role: 'strategy' };
    expect(dailySummary([otherRole, first], NOW).items).toEqual([first]);
    const unknownA = { ...first, news: { ...first.news, id: 0 } };
    const unknownB = { ...otherRole, news: { ...otherRole.news, id: 0 } };
    expect(dailySummary([unknownA, unknownB], NOW).items).toHaveLength(2);
  });

  it('includes both boundaries and excludes older, future, and invalid dates', () => {
    const values = [
      item(1, 'cfo', new Date(NOW - 24 * HOUR).toISOString(), 'risk'),
      item(2, 'cfo', new Date(NOW - HOUR).toISOString(), 'opportunity'),
      item(3, 'cfo', new Date(NOW).toISOString(), 'event'),
      item(4, 'cfo', new Date(NOW - 24 * HOUR - 1).toISOString(), 'risk'),
      item(5, 'cfo', new Date(NOW + 1).toISOString(), 'opportunity'),
      item(6, 'cfo', 'not-a-date', 'event'),
    ];

    const result = dailySummary(values, NOW);

    expect(result.items.map(({ id }) => id)).toEqual([1, 2, 3]);
    expect(result.counts).toEqual({ event: 1, risk: 1, opportunity: 1 });
    expect(result.start).toBe(NOW - 24 * HOUR);
    expect(result.end).toBe(NOW);
  });
});

describe('role assignment', () => {
  const values = [
    item(1, 'cfo', new Date(NOW).toISOString()),
    item(2, 'strategy', new Date(NOW).toISOString()),
    item(3, 'operations', new Date(NOW).toISOString()),
  ];

  it('removes items for a role as soon as that role is no longer assigned', () => {
    expect(assignedFeed(values, ['cfo', 'strategy']).map(({ id }) => id)).toEqual([1, 2]);
    expect(assignedFeed(values, ['strategy']).map(({ id }) => id)).toEqual([2]);
    expect(assignedFeed(values, [])).toEqual([]);
    expect(assignedFeed(null, ['cfo'])).toEqual([]);
  });
});

describe('source URLs and relevance', () => {
  it.each([
    ['https://example.test/news?q=1', 'https://example.test/news?q=1'],
    ['http://example.test/news', 'http://example.test/news'],
    ['ftp://example.test/file', undefined],
    ['javascript:alert(1)', undefined],
    ['/relative/source', undefined],
    ['', undefined],
    [undefined, undefined],
  ])('normalizes %s without admitting unsupported protocols', (value, expected) => {
    expect(sourceUrl(value)).toBe(expected);
  });

  it.each([
    [0, '0%'],
    [0.004, '0%'],
    [0.874, '87%'],
    [1, '100%'],
    [-0.01, 'не передана'],
    [1.01, 'не передана'],
    [Number.NaN, 'не передана'],
    [Number.POSITIVE_INFINITY, 'не передана'],
  ])('formats relevance %s as %s', (score, expected) => {
    expect(relevance(score)).toBe(expected);
  });

  it.each([
    [0, 'Без срочности'],
    [0.25, 'Срочность не указана'],
    [0.5, 'Наблюдать'],
    [0.8, 'Скоро'],
    [1, 'Срочно'],
    [0.7, 'Срочность не указана'],
    [Number.NaN, 'Срочность не указана'],
  ])('formats live ordinal priority %s as %s', (score, expected) => {
    expect(priority(score)).toBe(expected);
  });
});

describe('text report provenance', () => {
  it('labels API material, preserves source provenance, and avoids claiming bank analysis', () => {
    const report = exportReport(item(11, 'cfo', '2026-10-22T10:30:00Z', 'risk'), {
      company,
      roleName: 'Финансовый директор',
      demo: false,
    });

    expect(report).toContain('Данные получены из API');
    expect(report).toContain('Компания: ООО «Проверка»');
    expect(report).toContain('Ракурс: Финансовый директор');
    expect(report).toContain('Тип: Риск');
    expect(report).toContain('Приоритет (срочность): Срочность не указана');
    expect(report).toContain('Что произошло [Сообщение источника / news.summary]');
    expect(report).toContain('Значение для бизнеса [Интерпретация / insight]');
    expect(report).toContain('Что может измениться [Гипотеза]');
    expect(report).toContain('Документы компании [Основания]');
    expect(report).toContain('Материалы банка [Основания]');
    expect(report).toContain(BANK_UNKNOWN);
    expect(report).toContain('Источник: S11');
    expect(report).toContain('Ссылка: https://example.test/source');
    expect(report).toContain(DISCLAIMER);
    expect(report).not.toContain(BANK_NOT_USED);
  });

  it('marks synthetic demo data and reports invalid or absent provenance explicitly', () => {
    const demoItem = item(12, 'operations', 'invalid-date', 'opportunity');
    demoItem.news.url = 'file:///private/source';
    demoItem.news.sourceId = '';
    demoItem.news.summary = '';
    demoItem.insight = '';
    demoItem.elements = [];

    const report = exportReport(demoItem, { roleName: 'Операционный директор', demo: true });

    expect(report).toContain('ДЕМО: синтетические данные');
    expect(report).toContain('Компания: не указана');
    expect(report).toContain('Сообщение источника не передано.');
    expect(report).toContain('Интерпретация не передана.');
    expect(report).toContain('Дата не передана');
    expect(report).toContain('Источник: не указан');
    expect(report).toContain('Ссылка: не передана или имеет неподдерживаемый формат');
    expect(report).toContain('Элементы профиля: не переданы');
    expect(report).toContain(BANK_NOT_USED);
    expect(report).toContain(DISCLAIMER);
    expect(report).not.toContain(BANK_UNKNOWN);
  });
});
