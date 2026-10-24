import type { FeedItem } from './api/types';

export function countLabel(count: number, forms: readonly [string, string, string]): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return forms[2];
  const units = count % 10;
  return units === 1 ? forms[0] : units >= 2 && units <= 4 ? forms[1] : forms[2];
}

/** Show both sides of the overview when available, without inventing a story. */
export function summaryStories(items: readonly FeedItem[]): FeedItem[] {
  const ranked = [...items].sort((a, b) => b.score - a.score || a.id - b.id);
  const selected: FeedItem[] = [];
  const add = (item?: FeedItem) => {
    if (item && selected.length < 2 && !selected.some(existing => existing.id === item.id ||
      (item.news.id > 0 && existing.news.id === item.news.id))) selected.push(item);
  };
  add(ranked.find(item => item.kind === 'risk'));
  add(ranked.find(item => item.kind === 'opportunity'));
  ranked.forEach(add);
  return selected;
}

/** The worker runs asynchronously. Retry an empty result briefly, never an error. */
export function emptyFeedRefetchInterval(demo: boolean, status: string, count: number, updates: number): number | false {
  return !demo && status === 'success' && count === 0 && updates < 5 ? 15_000 : false;
}
