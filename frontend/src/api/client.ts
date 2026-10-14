import type { Company, CompanyFile, FeedItem, ProfileElement, Role, User } from "./types";

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
  createUser: (u: Pick<User, "email" | "fullName" | "companyId" | "roles">) =>
    request<User>("/users", { method: "POST", body: JSON.stringify(u) }),
  setRoles: (id: number, roles: string[]) =>
    request<User>(`/users/${id}/roles`, { method: "PUT", body: JSON.stringify({ roles }) }),
  feed: (id: number, role?: string) =>
    request<FeedItem[]>(`/users/${id}/feed${role ? `?role=${encodeURIComponent(role)}` : ""}`),

  company: (id: number) => request<Company>(`/companies/${id}`),
  createCompany: (c: Pick<Company, "inn" | "name">) =>
    request<Company>("/companies", { method: "POST", body: JSON.stringify(c) }),
  patchProfile: (id: number, patch: Record<string, unknown>) =>
    request<Company>(`/companies/${id}/profile`, { method: "PATCH", body: JSON.stringify(patch) }),
  files: (id: number) => request<CompanyFile[]>(`/companies/${id}/files`),
  uploadFile: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CompanyFile>(`/companies/${id}/files`, { method: "POST", body: form });
  },
};
