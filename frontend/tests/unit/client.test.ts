import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEMO_ACCOUNTS, DEMO_FEED, DEMO_NOW } from "../../src/api/mocks";

async function loadClient() {
  vi.resetModules();
  return import("../../src/api/client");
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("data mode", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([
    ["demo", "demo"],
    ["api", "api"],
    [undefined, "api"],
    [null, "api"],
    ["DEMO", "api"],
    ["unknown", "api"],
  ] as const)("resolves %s to %s", async (value, expected) => {
    const { resolveDataMode } = await loadClient();
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
  ])("normalizes %s to %s", async (value, expected) => {
    const { normalizeFeedLimit } = await loadClient();
    expect(normalizeFeedLimit(value)).toBe(expected);
  });
});

describe("API mode", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("keeps the HTTP status and parsed backend message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: "Сервис временно недоступен" }, 503)));
    const { createApiClient } = await loadClient();
    const api = createApiClient("api");

    await expect(api.roles()).rejects.toEqual(
      expect.objectContaining({
        name: "ApiError",
        message: "Сервис временно недоступен",
        status: 503,
        body: { error: "Сервис временно недоступен" },
      }),
    );
  });

  it("does not replace a network failure with demo data", async () => {
    const failure = new TypeError("network offline");
    const fetchMock = vi.fn().mockRejectedValue(failure);
    vi.stubGlobal("fetch", fetchMock);
    const { createApiClient } = await loadClient();
    const api = createApiClient("api");

    await expect(api.roles()).rejects.toBe(failure);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    "<!doctype html><html><body>Сигнал</body></html>",
    "upstream unavailable",
    "",
    "true",
    '"unexpected string"',
    '{"items": []}',
    '{"error": "backend unavailable"}',
  ])("does not turn a successful non-JSON/invalid payload into an empty feed: %s", async (body) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { createApiClient } = await loadClient();

    await expect(createApiClient("api").feed(1, undefined, 200)).rejects.toEqual(
      expect.objectContaining({ name: "ApiError", status: 200, message: expect.stringContaining("JSON") }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves non-JSON HTTP error messages and their status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("upstream unavailable", { status: 502 })));
    const { createApiClient } = await loadClient();

    await expect(createApiClient("api").feed(1)).rejects.toEqual(
      expect.objectContaining({ name: "ApiError", status: 502, message: "upstream unavailable" }),
    );
  });

  it.each([null, []])("rejects an invalid entity response instead of restoring an incomplete user: %s", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(value)));
    const { createApiClient } = await loadClient();

    await expect(createApiClient("api").user(1)).rejects.toEqual(
      expect.objectContaining({ name: "ApiError", status: 200, message: expect.stringContaining("JSON") }),
    );
  });

  it("normalizes nullable Go collections at the client boundary", async () => {
    const feedItem = {
      id: 10,
      role: "cfo",
      kind: "event",
      score: 0.7,
      insight: "Событие",
      elements: null,
      news: {
        id: 11,
        sourceId: "S001",
        url: "https://example.test/news",
        title: "Новость",
        summary: "Описание",
        publishedAt: DEMO_NOW,
      },
      createdAt: DEMO_NOW,
      readAt: null,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(null))
      .mockResolvedValueOnce(json(null))
      .mockResolvedValueOnce(
        json({ id: 4, companyId: null, email: "a@example.test", fullName: "А", roles: null, createdAt: DEMO_NOW }),
      )
      .mockResolvedValueOnce(json([feedItem]))
      .mockResolvedValueOnce(json(null));
    vi.stubGlobal("fetch", fetchMock);
    const { createApiClient } = await loadClient();
    const api = createApiClient("api");

    await expect(api.roles()).resolves.toEqual([]);
    await expect(api.profileElements()).resolves.toEqual([]);
    await expect(api.user(4)).resolves.toMatchObject({ roles: [] });
    await expect(api.feed(4)).resolves.toEqual([{ ...feedItem, elements: [] }]);
    await expect(api.files(9)).resolves.toEqual([]);
  });

  it("forwards AbortSignal to fetch", async () => {
    const controller = new AbortController();
    controller.abort(new DOMException("cancelled", "AbortError"));
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      expect(init?.signal).toBe(controller.signal);
      return Promise.reject(controller.signal.reason);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { createApiClient } = await loadClient();
    const api = createApiClient("api");

    await expect(api.feed(1, undefined, 200, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("demo mode", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("never uses fetch and exposes distinct company scenarios", async () => {
    const fetchMock = vi.fn(() => {
      throw new Error("demo mode must not access the network");
    });
    vi.stubGlobal("fetch", fetchMock);
    const { createApiClient } = await loadClient();
    const api = createApiClient("demo");

    const [finance, operations, financeFeed, operationsFeed] = await Promise.all([
      api.user(1),
      api.user(2),
      api.feed(1, undefined, 200),
      api.feed(2, undefined, 200),
    ]);

    expect(finance.companyId).toBe(1);
    expect(finance.roles).toEqual(["strategy", "cfo"]);
    expect(operations.companyId).toBe(2);
    expect(operations.roles).toEqual(["procurement", "operations"]);
    expect(financeFeed.map((item) => item.id)).toEqual([101, 102, 103]);
    expect(operationsFeed.map((item) => item.id)).toEqual([201, 202, 203, 204]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps prepared feed fixtures scoped to their company when roles change", async () => {
    const { createApiClient } = await loadClient();
    const api = createApiClient("demo");

    await api.setRoles(1, ["cfo", "operations"]);
    await api.setRoles(2, ["strategy", "operations"]);

    expect((await api.feed(1, undefined, 200)).map((item) => item.id)).toEqual([101, 103]);
    await expect(api.feed(1, "operations", 200)).resolves.toEqual([]);
    expect((await api.feed(2, undefined, 200)).map((item) => item.id)).toEqual([201, 203]);
    await expect(api.feed(2, "strategy", 200)).resolves.toEqual([]);
  });

  it("accepts only published demo credentials without network access", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { demoLogin } = await loadClient();
    const account = DEMO_ACCOUNTS[0];

    await expect(demoLogin(account.email.toUpperCase(), account.password)).resolves.toMatchObject({
      id: account.userId,
      companyId: account.companyId,
      email: account.email,
    });
    await expect(demoLogin(account.email, "wrong password")).rejects.toEqual(
      expect.objectContaining({ status: 401 }),
    );
    await expect(demoLogin("unknown@signal.demo", account.password)).rejects.toEqual(
      expect.objectContaining({ status: 401 }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("registers demo users without accepting or storing a password", async () => {
    const { createApiClient } = await loadClient();
    const api = createApiClient("demo");
    const company = await api.createCompany({ inn: "7812345678", name: "Тестовая компания" });
    const user = await api.createUser({
      companyId: company.id,
      email: "new@signal.demo",
      fullName: "Новый пользователь",
      roles: ["sales"],
    });

    expect(user.email).toBe("new@signal.demo");
    await expect(api.feed(user.id, undefined, 200)).resolves.toEqual([]);
    const stored = localStorage.getItem("signal.demo-api.v2") ?? "";
    expect(stored).not.toContain("SignalDemo2026!");
    expect(stored).not.toContain("password");
  });

  it("keeps every prepared dashboard event inside the fixed 24-hour window", () => {
    const now = Date.parse(DEMO_NOW);
    for (const item of DEMO_FEED) {
      const age = now - Date.parse(item.createdAt);
      expect(age).toBeGreaterThanOrEqual(0);
      expect(age).toBeLessThanOrEqual(24 * 60 * 60 * 1_000);
    }
  });

  it("honors an already aborted demo request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    controller.abort(new DOMException("cancelled", "AbortError"));
    const { createApiClient } = await loadClient();
    const api = createApiClient("demo");

    await expect(api.feed(1, undefined, 200, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
