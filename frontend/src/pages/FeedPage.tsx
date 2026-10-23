import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FeedKind } from "../api/types";

const KIND_LABEL: Record<FeedKind, string> = { event: "Событие", risk: "Риск", opportunity: "Возможность" };

function safeNewsUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export default function FeedPage({ userId }: { userId: number }) {
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => api.user(userId) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const [role, setRole] = useState<string>("");
  const feed = useQuery({ queryKey: ["feed", userId, role], queryFn: () => api.feed(userId, role) });

  const roleName = (code: string) => roles.data?.find((r) => r.code === code)?.name ?? code;
  const errorText = (error: unknown) => error instanceof Error ? error.message : "Не удалось загрузить данные.";

  return (
    <section>
      <div className="tabs">
        <button className={role === "" ? "tab tab--on" : "tab"} onClick={() => setRole("")}>
          Все роли
        </button>
        {user.data?.roles.map((code) => (
          <button key={code} className={role === code ? "tab tab--on" : "tab"} onClick={() => setRole(code)}>
            {roleName(code)}
          </button>
        ))}
      </div>
      {user.isError && <p className="error" role="alert">Не удалось загрузить пользователя: {errorText(user.error)} <button onClick={() => user.refetch()}>Повторить</button></p>}
      {roles.isError && <p className="error" role="alert">Не удалось загрузить роли: {errorText(roles.error)} <button onClick={() => roles.refetch()}>Повторить</button></p>}
      {feed.isLoading && <p role="status">Загрузка…</p>}
      {feed.isError && <p className="error" role="alert">Не удалось загрузить ленту: {errorText(feed.error)} <button onClick={() => feed.refetch()}>Повторить</button></p>}
      {feed.data?.length === 0 && <p className="muted">Пока нет инсайтов. Они появятся после сбора новостей.</p>}
      <ul className="feed">
        {feed.data?.map((item) => {
          const newsUrl = safeNewsUrl(item.news.url);
          return (
          <li key={item.id} className={`insight insight--${item.kind}`}>
            <div className="insight__meta">
              <span className="badge">{KIND_LABEL[item.kind]}</span>
              <span>{roleName(item.role)}</span>
              <span>{new Date(item.news.publishedAt).toLocaleString("ru-RU")}</span>
            </div>
            {newsUrl ? (
              <a href={newsUrl} target="_blank" rel="noreferrer" className="insight__title">
                {item.news.title}
              </a>
            ) : <span className="insight__title">{item.news.title}</span>}
            {item.insight && <p>{item.insight}</p>}
          </li>
          );
        })}
      </ul>
    </section>
  );
}
