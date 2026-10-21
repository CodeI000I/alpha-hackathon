import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import EventCard from "../components/EventCard";
import { DemoChat } from "../components/DemoChat";
import { TrendChart } from "../components/Charts";
import { Badge, Button, DemoBadge, SearchField, StatePanel } from "../components/ui";
import { filterFeedItems } from "../feedFilters";
import type { FeedFilter } from "../feedFilters";
import { localKey, useStoredState } from "../localState";

const filters: Array<{ value: FeedFilter; label: string }> = [
  { value: "all", label: "Все события" },
  { value: "risk", label: "Риски" },
  { value: "opportunity", label: "Возможности" },
  { value: "event", label: "События" },
  { value: "saved", label: "Сохранённые · Демо" },
];

export default function FeedPage({ userId }: { userId: number }) {
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => api.user(userId) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const [searchParams, setSearchParams] = useSearchParams();
  const [role, setRole] = useState("");
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [query, setQuery] = useState("");
  const [saved, setSaved] = useStoredState<number[]>(localKey(userId, "saved"), []);
  const feed = useQuery({
    queryKey: ["feed", userId, role],
    queryFn: ({ signal }) => api.feed(userId, role || undefined, 200, signal),
  });
  const activeFilter: FeedFilter = searchParams.get("saved") === "1" ? "saved" : filter;

  const roleName = (code: string) => roles.data?.find((item) => item.code === code)?.name ?? code;
  const visibleItems = useMemo(
    () => filterFeedItems(feed.data ?? [], { filter: activeFilter, query, savedIds: saved }),
    [activeFilter, feed.data, query, saved],
  );

  const selectFilter = (next: FeedFilter) => {
    setFilter(next === "saved" ? "all" : next);
    const params = new URLSearchParams(searchParams);
    if (next === "saved") params.set("saved", "1");
    else params.delete("saved");
    setSearchParams(params, { replace: true });
  };

  const toggleSaved = (id: number) => {
    setSaved((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  const now = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    weekday: "long",
  }).format(new Date());

  return (
    <div className="dashboard-page">
      <header className="page-heading page-heading--dashboard">
        <div>
          <span className="eyebrow">{now}</span>
          <h1>Обзор событий</h1>
          <p>Новости и объяснения, отобранные с учётом вашей компании и ролей.</p>
        </div>
        <div className="heading-metrics" aria-label="Сводка ленты">
          <div><strong>{feed.data?.length ?? "—"}</strong><span>в ленте</span></div>
          <div><strong>{saved.length}</strong><span>сохранено</span></div>
        </div>
      </header>

      <div className="role-tabs" role="tablist" aria-label="Фильтр по роли">
        <button className={!role ? "is-active" : ""} type="button" onClick={() => setRole("")}>
          Все роли
        </button>
        {user.data?.roles.map((code) => (
          <button key={code} className={role === code ? "is-active" : ""} type="button" onClick={() => setRole(code)}>
            {roleName(code)}
          </button>
        ))}
      </div>

      <div className="dashboard-grid">
        <section className="feed-column" aria-label="Лента событий">
          <div className="feed-toolbar">
            <SearchField
              id="feed-search"
              label="Поиск по событиям"
              hideLabel
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Поиск по событиям и темам"
            />
            <div className="filter-pills" aria-label="Фильтр событий">
              {filters.map((item) => (
                <button
                  className={activeFilter === item.value ? "is-active" : ""}
                  type="button"
                  key={item.value}
                  onClick={() => selectFilter(item.value)}
                >
                  {item.label}
                  {item.value === "saved" && saved.length > 0 && <span>{saved.length}</span>}
                </button>
              ))}
            </div>
          </div>

          {feed.isLoading && <div className="feed-skeleton" aria-label="Загрузка ленты"><i /><i /><i /></div>}
          {feed.isError && (
            <StatePanel
              tone="error"
              title="Лента не загрузилась"
              text={feed.error.message}
              action={<Button onClick={() => feed.refetch()}>Повторить</Button>}
            />
          )}
          {!feed.isLoading && !feed.isError && visibleItems.length === 0 && (
            <StatePanel
              title={feed.data?.length ? "Ничего не найдено" : "В ленте пока нет событий"}
              text={
                feed.data?.length
                  ? "Измените поисковый запрос или сбросьте фильтры."
                  : "События появятся после того, как backend соберёт новости и сформирует рекомендации."
              }
              action={
                feed.data?.length ? (
                  <Button variant="secondary" onClick={() => { selectFilter("all"); setQuery(""); }}>
                    Сбросить фильтры
                  </Button>
                ) : undefined
              }
            />
          )}

          <div className="event-list">
            {visibleItems.map((item) => (
              <EventCard
                item={item}
                key={item.id}
                roleName={roleName(item.role)}
                saved={saved.includes(item.id)}
                onToggleSave={() => toggleSaved(item.id)}
              />
            ))}
          </div>
        </section>

        <aside className="dashboard-rail">
          <section className="panel activity-panel">
            <div className="panel-heading"><div><span className="eyebrow">Динамика</span><h2>События за неделю</h2></div><DemoBadge /></div>
            <TrendChart compact />
            <div className="legend-row"><Badge tone="risk">Риски</Badge><Badge tone="opportunity">Возможности</Badge></div>
          </section>
          <DemoChat itemTitle="события в вашей ленте" roleName={role ? roleName(role) : "все ваши роли"} compact />
        </aside>
      </div>
    </div>
  );
}
