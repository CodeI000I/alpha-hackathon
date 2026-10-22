import { describe, expect, it } from "vitest";
import { DEMO_FEED } from "../../src/api/mocks";
import { filterFeedItems } from "../../src/feedFilters";

describe("feed filters", () => {
  it("filters all three event kinds", () => {
    expect(filterFeedItems(DEMO_FEED, { filter: "risk", query: "", savedIds: [] }).map((item) => item.id)).toEqual([101, 201, 204]);
    expect(filterFeedItems(DEMO_FEED, { filter: "opportunity", query: "", savedIds: [] }).map((item) => item.id)).toEqual([102, 202]);
    expect(filterFeedItems(DEMO_FEED, { filter: "event", query: "", savedIds: [] }).map((item) => item.id)).toEqual([103, 203]);
  });

  it("shows only explicitly saved items", () => {
    expect(filterFeedItems(DEMO_FEED, { filter: "saved", query: "", savedIds: [102, 204] }).map((item) => item.id)).toEqual([102, 204]);
  });

  it("searches titles, summaries, insights, sources, and profile elements", () => {
    expect(filterFeedItems(DEMO_FEED, { filter: "all", query: "плавающей ставкой", savedIds: [] }).map((item) => item.id)).toEqual([101]);
    expect(filterFeedItems(DEMO_FEED, { filter: "all", query: "S066", savedIds: [] }).map((item) => item.id)).toEqual([202]);
    expect(filterFeedItems(DEMO_FEED, { filter: "all", query: "сменной работы", savedIds: [] }).map((item) => item.id)).toEqual([203]);
  });

  it("treats a nullable collection as an empty feed", () => {
    expect(filterFeedItems(null, { filter: "all", query: "", savedIds: [] })).toEqual([]);
  });
});
