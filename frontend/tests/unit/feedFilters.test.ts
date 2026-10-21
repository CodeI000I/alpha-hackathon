import { describe, expect, it } from "vitest";
import { DEMO_FEED } from "../../src/api/mocks";
import { filterFeedItems } from "../../src/feedFilters";

describe("feed filters", () => {
  it("filters all three event kinds", () => {
    expect(filterFeedItems(DEMO_FEED, { filter: "risk", query: "", savedIds: [] }).map((item) => item.id)).toEqual([101, 105]);
    expect(filterFeedItems(DEMO_FEED, { filter: "opportunity", query: "", savedIds: [] }).map((item) => item.id)).toEqual([102, 104]);
    expect(filterFeedItems(DEMO_FEED, { filter: "event", query: "", savedIds: [] }).map((item) => item.id)).toEqual([103, 106]);
  });

  it("shows only explicitly saved items", () => {
    expect(filterFeedItems(DEMO_FEED, { filter: "saved", query: "", savedIds: [102, 105] }).map((item) => item.id)).toEqual([102, 105]);
  });

  it("searches titles, summaries, insights, sources, and profile elements", () => {
    expect(filterFeedItems(DEMO_FEED, { filter: "all", query: "плавающей ставкой", savedIds: [] }).map((item) => item.id)).toEqual([101]);
    expect(filterFeedItems(DEMO_FEED, { filter: "all", query: "S042", savedIds: [] }).map((item) => item.id)).toEqual([104]);
    expect(filterFeedItems(DEMO_FEED, { filter: "all", query: "Б12", savedIds: [] }).map((item) => item.id)).toEqual([106]);
  });
});
