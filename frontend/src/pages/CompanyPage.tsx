import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, isDemoMode } from "../api/client";
import type { ProfileElement } from "../api/types";
import RolePicker from "../components/RolePicker";
import { StatePanel } from "../components/ui";
import { Button, TextField } from "../signal/components/ui";
import { Chart, Directions, Keywords } from "../signal/Insights";
import { localKey, useStoredState } from "../localState";
import "../auth/integration.css";
import "../auth/profile.css";

const tabs = ["roles", "company", "keywords", "documents"] as const;
type Tab = (typeof tabs)[number];
const tabLabels: Record<Tab, string> = { roles: "Моя роль", company: "Компания", keywords: "Ключевые слова", documents: "Документы" };
interface UploadTask { id: number; file: File; state: "sending" | "success" | "error"; message?: string; retryable?: boolean }
export function validateDocument(file: Pick<File, "name" | "size">): string | undefined {
  if (!/\.(pdf|txt|docx|xlsx)$/i.test(file.name)) return "Допустимы только PDF, TXT, DOCX и XLSX.";
  if (file.size > 10 * 1024 * 1024) return "Файл больше 10 МБ. Выберите файл меньшего размера.";
  if (file.size === 0) return "Файл пуст. Выберите документ с содержимым.";
  return undefined;
}
function profileValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (["string", "number", "boolean"].includes(typeof value)) return String(value);
  try { return JSON.stringify(value); } catch { return "Не удалось отобразить значение"; }
}
function groupElements(elements: ProfileElement[]) {
  return elements.reduce<Record<string, ProfileElement[]>>((groups, element) => { (groups[element.block || "Без группы"] ??= []).push(element); return groups; }, {});
}
function formatDate(value: string): string {
  const date = new Date(value); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(date) : "Дата не передана";
}

export default function CompanyPage({ userId }: { userId: number }) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tab: Tab = tabs.includes(rawTab as Tab) ? rawTab as Tab : rawTab === "analytics" ? "company" : "roles";
  const user = useQuery({ queryKey: ["user", userId], queryFn: ({ signal }) => api.user(userId, signal) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const companyId = user.data?.companyId ?? null;
  const company = useQuery({ queryKey: ["company", companyId], queryFn: ({ signal }) => api.company(companyId!, signal), enabled: companyId !== null });
  const elements = useQuery({ queryKey: ["profile-elements"], queryFn: api.profileElements, enabled: tab === "company" });
  const files = useQuery({ queryKey: ["files", companyId], queryFn: ({ signal }) => api.files(companyId!, signal), enabled: companyId !== null });
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [keywords, setKeywords] = useStoredState<string[]>(localKey(userId, "keywords", companyId), []);
  const [directions, setDirections] = useStoredState<number[]>(localKey(userId, "directions", companyId), [50, 50, 50, 50, 50]);
  const [notice, setNotice] = useState("");
  const [uploads, setUploads] = useState<UploadTask[]>([]);
  const uploadSequence = useRef(0);
  useEffect(() => {
    if (!user.data) return;
    const available = roles.data ? new Set(roles.data.map((role) => role.code)) : null;
    setSelectedRoles(available ? user.data.roles.filter((code) => available.has(code)) : user.data.roles);
  }, [user.data, roles.data]);
  useEffect(() => { setUploads([]); }, [companyId]);
  const grouped = useMemo(() => groupElements(elements.data ?? []), [elements.data]);
  const knownElements = useMemo(() => new Set((elements.data ?? []).map((element) => element.code)), [elements.data]);
  const saveRoles = useMutation({
    mutationFn: () => api.setRoles(userId, selectedRoles),
    onSuccess: (updated) => {
      queryClient.setQueryData(["user", userId], updated);
      setSelectedRoles(updated.roles);
      void queryClient.invalidateQueries({ queryKey: ["feed", userId] });
      setNotice("Роли сохранены. Лента обновляется с учётом ответа сервера.");
    },
  });
  const uploadFile = async (task: UploadTask) => {
    if (companyId === null) return;
    setUploads((current) => current.map((item) => item.id === task.id ? { ...item, state: "sending", message: undefined } : item));
    try {
      await api.uploadFile(companyId, task.file);
      setUploads((current) => current.map((item) => item.id === task.id ? { ...item, state: "success", message: "Загружен. Статус анализа сервер не передаёт." } : item));
      await queryClient.invalidateQueries({ queryKey: ["files", companyId] });
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
  const companyState = companyId === null ? <StatePanel title="Компания не привязана" text="Сервер вернул пользователя без компании. Документы и профиль компании пока недоступны." /> : company.isLoading ? <StatePanel title="Загружаем компанию…" /> : company.isError && !company.data ? <StatePanel tone="error" title="Компания не загрузилась" text={company.error.message} action={<Button onClick={() => company.refetch()}>Повторить</Button>} /> : null;

  return <div className="signal-profile">
    <div className="w-heading"><div><h1>Личный кабинет</h1><p className="w-muted">{user.data.fullName}{company.data ? ` · ${company.data.name}` : ""}</p></div></div>
    <nav className="w-profile-tabs" aria-label="Разделы личного кабинета">{tabs.map((item) => <button className={tab === item ? "active" : ""} aria-current={tab === item ? "page" : undefined} onClick={() => { setSearchParams({ tab: item }); setNotice(""); }} key={item}>{tabLabels[item]}{item === "documents" && <span>{files.data?.length ?? 0}</span>}</button>)}</nav>
    {notice && <div className="signal-profile-notice" role="status">{notice}<button type="button" aria-label="Закрыть сообщение" onClick={() => setNotice("")}>×</button></div>}
    <div className="w-profile-grid"><section className="w-panel w-profile-panel">
      {tab === "roles" && <div className="w-form">
        <h2>Имя и роли</h2><TextField id="person-name" label="Как вас зовут" value={user.data.fullName} readOnly hint="Имя из профиля. Серверное редактирование пока не подключено." /><TextField id="person-email" label="Электронная почта" value={user.data.email} readOnly />
        <div><h3>Роли в компании</h3><p className="w-muted">Можно выбрать несколько ролей. Активный ракурс ленты выбирается отдельно в обзоре.</p></div>
        {roles.isLoading && <p role="status">Загружаем роли…</p>}
        {roles.isError && <StatePanel tone="error" title="Роли не загрузились" text={roles.error.message} action={<Button onClick={() => roles.refetch()}>Повторить</Button>} />}
        {roles.data && <RolePicker roles={roles.data} selected={selectedRoles} onChange={setSelectedRoles} disabled={saveRoles.isPending} />}
        {!roles.isLoading && !roles.isError && !roles.data?.length && <p className="w-muted">Каталог ролей пуст.</p>}
        {saveRoles.error && <div className="auth-problem" role="alert"><strong>Не удалось сохранить роли</strong>{saveRoles.error.message}</div>}
        <Button disabled={!selectedRoles.length || saveRoles.isPending || roles.isError || roles.isLoading} onClick={() => saveRoles.mutate()}>{saveRoles.isPending ? "Сохраняем…" : "Сохранить роли"}</Button>
        <section className="profile-demo-section"><span className="w-demo">Демо · локально</span><Directions values={directions} onChange={setDirections} editable /><p className="w-small">Направления внимания — ваша локальная настройка, а не расчёт риска. Значения не отправляются на сервер.</p></section>
      </div>}
      {tab === "company" && (companyState || (company.data && <>
        <h2>{company.data.name}</h2><p className="w-muted">{isDemoMode ? "Демонстрационный профиль компании" : "Данные профиля из API"}. Доступен только просмотр.</p>
        <dl className="w-company-details"><div><dt>ИНН</dt><dd>{company.data.inn || "Не передан"}</dd></div><div><dt>ОГРН</dt><dd>{company.data.ogrn || "Не передан"}</dd></div><div><dt>Обновлено</dt><dd>{formatDate(company.data.updatedAt)}</dd></div></dl>
        <h3>Элементы профиля</h3>
        {elements.isLoading && <p role="status">Загружаем описание элементов…</p>}
        {elements.isError && <StatePanel tone="error" title="Справочник не загрузился" text={elements.error.message} action={<Button onClick={() => elements.refetch()}>Повторить</Button>} />}
        <div className="signal-profile-elements">{Object.entries(grouped).map(([block, blockElements], index) => <details key={block} open={index === 0}><summary>{block}</summary><dl>{blockElements.map((element) => <div key={element.code}><dt>{element.name}<small>{element.code}</small></dt><dd>{profileValue(company.data.profile[element.code]) || "Данные не переданы"}</dd></div>)}</dl></details>)}
          {Object.entries(company.data.profile).filter(([key]) => !knownElements.has(key)).map(([key, value]) => <dl key={key}><div><dt>{key}</dt><dd>{profileValue(value) || "Данные не переданы"}</dd></div></dl>)}
        </div>
        {!Object.keys(company.data.profile).length && <p className="w-muted">Профиль компании пока не заполнен.</p>}
        <p className="w-small">Изменение полей появится после согласования формата каждого значения с backend. Произвольный JSON не записывается.</p>
        <section className="company-analytics"><span className="w-demo">Демо · локально</span><h3>Аналитика компании</h3><p className="w-muted">Иллюстративные показатели. Это не финансовые данные вашей компании.</p><Chart /><div className="analytics-kpis"><div><span>Операционные расходы · пример</span><strong>31,5 млн ₽</strong><small>Синтетические данные</small></div><div><span>Денежный поток · пример</span><strong>+8,2 млн ₽</strong><small>Синтетические данные</small></div></div><Chart kind="supply" /></section>
      </>))}
      {tab === "keywords" && <><span className="w-demo">Демо · локально</span><Keywords words={keywords} onChange={setKeywords} /><p className="w-small">Слова сохраняются отдельно для текущего режима, пользователя и компании. Используются только для подсветки совпадений, не влияют на серверную выдачу.</p></>}
      {tab === "documents" && (companyState || <>
        <h2>Документы компании</h2><p className="w-muted">{isDemoMode ? "Демонстрационный список сохраняется в браузере. Содержимое файлов на сервер не отправляется." : "Документы отправляются в хранилище компании на backend."}</p>
        {isDemoMode && <span className="w-demo">Демо</span>}
        <label className="w-upload"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 13h8m-8 4h6" /></svg><strong>Выбрать документы</strong><span>PDF, TXT, DOCX, XLSX · до 10 МБ на файл</span><input type="file" multiple accept=".pdf,.txt,.docx,.xlsx" aria-label="Выбрать документы" onChange={(event) => { enqueue(Array.from(event.target.files ?? [])); event.target.value = ""; }} /></label>
        <p className="w-small">«Загружен» не означает «Проанализирован». Статус обработки, серверное удаление и скачивание пока не поддерживаются.</p>
        {!!uploads.length && <section className="signal-upload-results" aria-label="Результаты загрузки" aria-live="polite">{uploads.map((task) => <article key={task.id} className={`signal-upload-result is-${task.state}`}><strong>{task.file.name}</strong><p>{task.state === "sending" ? "Отправка…" : task.message}</p>{task.state === "error" && task.retryable && <Button variant="secondary" onClick={() => void uploadFile(task)}>Повторить загрузку</Button>}</article>)}</section>}
        <h3>Загруженные документы</h3>{files.isLoading && <p role="status">Загружаем список…</p>}
        {files.isError && <StatePanel tone="error" title="Список документов не загрузился" text={files.error.message} action={<Button onClick={() => files.refetch()}>Повторить</Button>} />}
        {files.data?.map((file) => <article className="w-document signal-document" key={file.id}><div><strong>{file.filename}</strong><small>{Math.max(1, Math.round(file.sizeBytes / 1024))} КБ · {formatDate(file.createdAt)}</small><span>Загружен · анализ не подтверждён</span></div></article>)}
        {!files.isLoading && !files.isError && files.data?.length === 0 && <StatePanel title="Документов пока нет" text="Добавьте материалы компании. Они не станут основанием вывода до подтверждения обработки сервером." />}
        <section className="signal-bank-materials"><h3>Материалы банка</h3><p className="w-muted">Сведения о банковских материалах этим API не передаются. Они не смешиваются с документами компании.</p></section>
      </>)}
    </section><aside className="w-panel w-profile-help"><h3>{tab === "company" ? "Профиль и динамика бизнеса" : tab === "keywords" ? "Темы для наблюдения" : "Настройки компании"}</h3><p>{tab === "documents" ? "Документы компании и материалы банка имеют разное происхождение. Загрузка файла сама по себе не подтверждает его использование в разборе." : tab === "roles" ? "Роли определяют доступные ракурсы событий. Направления внимания ниже — отдельная локальная демонастройка." : tab === "company" ? "Профиль отображается из API без изменений. Все иллюстративные графики отмечены как демо." : "Добавьте важные темы через запятую. Совпадения будут подсвечиваться в карточках событий."}</p><Link className="w-text-btn action-back" to="/dashboard"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M19 12H5m6-6-6 6 6 6" /></svg>Вернуться к событиям</Link><details className="data-note"><summary>О данных и сохранении</summary><p>{isDemoMode ? "Серверные данные заменены детерминированным демонабором. Запросов к Go нет." : "Компания, роли и документы используют Go API. Ошибки сервера не заменяются демоданными."}</p><p>Ключевые слова и направления внимания сохраняются локально. Серверной авторизации пока нет.</p></details></aside></div>
  </div>;
}
