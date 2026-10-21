import type { FeedItem, FeedKind } from "./api/types";

export type FeedFilter = "all" | FeedKind | "saved";

export interface FeedFilterOptions {
  filter: FeedFilter;
  query: string;
  savedIds: readonly number[];
}

export function filterFeedItems(items: readonly FeedItem[], options: FeedFilterOptions): FeedItem[] {
  const normalized = options.query.trim().toLocaleLowerCase("ru-RU");

  return items.filter((item) => {
    if (options.filter === "saved" && !options.savedIds.includes(item.id)) return false;
    if (options.filter !== "all" && options.filter !== "saved" && item.kind !== options.filter) return false;
    if (!normalized) return true;

    return [item.news.title, item.news.summary, item.insight, item.news.sourceId, ...item.elements]
      .join(" ")
      .toLocaleLowerCase("ru-RU")
      .includes(normalized);
  });
}
