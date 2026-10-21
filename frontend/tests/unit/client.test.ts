import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, normalizeFeedLimit, resolveDataMode } from "../../src/api/client";

describe("data mode", () => {
  it.each([
    ["demo", "demo"],
    ["api", "api"],
    [undefined, "api"],
    [null, "api"],
    ["DEMO", "api"],
    ["unknown", "api"],
  ] as const)("resolves %s to %s", (value, expected) => {
    expect(resolveDataMode(value)).toBe(expected);
  });
});

describe("feed limits", () => {
  it.each([
    [undefined, 50],
    [Number.NaN, 50],
    [Number.POSITIVE_INFINITY, 50],
    [-10, 1],
    [0, 1],
    [1.9, 1],
    [75, 75],
    [200, 200],
    [201, 200],
  ])("normalizes %s to %s", (value, expected) => {
    expect(normalizeFeedLimit(value)).toBe(expected);
  });
});

describe("API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the HTTP status and parsed backend message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Сервис временно недоступен" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const request = api.roles();

    await expect(request).rejects.toMatchObject<ApiError>({
      name: "ApiError",
      message: "Сервис временно недоступен",
      status: 503,
      body: { error: "Сервис временно недоступен" },
    });
  });
});
