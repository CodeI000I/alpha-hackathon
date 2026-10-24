import { describe, expect, it } from 'vitest';
import type { FeedItem, FeedKind } from '../../src/api/types';
import { countLabel, emptyFeedRefetchInterval, summaryStories } from '../../src/summaryPresentation';

function item(id: number, kind: FeedKind, score: number, newsId = id): FeedItem {
  return { id, kind, score, role: 'cfo', insight: '', elements: [], readAt: null, createdAt: '', news: { id: newsId, title: 'Событие ' + id, summary: '', publishedAt: '', url: '', sourceId: '' } };
}

describe('summary stories', () => {
  it('keeps both a real risk and opportunity even if the two highest scores are risks', () => {
    const items = [item(1, 'risk', .95), item(2, 'risk', .9), item(3, 'opportunity', .7), item(4, 'event', .8)];
    expect(summaryStories(items).map(value => value.id)).toEqual([1, 3]);
    expect(items.map(value => value.id)).toEqual([1, 2, 3, 4]);
  });
  it('uses real events when no risk or opportunity exists, including a single card', () => {
    expect(summaryStories([item(1, 'event', .6)])).toHaveLength(1);
    expect(summaryStories([item(1, 'event', .6), item(2, 'event', .9), item(3, 'event', .8)]).map(value => value.id)).toEqual([2, 3]);
    expect(summaryStories([])).toEqual([]);
  });
  it('does not repeat the same news in both story columns', () => {
    expect(summaryStories([item(1, 'risk', .9, 77), item(2, 'opportunity', .8, 77), item(3, 'event', .6)]).map(value => value.id)).toEqual([1, 3]);
  });
});

describe('Russian count labels', () => {
  it.each([[0, 'событий'], [1, 'событие'], [2, 'события'], [4, 'события'], [5, 'событий'], [11, 'событий'], [14, 'событий'], [21, 'событие'], [22, 'события'], [112, 'событий']])('formats %s', (count, label) => {
    expect(countLabel(Number(count), ['событие', 'события', 'событий'])).toBe(label);
  });
});

describe('bounded asynchronous feed refresh', () => {
  it('retries an empty successful API result no more than four times after the initial load', () => {
    expect([1, 2, 3, 4, 5, 6].map(updates => emptyFeedRefetchInterval(false, 'success', 0, updates))).toEqual([15000, 15000, 15000, 15000, false, false]);
  });
  it('never polls demo mode, errors, pending requests or a populated feed', () => {
    expect(emptyFeedRefetchInterval(true, 'success', 0, 1)).toBe(false);
    expect(emptyFeedRefetchInterval(false, 'error', 0, 1)).toBe(false);
    expect(emptyFeedRefetchInterval(false, 'pending', 0, 0)).toBe(false);
    expect(emptyFeedRefetchInterval(false, 'success', 1, 1)).toBe(false);
  });
});
