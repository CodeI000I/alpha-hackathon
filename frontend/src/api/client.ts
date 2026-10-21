import { demoStore, DemoStoreError } from "./demoStore";
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

const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;

export const dataMode: DataMode = resolveDataMode(env?.VITE_DATA_MODE);
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

function feedPath(userId: number, role: string | undefined, limit: number): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (role) params.set("role", role);
  return `/users/${userId}/feed?${params.toString()}`;
}

export const api = {
  roles(signalInput?: SignalInput): Promise<Role[]> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo" ? demoCall(() => demoStore.roles(), signal) : request<Role[]>("/roles", { signal });
  },

  profileElements(signalInput?: SignalInput): Promise<ProfileElement[]> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.profileElements(), signal)
      : request<ProfileElement[]>("/profile-elements", { signal });
  },

  user(id: number, signalInput?: SignalInput): Promise<User> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo" ? demoCall(() => demoStore.user(id), signal) : request<User>(`/users/${id}`, { signal });
  },

  createUser(input: CreateUserInput, signalInput?: SignalInput): Promise<User> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.createUser(input), signal)
      : request<User>("/users", { method: "POST", body: JSON.stringify(input), signal });
  },

  setRoles(id: number, roles: string[], signalInput?: SignalInput): Promise<User> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.setRoles(id, roles), signal)
      : request<User>(`/users/${id}/roles`, {
          method: "PUT",
          body: JSON.stringify({ roles }),
          signal,
        });
  },

  feed(id: number, role?: string, limit?: number, signal?: AbortSignal): Promise<FeedItem[]> {
    const normalizedLimit = normalizeFeedLimit(limit);
    return dataMode === "demo"
      ? demoCall(() => demoStore.feed(id, role, normalizedLimit), signal)
      : request<FeedItem[]>(feedPath(id, role, normalizedLimit), { signal });
  },

  company(id: number, signalInput?: SignalInput): Promise<Company> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.company(id), signal)
      : request<Company>(`/companies/${id}`, { signal });
  },

  createCompany(input: CreateCompanyInput, signalInput?: SignalInput): Promise<Company> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.createCompany(input), signal)
      : request<Company>("/companies", { method: "POST", body: JSON.stringify(input), signal });
  },

  patchProfile(id: number, patch: Record<string, unknown>, signalInput?: SignalInput): Promise<Company> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.patchProfile(id, patch), signal)
      : request<Company>(`/companies/${id}/profile`, {
          method: "PATCH",
          body: JSON.stringify(patch),
          signal,
        });
  },

  files(id: number, signalInput?: SignalInput): Promise<CompanyFile[]> {
    const signal = toAbortSignal(signalInput);
    return dataMode === "demo"
      ? demoCall(() => demoStore.files(id), signal)
      : request<CompanyFile[]>(`/companies/${id}/files`, { signal });
  },

  uploadFile(id: number, file: File, signalInput?: SignalInput): Promise<CompanyFile> {
    const signal = toAbortSignal(signalInput);
    if (dataMode === "demo") return demoCall(() => demoStore.uploadFile(id, file), signal);
    const form = new FormData();
    form.append("file", file);
    return request<CompanyFile>(`/companies/${id}/files`, { method: "POST", body: form, signal });
  },
};
