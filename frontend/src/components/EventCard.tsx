import { Link } from "react-router-dom";
import type { FeedItem, FeedKind } from "../api/types";
import { Icon } from "./Icon";
import { Badge, DemoBadge } from "./ui";

export interface EventCardProps {
  item: FeedItem;
  roleName: string;
  saved: boolean;
  onToggleSave: () => void;
}

const KIND_LABEL: Record<FeedKind, string> = {
  event: "Событие",
  risk: "Риск",
  opportunity: "Возможность",
};

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
    .format(date)
    .replace(" г.", "");
}

function scoreLabel(score: number) {
  const normalized = score <= 1 ? score * 100 : score;
  return `${Math.round(Math.max(0, Math.min(normalized, 100)))}%`;
}

export default function EventCard({ item, roleName, saved, onToggleSave }: EventCardProps) {
  const summary = item.news.summary?.trim();
  const insight = item.insight?.trim();
  return (
    <article className={`event-card event-card--${item.kind}`}>
      <div className="event-card__meta">
        <Badge tone={item.kind}>{KIND_LABEL[item.kind]}</Badge>
        <time dateTime={item.news.publishedAt}>{formatDate(item.news.publishedAt)}</time>
        {item.news.sourceId && <span className="event-card__source">{item.news.sourceId}</span>}
        <DemoBadge className="event-card__save-demo">Закладка · Демо</DemoBadge>
        <button
          type="button"
          className={`ui-icon-button event-card__save${saved ? " is-active" : ""}`}
          aria-label={saved ? `Убрать из сохранённых: ${item.news.title}` : `Сохранить: ${item.news.title}`}
          aria-pressed={saved}
          onClick={onToggleSave}
        >
          <Icon name="bookmark" size={19} />
        </button>
      </div>
      <h2 className="event-card__title">
        <Link to={`/feed/${item.id}`}>{item.news.title}</Link>
      </h2>
      {summary && <p className="event-card__summary">{summary}</p>}
      {insight && (
        <div className="event-card__insight">
          <strong>
            <Icon name="spark" size={16} />
            Почему это важно
          </strong>
          <p>{insight}</p>
        </div>
      )}
      <div className="event-card__tags">
        <Badge>{roleName}</Badge>
        <Badge>Релевантность {scoreLabel(item.score)}</Badge>
        {item.elements.slice(0, 4).map((element) => (
          <Badge key={element}>{element}</Badge>
        ))}
        {item.elements.length > 4 && <Badge>+{item.elements.length - 4}</Badge>}
      </div>
      <div className="event-card__footer">
        <span>Персональный разбор по вашей роли</span>
        <Link to={`/feed/${item.id}`} aria-label={`Открыть разбор: ${item.news.title}`}>
          Открыть разбор <Icon name="arrow-right" size={17} />
        </Link>
      </div>
    </article>
  );
}
