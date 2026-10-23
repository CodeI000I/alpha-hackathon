// Типы повторяют JSON-модели из backend/internal/domain/models.go.

export interface Role {
  id: number;
  code: string;
  name: string;
  question: string;
  focus: string;
  elements: string[];
}

export interface ProfileElement {
  code: string;
  block: string;
  name: string;
  description: string;
  purpose: string;
}

export interface User {
  id: number;
  companyId: number | null;
  email: string;
  fullName: string;
  roles: string[];
  createdAt: string;
}

export interface Company {
  id: number;
  inn: string;
  ogrn: string;
  name: string;
  profile: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface OnboardingRequest {
  company: Pick<Company, "inn" | "name"> & { ogrn?: string };
  user: Pick<User, "email" | "fullName" | "roles">;
}

export interface OnboardingResponse {
  company: Company;
  user: User;
}

export interface NewsItem {
  id: number;
  sourceId: string;
  url: string;
  title: string;
  summary: string;
  publishedAt: string;
}

export type FeedKind = "event" | "risk" | "opportunity";

export interface FeedItem {
  id: number;
  role: string;
  kind: FeedKind;
  score: number;
  insight: string;
  elements: string[];
  news: NewsItem;
  createdAt: string;
  readAt: string | null;
}

export interface CompanyFile {
  id: number;
  companyId: number;
  filename: string;
  contentType: string;
  sizeBytes: number;
  createdAt: string;
}
