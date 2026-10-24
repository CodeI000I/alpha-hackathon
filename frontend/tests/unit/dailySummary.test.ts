import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DailySummary } from '../../src/components/DailySummary';
import { dailySummary } from '../../src/report';
import type { FeedItem, FeedKind } from '../../src/api/types';

const NOW = Date.parse('2026-10-24T12:00:00Z');
const kinds: FeedKind[] = ['risk', 'risk', 'opportunity', 'event'];
function makeItem(kind: FeedKind, index: number): FeedItem {
  return {
    id: index + 1, role: 'cfo', kind, score: .8, insight: 'Интерпретация', elements: [], readAt: null,
    createdAt: new Date(NOW).toISOString(),
    news: { id: index + 1, title: `Заголовок ${index + 1}`, summary: 'Сообщение источника', publishedAt: new Date(NOW).toISOString() },
  };
}
let container: HTMLDivElement;
let root: Root;
const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
let previousActEnvironment: boolean | undefined;

beforeEach(() => {
  previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
});

function render(items = kinds.map(makeItem), onFilter = vi.fn()) {
  act(() => root.render(createElement(MemoryRouter, { future: { v7_startTransition: true, v7_relativeSplatPath: true } }, createElement(DailySummary, {
    summary: dailySummary(items, NOW), focus: 'Финансы', hasOlderItems: false, onFilter,
  }))));
  return onFilter;
}
function get(selector: string) {
  const element = container.querySelector<HTMLElement>(selector);
  if (!element) throw new Error(`Element not found: ${selector}`);
  return element;
}
function pointer(element: HTMLElement, type: 'pointerover' | 'pointerout', pointerType = 'mouse') {
  const event = new Event(type, { bubbles: true });
  Object.defineProperty(event, 'pointerType', { value: pointerType });
  act(() => element.dispatchEvent(event));
}

describe('summary type interactions', () => {
  it('exposes named segment buttons and equally sized icons without demo labels', () => {
    render();
    expect(get('.daily-balance-bar').getAttribute('role')).toBe('group');
    expect(get('.daily-balance-bar').getAttribute('aria-hidden')).toBeNull();
    expect(Array.from(container.querySelectorAll('.daily-segment')).map(element => element.getAttribute('aria-label'))).toEqual(['Показать 2 риска', 'Показать 1 возможность', 'Показать 1 событие']);
    const icons = container.querySelectorAll('.daily-counts svg');
    expect(icons).toHaveLength(3);
    icons.forEach(icon => {
      expect(icon.getAttribute('width')).toBe('18');
      expect(icon.getAttribute('height')).toBe('18');
      expect(icon.getAttribute('aria-hidden')).toBe('true');
    });
    expect(get('.daily-event-icon').querySelectorAll('rect')).toHaveLength(2);
    expect(get('.daily-event-icon path').getAttribute('d')).toBe('M13 8h5 M13 12h5 M6 16h12');
    expect(container.textContent).not.toMatch(/демо/i);
  });

  it('links segment hover with the matching row and mutes all other types', () => {
    render();
    pointer(get('.daily-segment-risk'), 'pointerover');
    expect(get('.daily-balance').dataset.highlightedKind).toBe('risk');
    expect(get('.daily-count-risk').classList.contains('is-highlighted')).toBe(true);
    expect(get('.daily-segment-risk').classList.contains('is-highlighted')).toBe(true);
    expect(container.querySelectorAll('.is-muted')).toHaveLength(4);
    pointer(get('.daily-segment-risk'), 'pointerout');
    expect(get('.daily-balance').dataset.highlightedKind).toBeUndefined();
    expect(container.querySelectorAll('.is-muted, .is-highlighted')).toHaveLength(0);
  });

  it('gives keyboard focus the same highlight and returns to it after pointer hover', () => {
    render();
    act(() => get('.daily-segment-event').focus());
    expect(get('.daily-balance').dataset.highlightedKind).toBe('event');
    expect(get('.daily-count-event').classList.contains('is-highlighted')).toBe(true);
    pointer(get('.daily-count-opportunity'), 'pointerover');
    expect(get('.daily-balance').dataset.highlightedKind).toBe('opportunity');
    pointer(get('.daily-count-opportunity'), 'pointerout');
    expect(get('.daily-balance').dataset.highlightedKind).toBe('event');
    act(() => get('.daily-count-risk').focus());
    expect(get('.daily-balance').dataset.highlightedKind).toBe('risk');
    act(() => get('.daily-count-risk').blur());
    expect(get('.daily-balance').dataset.highlightedKind).toBeUndefined();
  });

  it('filters from both controls and does not create a sticky touch hover', () => {
    const onFilter = render();
    pointer(get('.daily-segment-risk'), 'pointerover', 'touch');
    expect(get('.daily-balance').dataset.highlightedKind).toBeUndefined();
    act(() => get('.daily-segment-risk').click());
    act(() => get('.daily-count-event').click());
    expect(onFilter.mock.calls).toEqual([['risk'], ['event']]);
  });

  it('keeps zero-count rows disabled and only exposes nonempty segments', () => {
    const onFilter = render([makeItem('opportunity', 0)]);
    expect(container.querySelectorAll('.daily-segment')).toHaveLength(1);
    expect((get('.daily-count-risk') as HTMLButtonElement).disabled).toBe(true);
    pointer(get('.daily-count-risk'), 'pointerover');
    expect(get('.daily-balance').dataset.highlightedKind).toBeUndefined();
    act(() => get('.daily-count-risk').click());
    expect(onFilter).not.toHaveBeenCalled();
  });

  it('preserves the compact empty state without a decorative distribution', () => {
    render([]);
    expect(container.textContent).toContain('За сутки новых событий нет');
    expect(container.querySelector('.daily-balance')).toBeNull();
    expect(container.textContent).not.toMatch(/демо/i);
  });
});
