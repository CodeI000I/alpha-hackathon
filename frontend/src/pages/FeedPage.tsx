import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FeedKind } from "../api/types";

const KIND_LABEL: Record<FeedKind, string> = { event: "Событие", risk: "Риск", opportunity: "Возможность" };

export default function FeedPage({ userId }: { userId: number }) {
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => api.user(userId) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const [role, setRole] = useState<string>("");
  const feed = useQuery({ queryKey: ["feed", userId, role], queryFn: () => api.feed(userId, role) });

  const roleName = (code: string) => roles.data?.find((r) => r.code === code)?.name ?? code;

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
      {feed.isLoading && <p>Загрузка…</p>}
      {feed.data?.length === 0 && <p className="muted">Пока нет инсайтов. Они появятся после сбора новостей.</p>}
      <ul className="feed">
        {feed.data?.map((item) => (
          <li key={item.id} className={`insight insight--${item.kind}`}>
            <div className="insight__meta">
              <span className="badge">{KIND_LABEL[item.kind]}</span>
              <span>{roleName(item.role)}</span>
              <span>{new Date(item.news.publishedAt).toLocaleString("ru-RU")}</span>
            </div>
            <a href={item.news.url} target="_blank" rel="noreferrer" className="insight__title">
              {item.news.title}
            </a>
            {item.insight && <p>{item.insight}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
