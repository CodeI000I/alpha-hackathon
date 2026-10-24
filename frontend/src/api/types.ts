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

export interface OnboardingRequest {
  company: Pick<Company, "inn" | "name"> & { ogrn?: string };
  user: Pick<User, "email" | "fullName" | "roles"> & { password: string };
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

export type AnalyticsEffect = "risk" | "opportunity" | "mixed" | "neutral" | "unknown";
export interface BusinessIssue {
  issue_id: string;
  title: string;
  summary: string;
  overall_effect: AnalyticsEffect;
  evidence_sufficiency: "sufficient" | "conditional" | "insufficient" | "conflicting";
  key_unknowns: string[];
  conditions: string[];
  suggested_action: string;
  business_factors: string[];
  exposure: string;
  horizon: string;
  event_ids: string[];
  status: "active" | "watching" | "resolved" | "superseded" | "archived";
  urgency: "none" | "monitor" | "soon" | "immediate" | "unknown";
  impact_magnitude: "low" | "medium" | "high" | "unknown";
  version: number;
  as_of: string;
}

export interface CompanySituation {
  snapshot: null | {
    snapshot_id: string;
    as_of: string;
    overall: { summary: string; key_unknowns: string[]; actions: string[] };
    priority_issues: Array<Record<string, unknown>>;
    changes_since_previous: Array<Record<string, string>>;
  };
  current: boolean;
  status: string;
}

export interface AnalyticsEvidencePack {
  event: { event_id: string; summary: string; evidence_quote: string; source_news_ids: string[]; modality: string };
  news: Array<{ title: string; content: string; source_url: string | null; published_at: string }>;
  company_facts: Array<{ fact_id: string; text: string; source_quote: string; source_refs: string[]; verification_status: string }>;
  chunks: Array<{ chunk_id: string; document_id: string; locator: string; text: string }>;
  candidate_paths: Array<{ path_id: string; node_ids: string[]; relation_types: string[]; evidence_refs: string[]; status: string }>;
}

export interface AnalyticsUserState {
  issue_id: string;
  workflow: "open" | "watching" | "closed";
  pinned: boolean;
  read_version: number | null;
  unread: boolean;
}

export interface AnalyticsConversation {
  issue_id: string;
  issue_version: number;
  replies: Array<{ request_id: string; question: string; answer: { text: string; evidence_ids: string[]; missing_facts: string[] }; created_at: string }>;
}

export interface AnalyticsJob {
  job_id: string;
  status: string;
  [key: string]: unknown;
}

export interface AnalyticsDocument {
  file_id: string | number;
  filename: string;
  document_id: string | null;
  status: "queued" | "ready" | "failed";
  attempts: number;
  error: string | null;
  retry_at: number | null;
}
