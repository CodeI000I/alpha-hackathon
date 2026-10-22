import { demoStore, DemoStoreError } from "./demoStore";
import { DEMO_ACCOUNTS } from "./mocks";
import type {
  Company,
  CompanyFile,
  CreateCompanyInput,
  CreateUserInput,
  DataMode,
  FeedItem,
  ProfileElement,
  Role,
  User,
} from "./types";

const BASE = "/api/v1";
const DEFAULT_FEED_LIMIT = 50;
const MAX_FEED_LIMIT = 200;

export type SignalInput = AbortSignal | { readonly signal?: AbortSignal };

export function resolveDataMode(value: unknown): DataMode {
  return value === "demo" ? "demo" : "api";
}

const configuredDataMode = (
  import.meta as ImportMeta & { env?: { readonly VITE_DATA_MODE?: string } }
).env?.VITE_DATA_MODE;

export const dataMode: DataMode = resolveDataMode(configuredDataMode);
export const isDemoMode = dataMode === "demo";

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type WireRole = Omit<Role, "elements"> & { elements: string[] | null };
type WireUser = Omit<User, "roles"> & { roles: string[] | null };
type WireFeedItem = Omit<FeedItem, "elements"> & { elements: string[] | null };
type WireCompany = Omit<Company, "profile"> & { profile: Record<string, unknown> | null };

function normalizeCollection<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function normalizeRole(role: WireRole | Role): Role {
  return { ...role, elements: normalizeCollection(role.elements) };
}

function normalizeRoles(roles: Array<WireRole | Role> | null | undefined): Role[] {
  return normalizeCollection(roles).map(normalizeRole);
}

function normalizeUser(user: WireUser | User): User {
  return { ...user, roles: normalizeCollection(user.roles) };
}

function normalizeFeed(items: Array<WireFeedItem | FeedItem> | null | undefined): FeedItem[] {
  return normalizeCollection(items).map((item) => ({ ...item, elements: normalizeCollection(item.elements) }));
}

function normalizeCompany(company: WireCompany | Company): Company {
  return { ...company, profile: company.profile ?? {} };
}

function toAbortSignal(input?: SignalInput): AbortSignal | undefined {
  if (!input) return undefined;
  if ("signal" in input) return (input as { readonly signal?: AbortSignal }).signal;
  return input as AbortSignal;
}

function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null) {
    const candidate = body as { error?: unknown; message?: unknown };
    if (typeof candidate.error === "string" && candidate.error) return candidate.error;
    if (typeof candidate.message === "string" && candidate.message) return candidate.message;
  }
  if (typeof body === "string" && body.trim()) return body.trim();
  return fallback || "Ошибка запроса";
}

async function responseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body !== undefined && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(BASE + path, { ...init, headers });
  const body = await responseBody(response);
  if (!response.ok) {
    throw new ApiError(errorMessage(body, response.statusText), response.status, body);
  }
  return body as T;
}

function abortReason(signal: AbortSignal): Error {
  if (signal.reason instanceof Error) return signal.reason;
  const error = new Error("Запрос отменён");
  error.name = "AbortError";
  return error;
}

async function demoCall<T>(operation: () => T, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) throw abortReason(signal);
  await Promise.resolve();
  if (signal?.aborted) throw abortReason(signal);
  try {
    return operation();
  } catch (error) {
    if (error instanceof DemoStoreError) {
      throw new ApiError(error.message, error.status, { error: error.message });
    }
    throw error;
  }
}

export function normalizeFeedLimit(limit: number | undefined): number {
  if (limit === undefined || !Number.isFinite(limit)) return DEFAULT_FEED_LIMIT;
  return Math.min(MAX_FEED_LIMIT, Math.max(1, Math.floor(limit)));
}

export async function demoLogin(email: string, password: string, signalInput?: SignalInput): Promise<User> {
  const signal = toAbortSignal(signalInput);
  const normalizedEmail = email.trim().toLocaleLowerCase("en-US");
  const account = DEMO_ACCOUNTS.find(
    (candidate) => candidate.email.toLocaleLowerCase("en-US") === normalizedEmail && candidate.password === password,
  );
  return demoCall(() => {
    if (!account) throw new DemoStoreError(401, "Неверная электронная почта или пароль");
    return normalizeUser(demoStore.user(account.userId));
  }, signal);
}

function feedPath(userId: number, role: string | undefined, limit: number): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (role) params.set("role", role);
  return `/users/${userId}/feed?${params.toString()}`;
}

export function createApiClient(mode: DataMode = dataMode) {
  return {
    roles(signalInput?: SignalInput): Promise<Role[]> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeRoles(demoStore.roles()), signal)
        : request<WireRole[] | null>("/roles", { signal }).then(normalizeRoles);
    },

    profileElements(signalInput?: SignalInput): Promise<ProfileElement[]> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeCollection(demoStore.profileElements()), signal)
        : request<ProfileElement[] | null>("/profile-elements", { signal }).then(normalizeCollection);
    },

    user(id: number, signalInput?: SignalInput): Promise<User> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeUser(demoStore.user(id)), signal)
        : request<WireUser>(`/users/${id}`, { signal }).then(normalizeUser);
    },

    createUser(input: CreateUserInput, signalInput?: SignalInput): Promise<User> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeUser(demoStore.createUser(input)), signal)
        : request<WireUser>("/users", { method: "POST", body: JSON.stringify(input), signal }).then(normalizeUser);
    },

    setRoles(id: number, roles: string[], signalInput?: SignalInput): Promise<User> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeUser(demoStore.setRoles(id, roles)), signal)
        : request<WireUser>(`/users/${id}/roles`, {
            method: "PUT",
            body: JSON.stringify({ roles }),
            signal,
          }).then(normalizeUser);
    },

    feed(id: number, role?: string, limit?: number, signal?: AbortSignal): Promise<FeedItem[]> {
      const normalizedLimit = normalizeFeedLimit(limit);
      return mode === "demo"
        ? demoCall(() => normalizeFeed(demoStore.feed(id, role, normalizedLimit)), signal)
        : request<WireFeedItem[] | null>(feedPath(id, role, normalizedLimit), { signal }).then(normalizeFeed);
    },

    company(id: number, signalInput?: SignalInput): Promise<Company> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeCompany(demoStore.company(id)), signal)
        : request<WireCompany>(`/companies/${id}`, { signal }).then(normalizeCompany);
    },

    createCompany(input: CreateCompanyInput, signalInput?: SignalInput): Promise<Company> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeCompany(demoStore.createCompany(input)), signal)
        : request<WireCompany>("/companies", { method: "POST", body: JSON.stringify(input), signal }).then(
            normalizeCompany,
          );
    },

    patchProfile(id: number, patch: Record<string, unknown>, signalInput?: SignalInput): Promise<Company> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeCompany(demoStore.patchProfile(id, patch)), signal)
        : request<WireCompany>(`/companies/${id}/profile`, {
            method: "PATCH",
            body: JSON.stringify(patch),
            signal,
          }).then(normalizeCompany);
    },

    files(id: number, signalInput?: SignalInput): Promise<CompanyFile[]> {
      const signal = toAbortSignal(signalInput);
      return mode === "demo"
        ? demoCall(() => normalizeCollection(demoStore.files(id)), signal)
        : request<CompanyFile[] | null>(`/companies/${id}/files`, { signal }).then(normalizeCollection);
    },

    uploadFile(id: number, file: File, signalInput?: SignalInput): Promise<CompanyFile> {
      const signal = toAbortSignal(signalInput);
      if (mode === "demo") return demoCall(() => demoStore.uploadFile(id, file), signal);
      const form = new FormData();
      form.append("file", file);
      return request<CompanyFile>(`/companies/${id}/files`, { method: "POST", body: form, signal });
    },
  };
}

export const api = createApiClient();
