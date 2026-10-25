import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api, isDemoMode } from '../api/client';
import { useWorkspace } from '../appContext';
import { Button, StatePanel } from '../components/ui';
import type { AnalyticsEvidencePack } from '../api/types';
import { localKey, useStoredState } from '../localState';

function makeId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
function safeHttpUrl(value: string | null): string | null {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null; } catch { return null; }
}
function dateText(value: string): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('ru-RU') : 'Дата не указана';
}
function evidenceTarget(packIndex: number, kind: string, reference: string, itemIndex: number): string {
  return `evidence-${packIndex}-${kind}-${encodeURIComponent(reference)}-${itemIndex}`;
}
function evidenceTargets(packs: AnalyticsEvidencePack[] | undefined): Map<string, string> {
  const targets = new Map<string, string>();
  const repeated = new Set<string>();
  const add = (reference: string, target: string) => {
    if (repeated.has(reference)) return;
    if (targets.has(reference)) {
      targets.delete(reference);
      repeated.add(reference);
      return;
    }
    targets.set(reference, target);
  };
  for (const [packIndex, pack] of (packs ?? []).entries()) {
    pack.company_facts.forEach((fact, itemIndex) => add(fact.fact_id, evidenceTarget(packIndex, 'fact', fact.fact_id, itemIndex)));
    pack.chunks.forEach((chunk, itemIndex) => add(chunk.chunk_id, evidenceTarget(packIndex, 'chunk', chunk.chunk_id, itemIndex)));
    pack.candidate_paths.forEach((path, itemIndex) => add(path.path_id, evidenceTarget(packIndex, 'path', path.path_id, itemIndex)));
    // The API returns both lists sorted by evidence ID. If old article revisions
    // were collapsed, their counts differ; leave those citations unlinked.
    if (pack.event.source_news_ids.length === pack.news.length) {
      [...pack.event.source_news_ids].sort().forEach((reference, itemIndex) => add(reference, evidenceTarget(packIndex, 'news', reference, itemIndex)));
    }
  }
  return targets;
}

export default function IssueDetailPage() {
  const { issueId = '' } = useParams();
  const { user, activeRole } = useWorkspace();
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');
  const pendingRequest = useRef<{ question: string; id: string } | null>(null);
  const [conversationId, setConversationId] = useStoredState(localKey(user.id, `issue-chat-${issueId}-${activeRole}`, user.companyId), makeId());
  const issueQuery = useQuery({ queryKey: ['analytics', 'issue', activeRole, issueId], queryFn: ({ signal }) => api.analytics.issue(issueId, activeRole, signal), enabled: !!issueId && !!activeRole && !isDemoMode });
  const evidenceVersion = issueQuery.data?.version;
  const evidenceQuery = useQuery({ queryKey: ['analytics', 'evidence', activeRole, issueId, evidenceVersion], queryFn: ({ signal }) => api.analytics.evidence(issueId, activeRole, signal, evidenceVersion), enabled: !!issueId && !!activeRole && !!evidenceVersion && !isDemoMode });
  const historyQuery = useQuery({ queryKey: ['analytics', 'history', activeRole, issueId], queryFn: ({ signal }) => api.analytics.history(issueId, activeRole, signal), enabled: !!issueId && !!activeRole && !isDemoMode });
  const stateQuery = useQuery({ queryKey: ['analytics', 'state', activeRole, issueId], queryFn: ({ signal }) => api.analytics.state(issueId, activeRole, signal), enabled: !!issueId && !!activeRole && !isDemoMode });
  const conversationQuery = useQuery({ queryKey: ['analytics', 'conversation', activeRole, conversationId], queryFn: ({ signal }) => api.analytics.conversation(conversationId, activeRole, signal), enabled: !!conversationId && !!activeRole && !isDemoMode, retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1 });
  const updateState = useMutation({ mutationFn: (value: { workflow: 'open' | 'watching' | 'closed'; pinned: boolean; mark_read?: boolean }) => api.analytics.setState(issueId, activeRole, value), onSuccess: (state) => queryClient.setQueryData(['analytics', 'state', activeRole, issueId], state) });
  const ask = useMutation({ mutationFn: () => {
    const current = pendingRequest.current;
    if (!current) throw new Error('Введите вопрос.');
    return api.analytics.ask(issueId, activeRole, { question: current.question, conversation_id: conversationId, request_id: current.id, version: conversationQuery.data?.issue_version ?? issueQuery.data?.version });
  }, onSuccess: () => { setQuestion(''); pendingRequest.current = null; void queryClient.invalidateQueries({ queryKey: ['analytics', 'conversation', activeRole, conversationId] }); }, onError: (error) => {
    if (error instanceof ApiError && error.status === 409) {
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'issue', activeRole, issueId] });
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'conversation', activeRole, conversationId] });
    }
  } });

  useEffect(() => {
    if (stateQuery.data?.unread && !updateState.isPending) {
      updateState.mutate({ workflow: stateQuery.data.workflow, pinned: stateQuery.data.pinned, mark_read: true });
    }
  }, [stateQuery.data?.unread, stateQuery.data?.workflow, stateQuery.data?.pinned]);

  const history = useMemo(() => [...(historyQuery.data ?? [])].sort((left, right) => left.version - right.version), [historyQuery.data]);
  const linkedEvidence = useMemo(() => evidenceTargets(evidenceQuery.data), [evidenceQuery.data]);
  if (isDemoMode) return <StatePanel title="Разборы бизнес-ситуаций недоступны в деморежиме" text="Для просмотра используются только данные аналитического сервиса." action={<Link className="button button--secondary" to="/dashboard">Вернуться к обзору</Link>} />;
  if (!activeRole) return <StatePanel title="Для разбора нужна роль" text="Выберите роль в профиле и откройте ситуацию ещё раз." action={<Link className="button button--secondary" to="/profile?tab=roles">Перейти к ролям</Link>} />;
  if (issueQuery.isPending) return <StatePanel title="Загружаем разбор ситуации…" />;
  if (issueQuery.isError && !issueQuery.data) return <StatePanel tone="error" title="Разбор ситуации не загрузился" text={issueQuery.error.message} action={<><Button onClick={() => issueQuery.refetch()}>Повторить</Button><Link className="button button--secondary" to="/dashboard">К обзору</Link></>} />;
  if (!issueQuery.data) return <StatePanel title="Ситуация не найдена" action={<Link className="button button--secondary" to="/dashboard">К обзору</Link>} />;

  const issue = issueQuery.data;
  const conversationNotFound = conversationQuery.error instanceof ApiError && conversationQuery.error.status === 404;
  const conversationStale = Boolean(conversationQuery.data && conversationQuery.data.issue_version !== issue.version);
  const startNewConversation = () => {
    if (ask.isPending) return;
    setConversationId(makeId()); setQuestion(''); pendingRequest.current = null; ask.reset();
  };
  const submitQuestion = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = question.trim();
    if (!normalized) return;
    if (pendingRequest.current?.question !== normalized) pendingRequest.current = { question: normalized, id: makeId() };
    ask.mutate();
  };
  const togglePinned = () => updateState.mutate({ workflow: stateQuery.data?.workflow ?? 'open', pinned: !stateQuery.data?.pinned, mark_read: true });
  const setWorkflow = (workflow: 'open' | 'watching' | 'closed') => updateState.mutate({ workflow, pinned: stateQuery.data?.pinned ?? false, mark_read: true });

  return <main className="analytics-detail">
    <div className="w-news-toolbar"><Link className="action-back" to="/dashboard">← Все ситуации</Link><span className="w-chip">{issue.status}</span></div>
    <article className="analytics-issue-detail w-panel">
      <header><div><span className="w-eyebrow">БИЗНЕС-СИТУАЦИЯ · ВЕРСИЯ {issue.version}</span><h1>{issue.title}</h1><p className="w-muted">{issue.overall_effect} · срочность: {issue.urgency} · горизонт: {issue.horizon}</p></div>
        <Button variant="secondary" disabled={updateState.isPending || stateQuery.isPending} aria-pressed={stateQuery.data?.pinned ?? false} onClick={togglePinned}>{stateQuery.data?.pinned ? 'Снять закрепление' : 'Закрепить ситуацию'}</Button>
      </header>
      <p>{issue.summary}</p>
      <p><strong>Предлагаемый шаг:</strong> {issue.suggested_action}</p>
      {issue.exposure && <p><strong>Связь с компанией:</strong> {issue.exposure}</p>}
      <div className="analytics-detail-meta"><span>Достаточность оснований: {issue.evidence_sufficiency}</span><span>Факторы: {issue.business_factors.join(', ') || 'не указаны'}</span><span>Обновлено: {dateText(issue.as_of)}</span></div>
      {issue.key_unknowns.length > 0 && <section><h2>Что пока неизвестно</h2><ul>{issue.key_unknowns.map((item) => <li key={item}>{item}</li>)}</ul></section>}
      {issue.conditions.length > 0 && <section><h2>Условия</h2><ul>{issue.conditions.map((item) => <li key={item}>{item}</li>)}</ul></section>}
      <section className="analytics-state-controls"><h2>Моё состояние</h2><div>{(['open', 'watching', 'closed'] as const).map((workflow) => <Button key={workflow} variant={stateQuery.data?.workflow === workflow ? 'primary' : 'secondary'} disabled={updateState.isPending} aria-pressed={stateQuery.data?.workflow === workflow} onClick={() => setWorkflow(workflow)}>{workflow === 'open' ? 'Открыта' : workflow === 'watching' ? 'Наблюдать' : 'Закрыта'}</Button>)}</div>{stateQuery.isError && <p role="alert">Не удалось загрузить состояние: {stateQuery.error.message}</p>}{updateState.isError && <p role="alert">Не удалось сохранить состояние: {updateState.error.message}</p>}</section>
    </article>
    <section className="analytics-detail-section w-panel"><h2>Основания и источники</h2>
      {evidenceQuery.isPending && <p role="status">Загружаем основания…</p>}
      {evidenceQuery.isError && <StatePanel tone="error" title="Основания не загрузились" text={evidenceQuery.error.message} action={<Button onClick={() => evidenceQuery.refetch()}>Повторить</Button>} />}
      {evidenceQuery.data?.map((pack, index) => <article className="analytics-evidence-pack" key={`${pack.event.event_id}-${index}`}><h3>{pack.event.summary}</h3><p className="w-muted">Модальность: {pack.event.modality}</p>
        {pack.event.evidence_quote && <blockquote>{pack.event.evidence_quote}</blockquote>}
        {pack.news.map((news, newsIndex) => { const url = safeHttpUrl(news.source_url); const ref = pack.event.source_news_ids.length === pack.news.length ? [...pack.event.source_news_ids].sort()[newsIndex] : undefined; return <div className="analytics-evidence-item" id={ref ? evidenceTarget(index, 'news', ref, newsIndex) : undefined} key={`${news.title}-${newsIndex}`}><strong>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{news.title}</a> : news.title}</strong><p>{news.content}</p><small>{dateText(news.published_at)}</small></div>; })}
        {pack.company_facts.map((fact, itemIndex) => <details className="analytics-evidence-item" id={evidenceTarget(index, 'fact', fact.fact_id, itemIndex)} key={`${fact.fact_id}-${itemIndex}`}><summary>Факт компании · {fact.verification_status}</summary><p>{fact.text}</p>{fact.source_quote && <blockquote>{fact.source_quote}</blockquote>}<small>{fact.source_refs.join(' · ')}</small></details>)}
        {pack.chunks.map((chunk, itemIndex) => <details className="analytics-evidence-item" id={evidenceTarget(index, 'chunk', chunk.chunk_id, itemIndex)} key={`${chunk.chunk_id}-${itemIndex}`}><summary>Документ · {chunk.locator || chunk.document_id}</summary><p>{chunk.text}</p></details>)}
        {pack.candidate_paths.map((path, itemIndex) => <details className="analytics-evidence-item" id={evidenceTarget(index, 'path', path.path_id, itemIndex)} key={`${path.path_id}-${itemIndex}`}><summary>Связь · {path.status}</summary><p>{path.relation_types.join(' → ')}</p><small>Основания: {path.evidence_refs.join(', ')}</small></details>)}
      </article>)}
      {evidenceQuery.data?.length === 0 && <p className="w-muted">Подтверждённые основания не переданы.</p>}
    </section>
    <section className="analytics-detail-section w-panel"><h2>История изменений</h2>
      {historyQuery.isPending && <p role="status">Загружаем историю…</p>}
      {historyQuery.isError && <StatePanel tone="error" title="История не загрузилась" text={historyQuery.error.message} action={<Button onClick={() => historyQuery.refetch()}>Повторить</Button>} />}
      {history.map((version) => <article className="analytics-history-item" key={`${version.issue_id}-${version.version}`}><small>Версия {version.version} · {dateText(version.as_of)} · {version.status}</small><h3>{version.title}</h3><p>{version.summary}</p></article>)}
    </section>
    <section className="analytics-chat w-panel"><h2>Уточнить ситуацию</h2>
      {conversationQuery.isPending && <p role="status">Загружаем закреплённый диалог…</p>}
      {conversationQuery.data && <p className="w-small">Диалог закреплён за версией {conversationQuery.data.issue_version}</p>}
      {conversationNotFound && <p className="w-small">Новый диалог для версии {issue.version}</p>}
      {conversationStale && <div className="integration-warning" role="status"><p>Текущая ситуация обновилась до версии {issue.version}. Этот диалог относится к версии {conversationQuery.data?.issue_version}.</p><Button variant="secondary" disabled={ask.isPending} onClick={startNewConversation}>Начать новый диалог для версии {issue.version}</Button></div>}
      {conversationQuery.isError && !conversationNotFound && <p role="alert">Не удалось загрузить историю вопросов: {conversationQuery.error.message} <Button variant="secondary" onClick={() => conversationQuery.refetch()}>Повторить</Button></p>}
      {conversationQuery.data?.replies.map((reply) => <article className="analytics-chat-reply" key={reply.request_id}><p className="analytics-chat-question">{reply.question}</p><p>{reply.answer.text}</p>{reply.answer.evidence_ids.length > 0 && <small>Основания: {reply.answer.evidence_ids.map((reference, index) => {
        const target = conversationQuery.data?.issue_version === issue.version ? linkedEvidence.get(reference) : undefined;
        return <span key={`${reference}-${index}`}>{index > 0 ? ', ' : ''}{target ? <a href={`#${target}`} onClick={() => { const element = document.getElementById(target); if (element instanceof HTMLDetailsElement) element.open = true; }}>{reference}</a> : reference}</span>;
      })}</small>}{reply.answer.missing_facts.length > 0 && <small>Не хватает данных: {reply.answer.missing_facts.join(', ')}</small>}</article>)}
      <form onSubmit={submitQuestion}><label htmlFor="issue-question">Вопрос об этой ситуации</label><textarea id="issue-question" value={question} maxLength={6000} onChange={(event) => setQuestion(event.target.value)} required disabled={conversationQuery.isPending || conversationStale || (conversationQuery.isError && !conversationNotFound)} /><Button type="submit" disabled={ask.isPending || !question.trim() || conversationQuery.isPending || conversationStale || (conversationQuery.isError && !conversationNotFound)}>{ask.isPending ? 'Готовим ответ…' : 'Задать вопрос'}</Button></form>
      {ask.isError && <p role="alert">Не удалось получить ответ. Повторите отправку без изменения текста, чтобы сохранить тот же идентификатор запроса: {ask.error.message}</p>}
    </section>
  </main>;
}
