import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, isDemoMode } from "../api/client";
import type { ProfileElement } from "../api/types";
import { useWorkspace } from "../appContext";
import RolePicker from "../components/RolePicker";
import { StatePanel } from "../components/ui";
import { Button } from "../signal/components/ui";
import { Chart, Directions, Keywords } from "../signal/Insights";
import { localKey, useStoredState } from "../localState";
import { profileBlockLabel, profileValueText } from "../profilePresentation";
import "../auth/integration.css";
import "../auth/profile.css";

const tabs = ["roles", "company", "keywords", "documents"] as const;
type Tab = (typeof tabs)[number];
const tabLabels: Record<Tab, string> = { roles: "Моя роль", company: "Компания", keywords: "Ключевые слова", documents: "Документы" };
interface UploadTask { id: number; file: File; state: "sending" | "success" | "error"; message?: string; retryable?: boolean }
export function validateDocument(file: Pick<File, "name" | "size">): string | undefined {
  if (!/\.(pdf|txt|docx|xlsx)$/i.test(file.name)) return "Допустимы только PDF, TXT, DOCX и XLSX.";
  if (file.size > 12 * 1024 * 1024) return "Файл больше 12 МБ. Выберите файл меньшего размера.";
  if (file.size === 0) return "Файл пуст. Выберите документ с содержимым.";
  return undefined;
}
function groupElements(elements: ProfileElement[]) {
  return elements.reduce<Record<string, ProfileElement[]>>((groups, element) => { (groups[element.block || "Без группы"] ??= []).push(element); return groups; }, {});
}
function formatDate(value: string): string {
  const date = new Date(value); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(date) : "Дата не передана";
}

export default function CompanyPage({ userId }: { userId: number }) {
  const { activeRole } = useWorkspace();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [retryJobId, setRetryJobId] = useState("");
  const rawTab = searchParams.get("tab");
  const tab: Tab = tabs.includes(rawTab as Tab) ? rawTab as Tab : rawTab === "analytics" ? "company" : "roles";
  const user = useQuery({ queryKey: ["user", userId], queryFn: ({ signal }) => api.user(userId, signal) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const companyId = user.data?.companyId ?? null;
  const company = useQuery({ queryKey: ["company", companyId], queryFn: ({ signal }) => api.company(companyId!, signal), enabled: companyId !== null });
  const elements = useQuery({ queryKey: ["profile-elements"], queryFn: api.profileElements, enabled: tab === "company" });
  const files = useQuery({ queryKey: ["files", companyId], queryFn: ({ signal }) => api.files(companyId!, signal), enabled: companyId !== null });
  const analyticsDocuments = useQuery({ queryKey: ["analytics", "documents", activeRole], queryFn: ({ signal }) => api.analytics.documents(activeRole, signal), enabled: tab === "documents" && Boolean(activeRole) && !isDemoMode, refetchInterval: (query) => query.state.data?.some((document) => document.status === "queued") ? 3000 : false });
  const retryJob = useQuery({ queryKey: ["analytics", "document-retry-job", activeRole, retryJobId], queryFn: ({ signal }) => api.analytics.job(retryJobId, activeRole, signal), enabled: Boolean(retryJobId) && !isDemoMode, refetchInterval: (query) => query.state.data && ["completed", "failed"].includes(query.state.data.status) ? false : 1500 });
  const retryFailedDocuments = useMutation({
    mutationFn: () => api.analytics.refresh(activeRole, { reason: "retry_failed_documents", retry_failed: true }),
    onSuccess: (job) => {
      setRetryJobId(job.job_id);
      void queryClient.invalidateQueries({ queryKey: ["analytics", "documents", activeRole] });
    },
  });
  useEffect(() => {
    if (retryJob.data?.status === "completed") void queryClient.invalidateQueries({ queryKey: ["analytics", "documents", activeRole] });
  }, [retryJob.data?.status, queryClient, activeRole]);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  const roleDialog = useRef<HTMLDialogElement>(null);
  const roleTrigger = useRef<HTMLButtonElement>(null);
  const [keywords, setKeywords] = useStoredState<string[]>(localKey(userId, "keywords", companyId), []);
  const [directions, setDirections] = useStoredState<number[]>(localKey(userId, "directions", companyId), [50, 50, 50, 50, 50]);
  const [notice, setNotice] = useState("");
  const [uploads, setUploads] = useState<UploadTask[]>([]);
  const uploadSequence = useRef(0);
  useEffect(() => {
    if (!user.data || roleDialogOpen) return;
    const available = roles.data ? new Set(roles.data.map((role) => role.code)) : null;
    setSelectedRoles(available ? user.data.roles.filter((code) => available.has(code)) : user.data.roles);
  }, [user.data, roles.data, roleDialogOpen]);
  useEffect(() => {
    const dialog = roleDialog.current;
    if (!dialog || !roleDialogOpen) return;
    dialog.showModal();
    return () => { dialog.close(); roleTrigger.current?.focus({ preventScroll: true }); };
  }, [roleDialogOpen]);
  useEffect(() => { setUploads([]); }, [companyId]);
  const grouped = useMemo(() => groupElements(elements.data ?? []), [elements.data]);
  const saveRoles = useMutation({
    mutationFn: () => api.setRoles(userId, selectedRoles),
    onSuccess: (updated) => {
      queryClient.setQueryData(["user", userId], updated);
      setSelectedRoles(updated.roles);
      void queryClient.invalidateQueries({ queryKey: ["feed", userId] });
      setRoleDialogOpen(false);
      setNotice("Роли сохранены.");
    },
  });
  const uploadFile = async (task: UploadTask) => {
    if (companyId === null) return;
    setUploads((current) => current.map((item) => item.id === task.id ? { ...item, state: "sending", message: undefined } : item));
    try {
      await api.uploadFile(companyId, task.file);
      setUploads((current) => current.map((item) => item.id === task.id ? { ...item, state: "success", message: "Загружен. Анализ пока не подтверждён." } : item));
      await queryClient.invalidateQueries({ queryKey: ["files", companyId] });
      if (!isDemoMode) await queryClient.invalidateQueries({ queryKey: ["analytics", "documents", activeRole] });
    } catch (error) {
      setUploads((current) => current.map((item) => item.id === task.id ? { ...item, state: "error", retryable: true, message: error instanceof Error ? error.message : "Не удалось загрузить документ." } : item));
    }
  };
  const enqueue = (selectedFiles: File[]) => {
    const tasks: UploadTask[] = selectedFiles.map((file) => {
      const problem = validateDocument(file);
      return { id: ++uploadSequence.current, file, state: problem ? "error" : "sending", message: problem, retryable: false };
    });
    setUploads((current) => [...current, ...tasks]);
    for (const task of tasks) if (task.state === "sending") void uploadFile(task);
  };
  if (user.isLoading) return <StatePanel title="Загружаем профиль…" />;
  if (user.isError && !user.data) return <StatePanel tone="error" title="Профиль не загрузился" text={user.error.message} action={<Button onClick={() => user.refetch()}>Повторить</Button>} />;
  if (!user.data) return <StatePanel title="Профиль не найден" />;
  const companyState = companyId === null ? <StatePanel title="Компания не указана" text="Документы и сведения о компании пока недоступны." /> : company.isLoading ? <StatePanel title="Загружаем компанию…" /> : company.isError && !company.data ? <StatePanel tone="error" title="Компания не загрузилась" text={company.error.message} action={<Button onClick={() => company.refetch()}>Повторить</Button>} /> : null;

  return <div className="signal-profile">
    <div className="w-heading"><div><h1>Личный кабинет</h1><p className="w-muted">{user.data.fullName}{company.data ? ` · ${company.data.name}` : ""}</p></div></div>
    <nav className="w-profile-tabs" aria-label="Разделы личного кабинета">{tabs.map((item) => <button className={tab === item ? "active" : ""} aria-current={tab === item ? "page" : undefined} onClick={() => { setSearchParams({ tab: item }); setNotice(""); }} key={item}>{tabLabels[item]}{item === "documents" && <span>{files.data?.length ?? 0}</span>}</button>)}</nav>
    {notice && <div className="signal-profile-notice" role="status">{notice}<button type="button" aria-label="Закрыть сообщение" onClick={() => setNotice("")}>×</button></div>}
    <div className="w-profile-grid"><section className="w-panel w-profile-panel">
      {tab === "roles" && <div className="w-form">
        <h2>Моя роль</h2><dl className="profile-person"><div><dt>Имя</dt><dd>{user.data.fullName}</dd></div><div><dt>Электронная почта</dt><dd>{user.data.email}</dd></div></dl>
        <section className="profile-role-summary"><div className="profile-role-summary-heading"><h3>{user.data.roles.length > 1 ? "Ваши роли в компании" : "Ваша роль в компании"}</h3><button ref={roleTrigger} className="profile-role-edit" type="button" aria-label={user.data.roles.length ? "Изменить роли" : "Выбрать роли"} disabled={roles.isError || roles.isLoading || !roles.data?.length} onClick={() => { setSelectedRoles(user.data.roles.filter((code) => roles.data?.some((role) => role.code === code))); saveRoles.reset(); setRoleDialogOpen(true); }}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15l-1 6 5-2" /></svg>{user.data.roles.length ? "Изменить" : "Выбрать"}</button></div>
        {roles.isLoading && <p role="status">Загружаем роли…</p>}
        {roles.isError && <StatePanel tone="error" title="Роли не загрузились" text={roles.error.message} action={<Button onClick={() => roles.refetch()}>Повторить</Button>} />}
        {roles.data && <>{user.data.roles.length ? <ul className="profile-current-roles">{user.data.roles.map((code) => <li key={code}>{roles.data.find((role) => role.code === code)?.name || "Название роли недоступно"}</li>)}</ul> : <p className="w-muted">Роль пока не выбрана.</p>}</>}
        </section>
        <section className="profile-demo-section"><span className="w-demo">Демо</span><Directions values={directions} onChange={setDirections} editable /></section>
      </div>}
      {tab === "company" && (companyState || (company.data && <>
        <h2>{company.data.name}</h2>{isDemoMode && <span className="w-demo">Демо</span>}
        <dl className="w-company-details"><div><dt>ИНН</dt><dd>{company.data.inn || "Не указан"}</dd></div><div><dt>ОГРН</dt><dd>{company.data.ogrn || "Не указан"}</dd></div><div><dt>Обновлено</dt><dd>{formatDate(company.data.updatedAt)}</dd></div></dl>
        <h3>О компании</h3>
        {elements.isLoading && <p role="status">Загружаем сведения…</p>}
        {elements.isError && <StatePanel tone="error" title="Сведения не загрузились" text={elements.error.message} action={<Button onClick={() => elements.refetch()}>Повторить</Button>} />}
        <div className="signal-profile-elements">{Object.entries(grouped).map(([block, blockElements], index) => <details key={block} open={index === 0}><summary>{profileBlockLabel(block)}</summary><dl>{blockElements.map((element) => <div key={element.code}><dt>{element.name}</dt><dd>{profileValueText(company.data.profile[element.code], isDemoMode) ?? "Сведения получены · см. «О данных и сохранении»"}</dd></div>)}</dl></details>)}</div>
        {!Object.keys(company.data.profile).length && <p className="w-muted">Профиль компании пока не заполнен.</p>}
        {isDemoMode && <section className="company-analytics"><span className="w-demo">Демо</span><h3>Аналитика компании</h3><p className="w-muted">Пример с вымышленными показателями.</p><Chart /><div className="analytics-kpis"><div><span>Операционные расходы · пример</span><strong>31,5 млн ₽</strong><small>Синтетические данные</small></div><div><span>Денежный поток · пример</span><strong>+8,2 млн ₽</strong><small>Синтетические данные</small></div></div><Chart kind="supply" /></section>}
      </>))}
      {tab === "keywords" && <><span className="w-demo">Демо</span><Keywords words={keywords} onChange={setKeywords} /></>}
      {tab === "documents" && (companyState || <>
        <h2>Документы компании</h2>{isDemoMode && <p className="w-muted">В деморежиме файлы не отправляются.</p>}
        {isDemoMode && <span className="w-demo">Демо</span>}
        <label className="w-upload"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 13h8m-8 4h6" /></svg><strong>Выбрать документы</strong><span>PDF, TXT, DOCX, XLSX · до 12 МБ на файл</span><input type="file" multiple accept=".pdf,.txt,.docx,.xlsx" aria-label="Выбрать документы" onChange={(event) => { enqueue(Array.from(event.target.files ?? [])); event.target.value = ""; }} /></label>
        <p className="w-small">«Загружен» не означает «Проанализирован».</p>
        {!!uploads.length && <section className="signal-upload-results" aria-label="Результаты загрузки" aria-live="polite">{uploads.map((task) => <article key={task.id} className={`signal-upload-result is-${task.state}`}><strong>{task.file.name}</strong><p>{task.state === "sending" ? "Отправка…" : task.message}</p>{task.state === "error" && task.retryable && <Button variant="secondary" onClick={() => void uploadFile(task)}>Повторить загрузку</Button>}</article>)}</section>}
        <h3>Загруженные документы</h3>{files.isLoading && <p role="status">Загружаем список…</p>}
        {files.isError && <StatePanel tone="error" title="Список документов не загрузился" text={files.error.message} action={<Button onClick={() => files.refetch()}>Повторить</Button>} />}
        {!isDemoMode && activeRole && <section className="signal-document-analysis" aria-label="Статус анализа документов">
          <header><div><h3>Статус анализа</h3><p className="w-muted">Состояние обработки документов для выбранной роли.</p></div><Button variant="secondary" disabled={retryFailedDocuments.isPending || !analyticsDocuments.data?.some((document) => document.status === "failed")} onClick={() => retryFailedDocuments.mutate()}>{retryFailedDocuments.isPending ? "Ставим в очередь…" : "Повторить сбойные"}</Button></header>
          {analyticsDocuments.isPending && <p role="status">Загружаем статусы анализа…</p>}
          {analyticsDocuments.isError && <StatePanel tone="error" title="Статусы анализа не загрузились" text={analyticsDocuments.error.message} action={<Button onClick={() => analyticsDocuments.refetch()}>Повторить</Button>} />}
          {retryFailedDocuments.isError && <p className="integration-warning" role="alert">Не удалось повторить анализ: {retryFailedDocuments.error.message}</p>}
          {retryJob.data && <p role="status">Повторная обработка: {retryJob.data.status === "queued" ? "в очереди" : retryJob.data.status === "running" ? "выполняется" : retryJob.data.status === "completed" ? "завершена" : retryJob.data.status === "failed" ? "завершилась с ошибкой" : retryJob.data.status}</p>}
          {retryJob.isError && <p className="integration-warning" role="alert">Не удалось проверить повторную обработку: {retryJob.error.message}</p>}
          {analyticsDocuments.data?.map((document) => <article className={`w-document signal-document-analysis-item is-${document.status}`} key={`${document.file_id}-${document.document_id ?? "pending"}`}><div><strong>{document.filename}</strong><span>{document.status === "queued" ? "Ожидает анализа" : document.status === "ready" ? "Анализ завершён" : "Ошибка анализа"}</span>{document.status === "failed" && <small>{document.error || "Не удалось обработать файл"}{document.attempts > 0 ? ` · попыток: ${document.attempts}` : ""}</small>}{document.status === "queued" && document.retry_at && <small>Повтор после {new Date(document.retry_at * 1000).toLocaleString("ru-RU")}</small>}</div></article>)}
          {!analyticsDocuments.isLoading && !analyticsDocuments.isError && analyticsDocuments.data?.length === 0 && <p className="w-muted">Для этой роли документов пока нет.</p>}
        </section>}
        {files.data?.map((file) => <article className="w-document signal-document" key={file.id}><div><strong>{file.filename}</strong><small>{Math.max(1, Math.round(file.sizeBytes / 1024))} КБ · {formatDate(file.createdAt)}</small><span>{isDemoMode ? "Демо-файл · анализ сервера недоступен" : "Загружен"}</span></div></article>)}
        {!files.isLoading && !files.isError && files.data?.length === 0 && <StatePanel title="Документов пока нет" text="Здесь появятся добавленные вами материалы." />}
        <section className="signal-bank-materials"><h3>Материалы банка</h3><p className="w-muted">Сведения о материалах банка пока не переданы.</p></section>
      </>)}
    </section><aside className="w-panel w-profile-help"><h3>{tab === "company" ? "О компании" : tab === "keywords" ? "Темы для наблюдения" : tab === "roles" ? "Ваша роль" : "Документы"}</h3><p>{tab === "documents" ? "Добавьте отчёты и другие материалы вашей компании." : tab === "roles" ? "От вашей роли зависит подбор событий. Если обязанности изменились, обновите выбор." : tab === "company" ? "Сведения о вашей компании доступны для просмотра." : "Добавьте важные темы через запятую. Совпадения будут подсвечиваться в карточках событий."}</p><Link className="w-text-btn action-back" to="/dashboard"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M19 12H5m6-6-6 6 6 6" /></svg>Вернуться к событиям</Link><details className="data-note"><summary>О данных и сохранении</summary><p>{isDemoMode ? "Здесь используются подготовленные демонстрационные данные. Файлы и настройки остаются в этом браузере." : "Сведения о компании, роли и документы загружаются с сервера. При ошибке демонстрационные данные не подставляются."}</p><p>Ключевые слова и направления внимания сохраняются в этом браузере. Они не меняют подбор событий на сервере. Вход через Альфа-Бизнес пока не подключён.</p>{tab === "company" && <><p>Сведения доступны только для просмотра. Формат подробных данных ещё согласуется с командой backend.</p>{company.data && <details className="profile-raw-data"><summary>Полученные данные компании</summary><pre>{JSON.stringify(company.data.profile, null, 2)}</pre></details>}</>}{tab === "documents" && <p>Загрузка не подтверждает использование файла в разборе. Статус анализа, удаление и скачивание пока недоступны.</p>}</details></aside></div>
    <dialog ref={roleDialog} className="w-dialog profile-role-dialog" aria-labelledby="role-dialog-title" aria-describedby="role-dialog-description" onCancel={(event) => { event.preventDefault(); if (!saveRoles.isPending) setRoleDialogOpen(false); }}>
      <div className="profile-role-dialog-head"><h2 id="role-dialog-title">Роли в компании</h2><button type="button" className="w-icon" aria-label="Закрыть выбор ролей" disabled={saveRoles.isPending} onClick={() => setRoleDialogOpen(false)}>×</button></div>
      <div className="profile-role-dialog-body"><p id="role-dialog-description">Выберите одну или несколько ролей.</p>{roles.data && <RolePicker roles={roles.data} selected={selectedRoles} onChange={setSelectedRoles} disabled={saveRoles.isPending} />}{saveRoles.error && <div className="auth-problem" role="alert"><strong>Не удалось сохранить роли</strong>{saveRoles.error.message}</div>}</div>
      <div className="profile-role-dialog-actions"><Button variant="secondary" disabled={saveRoles.isPending} onClick={() => setRoleDialogOpen(false)}>Отмена</Button><Button disabled={!selectedRoles.length || saveRoles.isPending || roles.isError || roles.isLoading} onClick={() => saveRoles.mutate()}>{saveRoles.isPending ? "Сохраняем…" : "Сохранить роли"}</Button></div>
    </dialog>
  </div>;
}
