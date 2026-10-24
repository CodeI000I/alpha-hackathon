import { Link } from 'react-router-dom';
import type { FeedKind } from '../api/types';
import { dailySummary } from '../report';
import { countLabel, summaryStories } from '../summaryPresentation';
import { ActionIcon } from '../signal/components/ActionIcon';

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

interface Props {
  summary: ReturnType<typeof dailySummary>;
  demo: boolean;
  focus?: string;
  hasOlderItems: boolean;
  onFilter: (kind: FeedKind) => void;
}

export function DailySummary({ summary, demo, focus, hasOlderItems, onFilter }: Props) {
  const total = summary.items.length;
  const stories = summaryStories(summary.items);
  const first = summary.items.slice().sort((a, b) => b.score - a.score || a.id - b.id)[0];
  const kinds: FeedKind[] = summary.counts.event ? ['risk', 'opportunity', 'event'] : ['risk', 'opportunity'];
  const about = <details className="data-note daily-about"><summary>О сводке</summary>
    <p>События за последние 24 часа по дате публикации. Учитываются последние 200 записей ленты по всем вашим ролям. Это не резюме ИИ.</p>
    <p>Каждая новость учитывается один раз. Если у неё несколько ролевых разборов, для сводки выбран самый релевантный. Все разборы остаются в ленте. Полоса показывает распределение событий по типам, а не вероятность или динамику.</p>
    <p>Период: {new Date(summary.start).toLocaleString('ru-RU')} — {new Date(summary.end).toLocaleString('ru-RU')}.</p>
    {demo && <p>Показаны демонстрационные события.</p>}
  </details>;

  return <section className={'daily-summary' + (!total ? ' daily-summary-empty' : '')} aria-label="Сводка за 24 часа">
    <header className="daily-header"><div><span className="daily-kicker">Последние события за 24 часа{demo ? ' · демо' : ''}</span><h2>{total ? 'Что важно сегодня' : 'За сутки новых событий нет'}</h2></div></header>
    {total ? <>
      <div className={'daily-body' + (stories.length === 1 ? ' daily-body-single' : '')}>
        <div className="daily-balance">
          <strong><span className="daily-total">{total}</span><span>{countLabel(total, labels.event)}</span></strong>
          <div className="daily-balance-bar" aria-hidden="true">{kinds.filter(kind => summary.counts[kind] > 0).map(kind => <i key={kind} className={'daily-segment-' + kind} style={{ flexGrow: summary.counts[kind] }} />)}</div>
          <div className="daily-counts">{kinds.map(kind => <button key={kind} className={'daily-count-' + kind} disabled={!summary.counts[kind]} onClick={() => onFilter(kind)}>
            {kind === 'event' ? <span className="daily-dot" /> : <TrendIcon up={kind === 'opportunity'} />}
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
        <Link className="daily-next-action" to={'/news/' + first.id}><span>Самый релевантный разбор за сутки</span><strong>Открыть разбор <ActionIcon /></strong></Link>
        {about}
      </footer>
    </> : <>
      <p className="daily-empty-description">{hasOlderItems ? 'Более ранние события доступны в ленте ниже.' : 'Сводка появится, когда в ленте будут события за последние 24 часа.'}</p>
      {about}
    </>}
  </section>;
}
