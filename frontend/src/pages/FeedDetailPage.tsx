import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { DemoChat } from "../components/DemoChat";
import { TrendChart } from "../components/Charts";
import { Badge, Button, DemoBadge, StatePanel } from "../components/ui";
import { localKey, useStoredState } from "../localState";

const KIND_LABEL = { event: "Событие", risk: "Риск", opportunity: "Возможность" } as const;

function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob(["\ufeff", text], { type: "text/plain;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export default function FeedDetailPage({ userId }: { userId: number }) {
  const params = useParams();
  const itemId = Number(params.itemId);
  const [saved, setSaved] = useStoredState<number[]>(localKey(userId, "saved"), []);
  const feed = useQuery({
    queryKey: ["feed", userId, "detail"],
    queryFn: ({ signal }) => api.feed(userId, undefined, 200, signal),
    enabled: Number.isInteger(itemId) && itemId > 0,
  });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const elements = useQuery({ queryKey: ["profile-elements"], queryFn: api.profileElements });
  const item = feed.data?.find((candidate) => candidate.id === itemId);

  const roleName = roles.data?.find((role) => role.code === item?.role)?.name ?? item?.role ?? "Роль";
  const elementNames = useMemo(
    () => item?.elements.map((code) => elements.data?.find((element) => element.code === code)?.name ?? code) ?? [],
    [elements.data, item?.elements],
  );

  if (!Number.isInteger(itemId) || itemId <= 0) {
    return <StatePanel tone="error" title="Некорректная ссылка" text="Проверьте адрес события." action={<Link className="button button--secondary" to="/feed">Вернуться в ленту</Link>} />;
  }
  if (feed.isLoading) return <div className="detail-skeleton" aria-label="Загрузка разбора"><i /><i /><i /></div>;
  if (feed.isError) {
    return <StatePanel tone="error" title="Разбор не загрузился" text={feed.error.message} action={<Button onClick={() => feed.refetch()}>Повторить</Button>} />;
  }
  if (!item) {
    return <StatePanel title="Событие не найдено" text="Оно могло выйти за пределы текущей ленты или быть удалено." action={<Link className="button button--secondary" to="/feed">Вернуться в ленту</Link>} />;
  }

  const isSaved = saved.includes(item.id);
  const published = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(item.news.publishedAt));
  const relevance = Math.round(Math.max(0, Math.min(1, item.score)) * 100);
  const sourceLabel = item.news.sourceId || (() => { try { return item.news.url ? new URL(item.news.url).hostname : ""; } catch { return ""; } })();

  const exportText = [
    "АЛЬФА ИНСАЙТЫ",
    item.news.title,
    `${KIND_LABEL[item.kind]} · ${roleName} · релевантность ${relevance}%`,
    "",
    "Краткое содержание",
    item.news.summary,
    "",
    "Почему это важно",
    item.insight || "Персональное объяснение пока не сформировано.",
    "",
    sourceLabel || item.news.url ? `Источник: ${sourceLabel || item.news.url}${item.news.url ? ` — ${item.news.url}` : ""}` : "Источник не указан",
    "",
    "Блоки прогноза и диалога в интерфейсе являются демонстрационными.",
  ].join("\n");

  return (
    <div className="detail-page">
      <Link className="back-link" to="/feed"><span aria-hidden="true">←</span> К обзору событий</Link>
      <div className="detail-grid">
        <article className="detail-article">
          <div className="detail-meta">
            <Badge tone={item.kind}>{KIND_LABEL[item.kind]}</Badge>
            <Badge tone="neutral">{roleName}</Badge>
            <span>{published}</span>
          </div>
          <h1>{item.news.title}</h1>
          <div className="detail-actions">
            <Button variant="secondary" onClick={() => setSaved((current) => isSaved ? current.filter((id) => id !== item.id) : [...current, item.id])}>
              {isSaved ? "Сохранено · Демо" : "Сохранить · Демо"}
            </Button>
            <Button onClick={() => downloadText(`alfa-insights-${item.id}.txt`, exportText)}>Скачать итог</Button>
          </div>

          <section className="analysis-block">
            <span className="section-number">01</span>
            <h2>Что произошло</h2>
            <p>{item.news.summary || "Источник не предоставил краткое описание события."}</p>
            {item.news.url ? (
              <a className="source-link" href={item.news.url} target="_blank" rel="noreferrer">
                {sourceLabel && <span className="source-monogram" aria-hidden="true">{sourceLabel.slice(0, 2).toUpperCase()}</span>}
                <span><small>Первоисточник</small><strong>{sourceLabel || item.news.url}</strong></span>
                <span aria-hidden="true">↗</span>
              </a>
            ) : sourceLabel ? (
              <div className="source-link source-link--static"><span className="source-monogram" aria-hidden="true">{sourceLabel.slice(0, 2).toUpperCase()}</span><span><small>Идентификатор источника</small><strong>{sourceLabel}</strong></span></div>
            ) : null}
          </section>

          <section className="analysis-block analysis-block--accent">
            <span className="section-number">02</span>
            <h2>Почему это важно для вас</h2>
            <p>{item.insight || "Персональное объяснение пока не сформировано."}</p>
            <div className="relevance-meter">
              <span>Релевантность</span><strong>{relevance}%</strong>
              <i><b style={{ width: `${relevance}%` }} /></i>
            </div>
            {elementNames.length > 0 && <div className="tag-row">{elementNames.map((name) => <Badge tone="neutral" key={name}>{name}</Badge>)}</div>}
          </section>

          <section className="analysis-block">
            <div className="analysis-title-row"><div><span className="section-number">03</span><h2>Возможное влияние</h2></div><DemoBadge /></div>
            <p className="demo-disclaimer">Иллюстративный блок: backend пока не возвращает прогноз последствий.</p>
            <div className="scenario-grid">
              <article><Badge tone="risk">Риск</Badge><p>Проверьте, затрагивает ли событие действующие обязательства, сроки и денежный поток.</p></article>
              <article><Badge tone="opportunity">Возможность</Badge><p>Сравните альтернативы и оцените, можно ли использовать изменение рынка в интересах компании.</p></article>
            </div>
            <TrendChart />
          </section>

          <section className="analysis-block">
            <div className="analysis-title-row"><div><span className="section-number">04</span><h2>Что проверить дальше</h2></div><DemoBadge /></div>
            <ol className="next-steps">
              <li><span>1</span>Сопоставить событие с договорами и планами компании.</li>
              <li><span>2</span>Подтвердить сроки, суммы и ответственных по затронутым процессам.</li>
              <li><span>3</span>Зафиксировать решение и дату следующего обновления.</li>
            </ol>
          </section>
        </article>

        <aside className="detail-rail">
          <DemoChat itemTitle={item.news.title} roleName={roleName} />
        </aside>
      </div>
    </div>
  );
}
