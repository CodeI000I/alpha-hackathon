import type { Company, CompanyFile, FeedItem, OnboardingRequest, OnboardingResponse, ProfileElement, Role, User } from "./types";

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  roles: () => request<Role[]>("/roles"),
  profileElements: () => request<ProfileElement[]>("/profile-elements"),

  user: (id: number) => request<User>(`/users/${id}`),
  onboard: (body: OnboardingRequest, idempotencyKey: string) =>
    request<OnboardingResponse>("/onboarding", {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(body),
    }),
  setRoles: (id: number, roles: string[]) =>
    request<User>(`/users/${id}/roles`, { method: "PUT", body: JSON.stringify({ roles }) }),
  feed: (id: number, role?: string) =>
    request<FeedItem[]>(`/users/${id}/feed${role ? `?role=${encodeURIComponent(role)}` : ""}`),

  company: (id: number) => request<Company>(`/companies/${id}`),
  patchProfile: (id: number, patch: Record<string, unknown>) =>
    request<Company>(`/companies/${id}/profile`, { method: "PATCH", body: JSON.stringify(patch) }),
  files: (id: number) => request<CompanyFile[]>(`/companies/${id}/files`),
  uploadFile: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CompanyFile>(`/companies/${id}/files`, { method: "POST", body: form });
  },
};
