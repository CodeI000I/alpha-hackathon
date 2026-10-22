import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { api, isDemoMode } from '../api/client';
import { DEMO_NOW } from '../api/mocks';
import { useWorkspace } from '../appContext';
import EventCard from '../components/EventCard';
import { DemoChat } from '../components/DemoChat';
import { Button, StatePanel } from '../components/ui';
import { Icon } from '../components/Icon';
import { filterFeedItems, type FeedFilter } from '../feedFilters';
import { localKey, useStoredState } from '../localState';
import { WidgetBoard } from '../signal/DashboardOverview';
import { ActionIcon } from '../signal/components/ActionIcon';
import { assignedFeed, dailySummary, KIND_LABELS } from '../report';
const filters: Array<[FeedFilter, string]> = [['all', 'Все'], ['risk', 'Риски'], ['opportunity', 'Возможности'], ['event', 'События'], ['saved', 'Закладки · Демо']];
export default function FeedPage({ userId }: { userId: number }) {
  const { user, roles, activeRole, setActiveRole, saved, toggleSaved } = useWorkspace();
  const [params, setParams] = useSearchParams(); const [filter, setFilter] = useState<FeedFilter>('all'); const [query, setQuery] = useState('');
  const [keywords] = useStoredState<string[]>(localKey(userId, 'keywords', user.companyId), []);
  useEffect(() => {
    const requestedRole = params.get('role');
    if (requestedRole === null) return;
    if (user.roles.includes(requestedRole)) setActiveRole(requestedRole);
    const changed = new URLSearchParams(params); changed.delete('role'); setParams(changed, { replace: true });
  }, [params, user.roles, setActiveRole, setParams]);
  const feed = useQuery({ queryKey: ['feed', userId, user.roles], queryFn: ({ signal }) => api.feed(userId, undefined, 200, signal) });
  const allItems = assignedFeed(feed.data, user.roles);
  const activeFilter = params.get('saved') === '1' ? 'saved' : filter;
  const visibleItems = filterFeedItems(allItems.filter(item => !activeRole || item.role === activeRole), { filter: activeFilter, query, savedIds: saved });
  const summary = dailySummary(allItems, isDemoMode ? Date.parse(DEMO_NOW) : Date.now());
  const roleName = (code: string) => roles.find(role => role.code === code)?.name ?? code;
  const selectFilter = (next: FeedFilter) => { setFilter(next === 'saved' ? 'all' : next); const changed = new URLSearchParams(params); if (next === 'saved') changed.set('saved', '1'); else changed.delete('saved'); setParams(changed, { replace: true }); };
  return <>
    <div className="signal-page-heading"><h1>Обзор событий</h1></div>
    {feed.isRefetchError && <p className="integration-warning" role="alert">Обновление ленты не удалось. Показаны ранее полученные данные. <button onClick={() => feed.refetch()}>Повторить</button></p>}
    {feed.data && <section className="daily-summary" aria-label="Сводка за 24 часа">
      <header className="daily-header"><div><span className="daily-kicker">Последние 24 часа{isDemoMode ? ' · демонстрационный период' : ''}</span><h2>{summary.items.length ? 'Что важно сегодня' : 'За сутки новых событий нет'}</h2></div></header>
      <div className="daily-body"><div className="daily-balance"><strong>{summary.items.length}</strong><span>событий за сутки</span><div className="daily-counts">{(['risk', 'opportunity', 'event'] as const).map(kind => <button key={kind} onClick={() => selectFilter(kind)}><span className={'daily-dot ' + kind} />{KIND_LABELS[kind]}: {summary.counts[kind]}</button>)}</div></div>
        {summary.items.slice().sort((a, b) => b.score - a.score).slice(0, 2).map(item => <div className="daily-story" key={item.id}><span>{KIND_LABELS[item.kind]}</span><strong>{item.news.title}</strong><p>{item.news.summary}</p><Link className="daily-story-link action-link" to={'/news/' + item.id}>К разбору <ActionIcon /></Link></div>)}
      </div>
      <footer className="daily-footer"><details className="data-note"><summary>О сводке</summary><p>События за последние 24 часа по дате публикации. Учитываются последние 200 записей ленты. Это не резюме ИИ.</p><p>Период: {new Date(summary.start).toLocaleString('ru-RU')} — {new Date(summary.end).toLocaleString('ru-RU')}.</p>{isDemoMode && <p>Показаны демонстрационные события.</p>}</details></footer>
    </section>}
    <div className="w-dashboard-grid"><section aria-label="Лента событий"><header className="w-feed-heading"><h2>События для вас</h2><span>{visibleItems.length} из {allItems.length}</span></header>
      <div className="w-filterbar">{filters.map(([value, label]) => <button key={value} className={activeFilter === value ? 'active' : ''} aria-pressed={activeFilter === value} onClick={() => selectFilter(value)}>{label}</button>)}</div>
      <label className="w-search"><Icon name="search" size={18} /><span className="sr-only">Поиск по событиям</span><input type="search" placeholder="Поиск по событиям и темам" value={query} onChange={event => setQuery(event.target.value)} />{query && <button aria-label="Очистить поиск" onClick={() => setQuery('')}><Icon name="close" size={16} /></button>}</label>
      {feed.isPending && <StatePanel title="Загружаем события…" text="Это займёт несколько секунд." />}
      {feed.isError && !feed.data && <StatePanel tone="error" title="Лента не загрузилась" text={feed.error.message} action={<Button onClick={() => feed.refetch()}>Повторить</Button>} />}
      {!feed.isPending && !feed.isError && !visibleItems.length && <StatePanel title={allItems.length ? 'Ничего не найдено' : 'В ленте пока нет событий'} text={allItems.length ? 'Попробуйте другой запрос или фильтр.' : 'Здесь появятся события, важные для вашей компании.'} action={allItems.length ? <Button onClick={() => { selectFilter('all'); setQuery(''); }}>Сбросить фильтры</Button> : undefined} />}
      <div className="w-feed">{visibleItems.map(item => <EventCard key={item.id} item={item} keywords={keywords} roleName={roleName(item.role)} saved={saved.includes(item.id)} onToggleSave={() => toggleSaved(item.id)} />)}</div>
    </section><aside className="w-context-column"><WidgetBoard storageKey={localKey(userId, 'widgets', user.companyId)} /><DemoChat userId={userId} companyId={user.companyId} itemTitle="события в вашей ленте" roleName={activeRole ? roleName(activeRole) : 'роль не выбрана'} compact /></aside></div>
  </>;
}
