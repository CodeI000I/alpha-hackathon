import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, isDemoMode } from '../api/client';
import type { BusinessIssue } from '../api/types';
import { Button, StatePanel } from './ui';

const urgencyLabel: Record<BusinessIssue['urgency'], string> = {
  none: 'Без срочности', monitor: 'Наблюдать', soon: 'Скоро', immediate: 'Срочно', unknown: 'Срочность не указана',
};
const effectLabel: Record<BusinessIssue['overall_effect'], string> = {
  risk: 'Риск', opportunity: 'Возможность', mixed: 'Смешанное влияние', neutral: 'Нейтрально', unknown: 'Влияние уточняется',
};
const terminalJobs = new Set(['completed', 'failed']);

export default function AnalyticsOverview({ role }: { role: string }) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState('');
  const situation = useQuery({ queryKey: ['analytics', 'situation', role], queryFn: ({ signal }) => api.analytics.situation(role, signal), enabled: Boolean(role) && !isDemoMode });
  const issues = useQuery({ queryKey: ['analytics', 'issues', role], queryFn: ({ signal }) => api.analytics.issues(role, 0, 50, signal), enabled: Boolean(role) && !isDemoMode });
  const job = useQuery({ queryKey: ['analytics', 'job', role, jobId], queryFn: ({ signal }) => api.analytics.job(jobId, role, signal), enabled: Boolean(jobId) && !isDemoMode, refetchInterval: (query) => query.state.data && terminalJobs.has(query.state.data.status) ? false : 1500 });
  const refresh = useMutation({ mutationFn: () => api.analytics.refresh(role, { reason: 'user_requested' }), onSuccess: (result) => setJobId(result.job_id) });
  useEffect(() => {
    if (job.data?.status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'situation', role] });
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'issues', role] });
    }
  }, [job.data?.status, queryClient, role]);

  if (isDemoMode) return <section className="analytics-overview w-panel" aria-label="Аналитические ситуации"><h2>Бизнес-ситуации</h2><p className="w-muted">В деморежиме аналитические ситуации сервера недоступны. Здесь не показаны синтетические оценки влияния.</p></section>;
  if (!role) return <section className="analytics-overview w-panel" aria-label="Аналитические ситуации"><h2>Бизнес-ситуации</h2><p className="w-muted">Выберите роль, чтобы получить обзор по её бизнес-задачам.</p></section>;

  return <section className="analytics-overview w-panel" aria-label="Аналитические ситуации">
    <header className="analytics-overview-header"><div><span className="w-eyebrow">АНАЛИТИКА КОМПАНИИ</span><h2>Текущая ситуация</h2></div><Button variant="secondary" disabled={refresh.isPending || !role} onClick={() => refresh.mutate()}>{refresh.isPending ? 'Ставим в очередь…' : 'Обновить анализ'}</Button></header>
    {situation.isPending && <StatePanel title="Загружаем обзор компании…" />}
    {situation.isError && !situation.data && <StatePanel tone="error" title="Обзор не загрузился" text={situation.error.message} action={<Button onClick={() => situation.refetch()}>Повторить</Button>} />}
    {situation.data && <div className="analytics-situation">
      {!situation.data.snapshot ? <StatePanel title="Аналитика ещё готовится" text="После обработки новостей здесь появится обзор текущих бизнес-ситуаций." /> : <>
        {!situation.data.current && <p className="integration-warning" role="status">Сводка может быть устаревшей. Запустите обновление, чтобы проверить изменения.</p>}
        <p className="analytics-summary">{situation.data.snapshot.overall.summary}</p>
        {situation.data.snapshot.overall.actions.length > 0 && <section><h3>Что можно сделать</h3><ul>{situation.data.snapshot.overall.actions.map((action, index) => <li key={`${index}-${action}`}>{action}</li>)}</ul></section>}
        {situation.data.snapshot.overall.key_unknowns.length > 0 && <details><summary>Что пока неизвестно</summary><ul>{situation.data.snapshot.overall.key_unknowns.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></details>}
        <p className="w-small">Обновлено {new Date(situation.data.snapshot.as_of).toLocaleString('ru-RU')} · {situation.data.current ? 'актуальная сводка' : 'есть необработанные изменения'}</p>
      </>}
    </div>}
    {refresh.isError && <p className="integration-warning" role="alert">Не удалось запустить обновление: {refresh.error.message}</p>}
    {job.data && <p className="analytics-job" role="status">Обновление: {job.data.status === 'queued' ? 'в очереди' : job.data.status === 'running' ? 'выполняется' : job.data.status === 'completed' ? 'завершено' : job.data.status === 'failed' ? 'завершилось с ошибкой' : job.data.status}{job.data.error ? ` · ${String(job.data.error)}` : ''}</p>}
    {job.isError && <p className="integration-warning" role="alert">Не удалось проверить состояние обновления: {job.error.message}</p>}
    <div className="analytics-issue-list"><header><h3>Важные ситуации</h3><span>{issues.data?.length ?? 0}</span></header>
      {issues.isPending && <p role="status">Загружаем список ситуаций…</p>}
      {issues.isError && !issues.data && <StatePanel tone="error" title="Список ситуаций не загрузился" text={issues.error.message} action={<Button onClick={() => issues.refetch()}>Повторить</Button>} />}
      {issues.data?.length === 0 && <p className="w-muted">Активных бизнес-ситуаций пока нет.</p>}
      {issues.data?.map((issue) => <Link className="analytics-issue" key={issue.issue_id} to={`/issues/${encodeURIComponent(issue.issue_id)}`}>
        <span className={`analytics-effect ${issue.overall_effect}`}>{effectLabel[issue.overall_effect]}</span><span className="analytics-urgency">{urgencyLabel[issue.urgency]}</span><strong>{issue.title}</strong><p>{issue.summary}</p><small>{issue.business_factors.join(' · ') || 'Факторы не указаны'} · v{issue.version}</small>
      </Link>)}
    </div>
  </section>;
}
