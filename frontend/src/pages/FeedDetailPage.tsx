import { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, isDemoMode } from '../api/client';
import { useWorkspace } from '../appContext';
import { DemoChat } from '../components/DemoChat';
import { Icon } from '../components/Icon';
import { Button, DemoBadge, StatePanel } from '../components/ui';
import { localKey } from '../localState';
import { ActionIcon } from '../signal/components/ActionIcon';
import { AnalysisHeading } from '../signal/components/AnalysisHeading';
import { BankOffer } from '../signal/BankSolutions';
import { assignedFeed, BANK_NOT_USED, BANK_UNKNOWN, dateLabel, DISCLAIMER, exportReport, KIND_LABELS, relevance, sourceLabel, sourceUrl } from '../report';

export default function FeedDetailPage({ userId }: { userId: number }) {
  const { itemId } = useParams(); const navigate = useNavigate();
  const { user, company, roles, saved, toggleSaved } = useWorkspace();
  const dialog = useRef<HTMLDialogElement>(null); const returnFocus = useRef<HTMLElement | null>(null);
  const feed = useQuery({ queryKey: ['feed', userId, user.roles], queryFn: ({ signal }) => api.feed(userId, undefined, 200, signal) });
  const items = assignedFeed(feed.data, user.roles); const item = items.find(value => String(value.id) === itemId);
  const showSources = () => { returnFocus.current = document.activeElement as HTMLElement; dialog.current?.showModal(); };
  const closeSources = () => dialog.current?.close();
  if (feed.isPending) return <StatePanel title="Открываем разбор…" text="Ищем событие в последних 200 записях ленты." />;
  if (feed.isError && !feed.data) return <StatePanel tone="error" title="Не удалось загрузить разбор" text={feed.error.message} action={<Button onClick={() => feed.refetch()}>Повторить</Button>} />;
  if (!item) return <StatePanel title="Событие не найдено" text="Его нет среди последних 200 записей для назначенных вам ролей. Событие могло выйти за пределы выборки." action={<Link className="button button--secondary" to="/dashboard">Вернуться в обзор</Link>} />;
  const roleName = roles.find(role => role.code === item.role)?.name ?? item.role;
  const url = sourceUrl(item.news.url);
  const source = sourceLabel(item);
  const download = () => {
    const blob = new Blob([exportReport(item, { company, roleName, demo: isDemoMode })], { type: 'text/plain;charset=utf-8' });
    const objectUrl = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = 'signal-' + item.id + '.txt'; anchor.click(); setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  };
  return <>
    {feed.isRefetchError && <p className="integration-warning" role="alert">Не удалось обновить разбор. Показаны ранее полученные данные. <button onClick={() => feed.refetch()}>Повторить</button></p>}
    <div className="w-news-toolbar"><Link className="action-back" to="/dashboard"><ActionIcon direction="back" />Все события</Link></div>
    <div className="w-detail-grid">
      <aside className="w-news-list" aria-label="Другие события"><span className="w-eyebrow">Другие события</span>{items.slice(0, 12).map(value => <button key={value.id} className={value.id === item.id ? 'active' : ''} onClick={() => navigate('/news/' + value.id)}><span className={value.kind}>{KIND_LABELS[value.kind]}</span><strong>{value.news.title}</strong></button>)}</aside>
      <article className="w-detail">
        <div className="w-detail-topline"><div className="w-chips"><span className={'w-chip ' + item.kind}>{KIND_LABELS[item.kind]}</span><span className="w-chip">{roleName}</span>{isDemoMode && <DemoBadge />}</div><button className="w-icon" aria-label={saved.includes(item.id) ? 'Убрать из закладок (демо)' : 'Сохранить в закладки (демо)'} aria-pressed={saved.includes(item.id)} onClick={() => toggleSaved(item.id)}><Icon name="bookmark" /></button></div>
        <h1>{item.news.title || 'Без заголовка'}</h1>
        <p className="signal-detail-meta">{dateLabel(item.news.publishedAt)} · Релевантность {relevance(item.score)}</p>
        <div className="w-detail-actions"><button className="download-analysis" onClick={download}>Скачать разбор TXT <ActionIcon /></button></div>
        <section className="w-analysis-section w-analysis-narrative"><AnalysisHeading title="Что произошло" category="Сообщение источника" /><p>{item.news.summary || 'Сообщение источника не передано.'}</p>{source && <button className="w-source-pill" onClick={showSources}>Источник: {source} <ActionIcon direction="external" /></button>}</section>
        <section className="w-analysis-section w-personal"><AnalysisHeading title="Значение для бизнеса" category="Интерпретация" /><p>{item.insight || 'Интерпретация не передана.'}</p><p className="signal-muted">Контекст: {company?.name ?? 'компания не указана'} · {roleName}. {item.elements.length ? 'Элементы профиля: ' + item.elements.join(', ') + '.' : 'Элементы профиля не переданы.'}</p></section>
        <section className="w-analysis-section w-scenarios"><AnalysisHeading title="Что может измениться" category="Гипотеза" /><p>Отдельные гипотезы, сценарии и расчёты сервером не переданы. Не используйте релевантность события как вероятность его наступления.</p></section>
        <section className="w-analysis-section"><AnalysisHeading title="Документы компании" category="Основания" /><p>API не сообщает, какие документы использованы в разборе. Наличие загруженного файла не подтверждает его анализ.</p><Link className="action-link" to="/profile?tab=documents">Мои документы <ActionIcon /></Link></section>
        <section className="w-analysis-section w-bank"><AnalysisHeading title="Материалы банка" category="Основания" /><p>{isDemoMode ? BANK_NOT_USED : BANK_UNKNOWN}</p></section>
        <div className="signal-demo-block"><DemoBadge>Отдельный демоблок</DemoBadge><BankOffer ids={['credit', 'factoring', 'ved']} context="Пример интерфейса банковских предложений. Подбор не основан на этом событии или документах компании." scope={'event-' + item.id} storageKey={localKey(userId, 'bank-offers', user.companyId)} /></div>
        <button className="action-link w-source-link" onClick={showSources}>Источники и основания <ActionIcon direction="external" /></button>
        <p className="w-analysis-disclaimer">{DISCLAIMER}</p>
      </article>
      <DemoChat key={item.id} userId={userId} companyId={user.companyId} itemId={item.id} itemTitle={item.news.title} roleName={roleName} />
    </div>
    <dialog className="w-dialog w-source-dialog" ref={dialog} aria-labelledby="sources-title" onClose={() => returnFocus.current?.focus()} onClick={event => { if (event.target === event.currentTarget) closeSources(); }}>
      <div className="w-dialog-heading w-source-header"><button className="action-back w-source-return" autoFocus onClick={closeSources}><ActionIcon direction="back" />К разбору новости</button><button className="w-icon" aria-label="Закрыть источники" onClick={closeSources}><Icon name="close" /></button></div>
      <div className="w-source-content"><h2 id="sources-title">Источники и основания</h2>{isDemoMode && <DemoBadge>Синтетические данные</DemoBadge>}
        <section className="w-source-section"><AnalysisHeading title="Сообщение источника" /><p>{item.news.sourceId || 'Источник не указан сервером.'}</p><p>{item.news.summary || 'Описание отсутствует.'}</p><p>{dateLabel(item.news.publishedAt)}</p>{url ? <a className="action-link" href={url} target="_blank" rel="noopener noreferrer">Открыть первоисточник <ActionIcon direction="external" /></a> : <p>Ссылка на первоисточник не передана или имеет неподдерживаемый формат.</p>}</section>
        <section className="w-source-section"><AnalysisHeading title="Интерпретация и гипотезы" /><p>Интерпретация получена из поля insight. Отдельные гипотезы и расчёты, сведения о модели и проверке вывода API не передаёт.</p></section>
        <section className="w-source-section"><AnalysisHeading title="Документы компании" /><p>Список использованных документов и цитаты не переданы. Мы не приписываем вывод загруженным файлам.</p></section>
        <section className="w-source-section w-source-bank-card"><AnalysisHeading title="Материалы банка" /><p>{isDemoMode ? BANK_NOT_USED : BANK_UNKNOWN}</p></section>
        <p className="w-analysis-disclaimer">{DISCLAIMER}</p>
      </div>
    </dialog>
  </>;
}
