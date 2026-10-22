// Типы повторяют JSON-модели из backend/internal/domain/models.go.

export type DataMode = "api" | "demo";

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

export type CreateUserInput = Pick<User, "email" | "fullName" | "companyId" | "roles">;

export type CreateCompanyInput = Pick<Company, "inn" | "name">;

export interface DemoAccount {
  userId: number;
  companyId: number;
  email: string;
  password: string;
  scenario: "technology" | "industrial";
  label: string;
  description: string;
}
