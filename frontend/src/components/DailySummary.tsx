import { useState, type PointerEvent } from 'react';
import { Link } from 'react-router-dom';
import type { FeedKind } from '../api/types';
import { isDemoMode } from '../api/client';
import { dailySummary } from '../report';
import { countLabel, summaryStories } from '../summaryPresentation';
import { ActionIcon } from '../signal/components/ActionIcon';
import './DailySummary.css';

const labels: Record<FeedKind, readonly [string, string, string]> = {
  risk: ['риск', 'риска', 'рисков'],
  opportunity: ['возможность', 'возможности', 'возможностей'],
  event: ['событие', 'события', 'событий'],
};
const storyLabels: Record<FeedKind, string> = {
  risk: 'Требует внимания', opportunity: 'Открывает возможности', event: 'Важное событие',
};

function TrendIcon({ up = false }: { up?: boolean }) {
  return <svg className={'daily-trend ' + (up ? 'daily-trend-up' : 'daily-trend-down')} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={up ? 'M3 17l6-6 4 4 8-10 M15 5h6v6' : 'M3 7l6 6 4-4 8 10 M15 19h6v-6'} /></svg>;
}

function EventIcon() {
  return <svg className="daily-event-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><rect x="3" y="5" width="18" height="14" rx="2" /><rect x="6" y="8" width="4" height="4" rx=".5" /><path d="M13 8h5 M13 12h5 M6 16h12" /></svg>;
}

interface Props {
  summary: ReturnType<typeof dailySummary>;
  focus?: string;
  hasOlderItems: boolean;
  onFilter: (kind: FeedKind) => void;
}

export function DailySummary({ summary, focus, hasOlderItems, onFilter }: Props) {
  const [hoveredKind, setHoveredKind] = useState<FeedKind | null>(null);
  const [focusedKind, setFocusedKind] = useState<FeedKind | null>(null);
  const requestedKind = hoveredKind ?? focusedKind;
  const highlightedKind = requestedKind && summary.counts[requestedKind] > 0 ? requestedKind : null;
  const interaction = (kind: FeedKind) => ({
    onPointerEnter: (event: PointerEvent<HTMLButtonElement>) => { if (summary.counts[kind] > 0 && event.pointerType !== 'touch') setHoveredKind(kind); },
    onPointerLeave: () => setHoveredKind(null),
    onFocus: () => { setHoveredKind(null); setFocusedKind(kind); },
    onBlur: () => setFocusedKind(null),
  });
  const emphasis = (kind: FeedKind) => highlightedKind ? (highlightedKind === kind ? ' is-highlighted' : ' is-muted') : '';
  const total = summary.items.length;
  const stories = summaryStories(summary.items);
  const first = summary.items.slice().sort((a, b) => b.score - a.score || a.id - b.id)[0];
  const kinds: FeedKind[] = summary.counts.event ? ['risk', 'opportunity', 'event'] : ['risk', 'opportunity'];
  const about = <details className="data-note daily-about"><summary>О сводке</summary>
    {isDemoMode && <p>События подготовлены для примера и не отражают актуальную ленту.</p>}
    <p>События за последние 24 часа по дате публикации. Учитываются последние 200 записей ленты по всем вашим ролям. Это не резюме ИИ.</p>
    <p>Каждая новость учитывается один раз. Если у неё несколько ролевых разборов, для сводки выбран {isDemoMode ? 'наиболее релевантный' : 'самый срочный'}. Все разборы остаются в ленте. Полоса показывает распределение событий по типам, а не вероятность или динамику.</p>
    <p>Период: {new Date(summary.start).toLocaleString('ru-RU')} — {new Date(summary.end).toLocaleString('ru-RU')}.</p>
  </details>;

  return <section className={'daily-summary' + (!total ? ' daily-summary-empty' : '')} aria-label="Сводка за 24 часа">
    <header className="daily-header"><div><span className="daily-kicker">Последние события за 24 часа</span><h2>{total ? 'Что важно сегодня' : 'За сутки новых событий нет'}</h2></div></header>
    {total ? <>
      <div className={'daily-body' + (stories.length === 1 ? ' daily-body-single' : '')}>
        <div className="daily-balance" data-highlighted-kind={highlightedKind ?? undefined}>
          <strong><span className="daily-total">{total}</span><span>{countLabel(total, labels.event)}</span></strong>
          <div className="daily-balance-bar" role="group" aria-label="Распределение событий по типам">{kinds.filter(kind => summary.counts[kind] > 0).map(kind => <button key={kind} type="button" className={'daily-segment daily-segment-' + kind + emphasis(kind)} data-summary-kind={kind} style={{ flexGrow: summary.counts[kind] }} aria-label={'Показать ' + summary.counts[kind] + ' ' + countLabel(summary.counts[kind], labels[kind])} onClick={() => onFilter(kind)} {...interaction(kind)}><i aria-hidden="true" /></button>)}</div>
          <div className="daily-counts">{kinds.map(kind => <button key={kind} type="button" className={'daily-count-' + kind + emphasis(kind)} data-summary-kind={kind} disabled={!summary.counts[kind]} onClick={() => onFilter(kind)} {...interaction(kind)}>
            {kind === 'event' ? <EventIcon /> : <TrendIcon up={kind === 'opportunity'} />}
            {summary.counts[kind]} {countLabel(summary.counts[kind], labels[kind])}
          </button>)}</div>
        </div>
        {stories.map(item => <article className="daily-story" key={item.id}>
          <span className="daily-story-label"><i className={'daily-dot ' + item.kind} />{storyLabels[item.kind] ?? 'Событие'}</span>
          <strong>{item.news.title || 'Без заголовка'}</strong>
          <p>{item.news.summary || 'Сообщение источника не передано.'}</p>
          <Link className="daily-story-link action-link" to={'/news/' + item.id}>К разбору <ActionIcon /></Link>
        </article>)}
      </div>
      <footer className="daily-footer">
        <div className="daily-focus"><span>{focus ? 'В вашем фокусе' : 'В обзоре'}</span><p>{focus || 'События по вашим ролям за последние сутки'}</p></div>
        <Link className="daily-next-action" to={'/news/' + first.id}><span>{isDemoMode ? 'Самый релевантный разбор за сутки' : 'Самый срочный разбор за сутки'}</span><strong>Открыть разбор <ActionIcon /></strong></Link>
        {about}
      </footer>
    </> : <>
      <p className="daily-empty-description">{hasOlderItems ? 'Более ранние события доступны в ленте ниже.' : 'Сводка появится, когда в ленте будут события за последние 24 часа.'}</p>
      {about}
    </>}
  </section>;
}
