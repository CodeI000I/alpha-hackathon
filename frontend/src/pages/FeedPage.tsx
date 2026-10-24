import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api, isDemoMode } from '../api/client';
import { DEMO_NOW } from '../api/mocks';
import { useWorkspace } from '../appContext';
import EventCard from '../components/EventCard';
import { DemoChat } from '../components/DemoChat';
import { DailySummary } from '../components/DailySummary';
import AnalyticsOverview from '../components/AnalyticsOverview';
import { Button, StatePanel } from '../components/ui';
import { Icon } from '../components/Icon';
import { filterFeedItems, type FeedFilter } from '../feedFilters';
import { localKey, useStoredState } from '../localState';
import { WidgetBoard } from '../signal/DashboardOverview';
import { assignedFeed, dailySummary } from '../report';
import { emptyFeedRefetchInterval } from '../summaryPresentation';
import type { FeedKind } from '../api/types';
const filters: Array<[FeedFilter, string]> = [['all', 'Все'], ['risk', 'Риски'], ['opportunity', 'Возможности'], ['event', 'События'], ['saved', 'Закладки']];
const emptyKindLabels: Record<FeedKind, { title: string; action: string }> = {
  risk: { title: 'Для этой роли рисков нет', action: 'Показать риски' },
  opportunity: { title: 'Для этой роли возможностей нет', action: 'Показать возможности' },
  event: { title: 'Для этой роли нет событий этого типа', action: 'Показать события' },
};
export default function FeedPage({ userId }: { userId: number }) {
  const { user, roles, activeRole, setActiveRole, saved, toggleSaved } = useWorkspace();
  const [params, setParams] = useSearchParams(); const [filter, setFilter] = useState<FeedFilter>('all'); const [query, setQuery] = useState('');
  const [keywords] = useStoredState<string[]>(localKey(userId, 'keywords', user.companyId), []);
  const feedHeading = useRef<HTMLHeadingElement>(null);
  const [refreshNotice, setRefreshNotice] = useState('');
  useEffect(() => {
    if (!refreshNotice) return;
    const timer = window.setTimeout(() => setRefreshNotice(''), 6000);
    return () => window.clearTimeout(timer);
  }, [refreshNotice]);
  useEffect(() => {
    const requestedRole = params.get('role');
    if (requestedRole === null) return;
    if (user.roles.includes(requestedRole)) setActiveRole(requestedRole);
    const changed = new URLSearchParams(params); changed.delete('role'); setParams(changed, { replace: true });
  }, [params, user.roles, setActiveRole, setParams]);
  const feed = useQuery({
    queryKey: ['feed', userId, user.roles],
    queryFn: ({ signal }) => api.feed(userId, undefined, 200, signal),
    refetchOnWindowFocus: !isDemoMode,
    refetchInterval: query => emptyFeedRefetchInterval(isDemoMode, query.state.status, assignedFeed(query.state.data, user.roles).filter(item => !activeRole || item.role === activeRole).length, query.state.dataUpdateCount),
  });
  const allItems = assignedFeed(feed.data, user.roles);
  const activeFilter = params.get('saved') === '1' ? 'saved' : filter;
  const roleItems = allItems.filter(item => !activeRole || item.role === activeRole);
  const visibleItems = filterFeedItems(roleItems, { filter: activeFilter, query, savedIds: saved });
  const summary = dailySummary(allItems, isDemoMode ? Date.parse(DEMO_NOW) : Date.now());
  const roleName = (code: string) => roles.find(role => role.code === code)?.name ?? code;
  const kindFilter = activeFilter !== 'all' && activeFilter !== 'saved' ? activeFilter : undefined;
  const missingKind = kindFilter && !query.trim() && !roleItems.some(item => item.kind === kindFilter) ? kindFilter : undefined;
  const otherRoleItem = missingKind ? allItems.find(item => item.kind === missingKind && item.role !== activeRole) : undefined;
  const refreshFeed = async () => {
    setRefreshNotice('');
    const previous = JSON.stringify(feed.data ?? []);
    const result = await feed.refetch();
    if (!result.isError) setRefreshNotice(JSON.stringify(result.data ?? []) === previous ? 'Лента без изменений' : 'Лента обновлена');
  };
  const selectFilter = (next: FeedFilter) => { setFilter(next === 'saved' ? 'all' : next); const changed = new URLSearchParams(params); if (next === 'saved') changed.set('saved', '1'); else changed.delete('saved'); setParams(changed, { replace: true }); };
  const selectSummaryKind = (kind: FeedKind) => {
    const matches = summary.items.filter(item => item.kind === kind);
    if (!matches.some(item => item.role === activeRole) && matches[0]) setActiveRole(matches[0].role);
    setQuery('');
    selectFilter(kind);
    feedHeading.current?.focus();
  };
  return <>
    <div className="signal-page-heading"><h1>Обзор событий</h1></div>
    <AnalyticsOverview role={activeRole} />
    {feed.isRefetchError && <p className="integration-warning" role="alert">Обновление ленты не удалось. Показаны ранее полученные данные. <button onClick={() => feed.refetch()}>Повторить</button></p>}
    {feed.data && <DailySummary summary={summary} focus={roles.find(role => role.code === activeRole)?.focus} hasOlderItems={allItems.length > 0} onFilter={selectSummaryKind} />}
    <div className="w-dashboard-grid"><section aria-label="Лента событий"><header className="w-feed-heading"><h2 ref={feedHeading} tabIndex={-1}>События для вас</h2><div className="feed-refresh"><span title="События выбранной роли">{visibleItems.length} из {roleItems.length}</span><button type="button" disabled={feed.isFetching} aria-busy={feed.isFetching} aria-label="Обновить события" title="Обновить события" onClick={refreshFeed}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 1 1-9-9c2.5 0 4.9 1 6.7 2.7L21 8" /><path d="M21 3v5h-5" /></svg></button></div></header>
      <div className="w-filterbar">{filters.map(([value, label]) => <button key={value} className={activeFilter === value ? 'active' : ''} aria-pressed={activeFilter === value} onClick={() => selectFilter(value)}>{label}</button>)}</div>
      <label className="w-search"><Icon name="search" size={18} /><span className="sr-only">Поиск по событиям</span><input type="search" placeholder="Поиск по событиям и темам" value={query} onChange={event => setQuery(event.target.value)} />{query && <button aria-label="Очистить поиск" onClick={() => setQuery('')}><Icon name="close" size={16} /></button>}</label>
      {feed.isPending && <StatePanel title="Загружаем события…" text="Это займёт несколько секунд." />}
      {feed.isError && !feed.data && <StatePanel tone="error" title="Лента не загрузилась" text={feed.error.message} action={<Button onClick={() => feed.refetch()}>Повторить</Button>} />}
      {!feed.isPending && !feed.isError && !visibleItems.length && (missingKind ? <StatePanel title={emptyKindLabels[missingKind].title} text={otherRoleItem ? `Такие события есть для роли «${roleName(otherRoleItem.role)}».` : 'Попробуйте другой тип событий или обновите ленту позже.'} action={otherRoleItem ? <Button onClick={() => { setActiveRole(otherRoleItem.role); feedHeading.current?.focus(); }}>{emptyKindLabels[missingKind].action}</Button> : <Button onClick={() => selectFilter('all')}>Все события этой роли</Button>} /> : <StatePanel title={roleItems.length ? 'Ничего не найдено' : allItems.length ? 'Для этой роли пока нет событий' : 'В ленте пока нет событий'} text={roleItems.length ? 'Попробуйте другой запрос или фильтр.' : allItems.length ? 'Обновите ленту или выберите другую роль вверху страницы.' : 'Здесь появятся события, важные для вашей компании. Можно обновить ленту кнопкой рядом с её заголовком.'} action={roleItems.length ? <Button onClick={() => { selectFilter('all'); setQuery(''); }}>Сбросить фильтры</Button> : undefined} />)}
      <div className="w-feed">{visibleItems.map(item => <EventCard key={item.id} item={item} keywords={keywords} roleName={roleName(item.role)} saved={saved.includes(item.id)} onToggleSave={() => toggleSaved(item.id)} />)}</div>
    </section><aside className="w-context-column"><WidgetBoard storageKey={localKey(userId, 'widgets', user.companyId)} />{isDemoMode ? <DemoChat userId={userId} companyId={user.companyId} itemTitle="события в вашей ленте" roleName={activeRole ? roleName(activeRole) : 'роль не выбрана'} compact /> : <section className="w-panel"><h2>Уточнить разбор</h2><p className="w-muted">Вопросы и ответы доступны внутри связанной бизнес-ситуации.</p></section>}</aside></div>
    {refreshNotice && <div className="w-toast feed-refresh-notice" role="status">{refreshNotice}</div>}
  </>;
}
