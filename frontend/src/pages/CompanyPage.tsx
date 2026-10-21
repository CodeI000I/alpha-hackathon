import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, isDemoMode } from "../api/client";
import type { ProfileElement } from "../api/types";
import RolePicker from "../components/RolePicker";
import { RadarChart, TrendChart } from "../components/Charts";
import { Badge, Button, DemoBadge, StatePanel, TextField } from "../components/ui";
import { localKey, useStoredState } from "../localState";

const tabs = ["summary", "roles", "company", "keywords", "analytics", "documents"] as const;
type Tab = (typeof tabs)[number];

const tabLabels: Record<Tab, string> = {
  summary: "Сводка",
  roles: "Мои роли",
  company: "Компания",
  keywords: "Ключевые слова",
  analytics: "Аналитика",
  documents: "Документы",
};

function profileValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (["string", "number", "boolean"].includes(typeof value)) return String(value);
  if (typeof value === "object" && value && "value" in value && typeof value.value === "string") return value.value;
  try { return JSON.stringify(value); } catch { return "Данные заполнены"; }
}

function groupElements(elements: ProfileElement[]) {
  return elements.reduce<Record<string, ProfileElement[]>>((groups, element) => {
    (groups[element.block] ??= []).push(element);
    return groups;
  }, {});
}

export default function CompanyPage({ userId }: { userId: number }) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tab: Tab = tabs.includes(rawTab as Tab) ? (rawTab as Tab) : "summary";
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => api.user(userId) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const companyId = user.data?.companyId ?? null;
  const company = useQuery({ queryKey: ["company", companyId], queryFn: () => api.company(companyId!), enabled: companyId !== null });
  const elements = useQuery({ queryKey: ["profile-elements"], queryFn: api.profileElements });
  const files = useQuery({ queryKey: ["files", companyId], queryFn: () => api.files(companyId!), enabled: companyId !== null });
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keywords, setKeywords] = useStoredState<string[]>(localKey(userId, "keywords"), ["Поставки", "Комплектующие"]);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (user.data) setSelectedRoles(user.data.roles);
  }, [user.data]);

  const grouped = useMemo(() => groupElements(elements.data ?? []), [elements.data]);
  const filledCount = company.data ? Object.values(company.data.profile).filter((value) => profileValue(value)).length : 0;

  const saveRoles = useMutation({
    mutationFn: () => api.setRoles(userId, selectedRoles),
    onSuccess: (updated) => {
      queryClient.setQueryData(["user", userId], updated);
      queryClient.invalidateQueries({ queryKey: ["feed", userId] });
      setNotice("Роли сохранены. Лента обновится с учётом выбранных ракурсов.");
    },
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      if (file.size > 50 * 1024 * 1024) throw new Error("Файл больше 50 МБ. Выберите файл меньшего размера.");
      return api.uploadFile(companyId!, file);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files", companyId] });
      setNotice("Документ загружен.");
    },
  });

  if (user.isLoading || company.isLoading) return <div className="profile-skeleton" aria-label="Загрузка личного кабинета"><i /><i /><i /></div>;
  if (user.isError) return <StatePanel tone="error" title="Профиль не загрузился" text={user.error.message} action={<Button onClick={() => user.refetch()}>Повторить</Button>} />;
  if (!companyId) return <StatePanel title="Компания не привязана" text="Завершите регистрацию, чтобы открыть личный кабинет." />;
  if (company.isError) return <StatePanel tone="error" title="Компания не загрузилась" text={company.error.message} action={<Button onClick={() => company.refetch()}>Повторить</Button>} />;
  if (!company.data || !user.data) return null;

  const addKeywords = () => {
    const next = keywordDraft.split(",").map((word) => word.trim()).filter(Boolean);
    if (!next.length) return;
    setKeywords((current) => [...new Set([...current, ...next])].slice(0, 30));
    setKeywordDraft("");
    setNotice("Ключевые слова сохранены локально в этом браузере.");
  };

  return (
    <div className="profile-page">
      <header className="page-heading">
        <div><span className="eyebrow">Настройки и данные</span><h1>Личный кабинет</h1><p>{user.data.fullName} · {company.data.name}</p></div>
        <span className="company-avatar" aria-label={`Компания ${company.data.name}`}>{company.data.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase()}</span>
      </header>

      <nav className="profile-tabs" aria-label="Разделы личного кабинета">
        {tabs.map((item) => (
          <button key={item} className={tab === item ? "is-active" : ""} onClick={() => { setSearchParams({ tab: item }); setNotice(""); }} type="button">
            {tabLabels[item]}{item === "documents" && <span>{files.data?.length ?? 0}</span>}
          </button>
        ))}
      </nav>

      {notice && <div className="toast-inline" role="status">{notice}<button type="button" aria-label="Закрыть сообщение" onClick={() => setNotice("")}>×</button></div>}

      <div className="profile-grid">
        <section className="panel profile-content">
          {tab === "summary" && (
            <div className="profile-section">
              <div className="section-heading"><div><span className="eyebrow">Ваш профиль</span><h2>{user.data.fullName}</h2><p>{company.data.name}</p></div><Badge tone="neutral">ИНН {company.data.inn}</Badge></div>
              <RadarChart />
              <div className="stats-grid">
                <div><strong>{user.data.roles.length}</strong><span>управленческих ролей</span></div>
                <div><strong>{filledCount}/{elements.data?.length ?? "—"}</strong><span>элементов профиля</span></div>
                <div><strong>{keywords.length}</strong><span>ключевых слов</span></div>
                <div><strong>{files.data?.length ?? 0}</strong><span>документов</span></div>
              </div>
              <div className="summary-actions"><Button onClick={() => setSearchParams({ tab: "roles" })}>Настроить роли</Button><Button variant="secondary" onClick={() => setSearchParams({ tab: "company" })}>Посмотреть компанию</Button></div>
            </div>
          )}

          {tab === "roles" && (
            <div className="profile-section">
              <div className="section-heading"><div><span className="eyebrow">Персонализация</span><h2>Мои роли</h2><p>Одна новость может получить разные объяснения для каждой выбранной роли.</p></div></div>
              {roles.isLoading && <div className="skeleton skeleton--roles" />}
              {roles.isError && <StatePanel tone="error" title="Роли не загрузились" text={roles.error.message} action={<Button onClick={() => roles.refetch()}>Повторить</Button>} />}
              {roles.data && <RolePicker roles={roles.data} selected={selectedRoles} onChange={setSelectedRoles} />}
              {saveRoles.error && <div className="inline-error" role="alert"><strong>Не удалось сохранить</strong><span>{saveRoles.error.message}</span></div>}
              <Button disabled={!selectedRoles.length || saveRoles.isPending} onClick={() => saveRoles.mutate()}>{saveRoles.isPending ? "Сохраняем…" : "Сохранить роли"}</Button>
            </div>
          )}

          {tab === "company" && (
            <div className="profile-section">
              <div className="section-heading"><div><span className="eyebrow">Реальные данные API</span><h2>{company.data.name}</h2><p>Название и ИНН доступны только для просмотра: backend пока не поддерживает их изменение.</p></div></div>
              <dl className="company-facts"><div><dt>ИНН</dt><dd>{company.data.inn}</dd></div><div><dt>ОГРН</dt><dd>{company.data.ogrn || "Не указан"}</dd></div><div><dt>Обновлено</dt><dd>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(company.data.updatedAt))}</dd></div></dl>
              <div className="profile-elements-heading"><h3>Элементы профиля</h3><Badge tone="neutral">{filledCount} заполнено</Badge></div>
              {elements.isError && <StatePanel tone="error" title="Справочник не загрузился" text={elements.error.message} />}
              <div className="profile-element-groups">
                {Object.entries(grouped).map(([block, blockElements]) => (
                  <details key={block} open={Object.keys(grouped)[0] === block}>
                    <summary><span>{block}</span><small>{blockElements.filter((element) => profileValue(company.data.profile[element.code])).length}/{blockElements.length}</small></summary>
                    <div>{blockElements.map((element) => { const value = profileValue(company.data.profile[element.code]); return <article key={element.code} className={value ? "is-filled" : ""}><span>{element.code}</span><div><strong>{element.name}</strong><p>{value || element.description}</p></div><Badge tone={value ? "opportunity" : "neutral"}>{value ? "Заполнено" : "Нет данных"}</Badge></article>; })}</div>
                  </details>
                ))}
              </div>
              <p className="demo-disclaimer">Редактирование значений появится после согласования их JSON-формата с backend.</p>
            </div>
          )}

          {tab === "keywords" && (
            <div className="profile-section">
              <div className="section-heading"><div><span className="eyebrow">Темы для наблюдения</span><h2>Ключевые слова</h2><p>Совпадения подсвечиваются локально и не отправляются на сервер.</p></div><DemoBadge /></div>
              <div className="keyword-form"><TextField id="keyword" label="Добавить слова через запятую" value={keywordDraft} onChange={(event) => setKeywordDraft(event.target.value)} placeholder="Например: логистика, ставка, металл" /><Button onClick={addKeywords} disabled={!keywordDraft.trim()}>Добавить</Button></div>
              <div className="keyword-list">{keywords.map((word) => <span key={word}>{word}<button type="button" aria-label={`Удалить ${word}`} onClick={() => setKeywords((current) => current.filter((item) => item !== word))}>×</button></span>)}</div>
              {!keywords.length && <StatePanel title="Список пуст" text="Добавьте темы, которые важны для вашей компании." />}
            </div>
          )}

          {tab === "analytics" && (
            <div className="profile-section">
              <div className="section-heading"><div><span className="eyebrow">Динамика бизнеса</span><h2>Аналитика</h2><p>Иллюстрация будущего раздела; показатели не получены из банковских систем.</p></div><DemoBadge /></div>
              <div className="analytics-hero"><div><span>Выручка компании</span><strong>45 млн ₽</strong><small>+7,1% за месяц · пример</small></div><TrendChart /></div>
              <div className="stats-grid"><div><strong>31,5 млн ₽</strong><span>операционные расходы · пример</span></div><div><strong>+8,2 млн ₽</strong><span>денежный поток · пример</span></div></div>
            </div>
          )}

          {tab === "documents" && (
            <div className="profile-section">
              <div className="section-heading"><div><span className="eyebrow">Контекст компании</span><h2>Документы</h2><p>{isDemoMode ? "Демо-файлы сохраняются только локально в этом браузере. Максимальный размер — 50 МБ." : "Файлы отправляются в настоящее хранилище backend. Максимальный размер — 50 МБ."}</p></div>{isDemoMode && <DemoBadge />}</div>
              <label className={upload.isPending ? "upload-zone is-pending" : "upload-zone"}><span aria-hidden="true">＋</span><strong>{upload.isPending ? "Загружаем…" : "Выбрать документ"}</strong><small>До 50 МБ на файл</small><input type="file" disabled={upload.isPending} onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate(file); event.target.value = ""; }} /></label>
              {upload.error && <div className="inline-error" role="alert"><strong>Загрузка не выполнена</strong><span>{upload.error.message}</span></div>}
              {files.isError && <StatePanel tone="error" title="Список документов не загрузился" text={files.error.message} action={<Button onClick={() => files.refetch()}>Повторить</Button>} />}
              <div className="document-list">{files.data?.map((file) => <article key={file.id}><span className="document-icon" aria-hidden="true">▤</span><div><strong>{file.filename}</strong><small>{file.contentType || "Файл"} · {Math.max(1, Math.round(file.sizeBytes / 1024))} КБ</small></div><time>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(file.createdAt))}</time></article>)}</div>
              {!files.isLoading && !files.isError && files.data?.length === 0 && <StatePanel title="Документов пока нет" text="Добавьте материалы, чтобы команда могла дополнить профиль компании." />}
            </div>
          )}
        </section>

        <aside className="panel profile-help">
          <h3>{tabLabels[tab]}</h3>
          <p>{tab === "documents" ? (isDemoMode ? "Демо-файлы остаются в этом браузере; удалить или скачать их пока нельзя." : "Загруженные файлы хранятся на стороне backend; удалить или скачать их пока нельзя.") : tab === "company" ? "Профиль состоит из элементов, связанных с выбранными ролями и источниками новостей." : "Настройки помогают сделать ленту более точной и полезной для вашей управленческой задачи."}</p>
          {(tab === "keywords" || tab === "analytics") && <div className="demo-note"><DemoBadge /><span>Данные этого раздела остаются в браузере.</span></div>}
        </aside>
      </div>
    </div>
  );
}
