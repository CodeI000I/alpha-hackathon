import {
  DEMO_COMPANIES,
  DEMO_FEED,
  DEMO_FEED_ITEM_IDS_BY_COMPANY,
  DEMO_FILES,
  DEMO_NOW,
  DEMO_PROFILE_ELEMENTS,
  DEMO_ROLES,
  DEMO_USERS,
} from "./mocks";
import type {
  Company,
  CompanyFile,
  CreateCompanyInput,
  CreateUserInput,
  FeedItem,
  ProfileElement,
  Role,
  User,
} from "./types";

const STORAGE_KEY = "signal.demo-api.v2";
const FIXED_TIME = Date.parse(DEMO_NOW);

interface DemoState {
  version: 2;
  companies: Company[];
  users: User[];
  files: CompanyFile[];
}

export class DemoStoreError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "DemoStoreError";
    this.status = status;
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function initialState(): DemoState {
  return {
    version: 2,
    companies: clone(DEMO_COMPANIES),
    users: clone(DEMO_USERS),
    files: clone(DEMO_FILES),
  };
}

let memoryState = initialState();

function isDemoState(value: unknown): value is DemoState {
  if (typeof value !== "object" || value === null) return false;
  const state = value as Partial<DemoState>;
  return state.version === 2 && Array.isArray(state.companies) && Array.isArray(state.users) && Array.isArray(state.files);
}

function readState(): DemoState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return clone(memoryState);
    const stored: unknown = JSON.parse(raw);
    if (isDemoState(stored)) {
      memoryState = clone(stored);
      return clone(stored);
    }
  } catch {
    // localStorage недоступен (например, SSR или строгий privacy mode) — остаёмся в памяти.
  }
  return clone(memoryState);
}

function writeState(state: DemoState): void {
  memoryState = clone(state);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // In-memory store сохраняет работоспособность деморежима в этой вкладке.
  }
}

function nextId(items: Array<{ id: number }>): number {
  return items.reduce((max, item) => Math.max(max, item.id), 0) + 1;
}

function createdAt(id: number): string {
  return new Date(FIXED_TIME + id * 60_000).toISOString();
}

function roleCodes(codes: string[]): string[] {
  const requested = new Set(codes);
  return DEMO_ROLES.filter((role) => requested.has(role.code)).map((role) => role.code);
}

function requireUser(state: DemoState, id: number): User {
  const user = state.users.find((candidate) => candidate.id === id);
  if (!user) throw new DemoStoreError(404, "Пользователь не найден");
  return user;
}

function requireCompany(state: DemoState, id: number): Company {
  const company = state.companies.find((candidate) => candidate.id === id);
  if (!company) throw new DemoStoreError(404, "Компания не найдена");
  return company;
}

export const demoStore = {
  roles(): Role[] {
    return clone(DEMO_ROLES);
  },

  profileElements(): ProfileElement[] {
    return clone(DEMO_PROFILE_ELEMENTS);
  },

  user(id: number): User {
    return clone(requireUser(readState(), id));
  },

  createUser(input: CreateUserInput): User {
    const state = readState();
    if (!input.email.trim() || !input.fullName.trim()) {
      throw new DemoStoreError(400, "Email и имя обязательны");
    }
    if (input.companyId !== null) requireCompany(state, input.companyId);
    const id = nextId(state.users);
    const user: User = {
      id,
      companyId: input.companyId,
      email: input.email.trim(),
      fullName: input.fullName.trim(),
      roles: roleCodes(input.roles),
      createdAt: createdAt(id),
    };
    state.users.push(user);
    writeState(state);
    return clone(user);
  },

  setRoles(id: number, codes: string[]): User {
    const state = readState();
    const user = requireUser(state, id);
    user.roles = roleCodes(codes);
    writeState(state);
    return clone(user);
  },

  feed(id: number, role: string | undefined, limit: number): FeedItem[] {
    const state = readState();
    const user = requireUser(state, id);
    const allowedRoles = new Set(user.roles);
    const companyFeedIds = new Set(
      user.companyId === null ? [] : (DEMO_FEED_ITEM_IDS_BY_COMPANY[user.companyId] ?? []),
    );
    return clone(
      DEMO_FEED.filter(
        (item) => companyFeedIds.has(item.id) && allowedRoles.has(item.role) && (!role || item.role === role),
      ).slice(0, limit),
    );
  },

  company(id: number): Company {
    return clone(requireCompany(readState(), id));
  },

  createCompany(input: CreateCompanyInput): Company {
    const state = readState();
    if (!input.inn.trim() || !input.name.trim()) {
      throw new DemoStoreError(400, "ИНН и название компании обязательны");
    }
    const id = nextId(state.companies);
    const timestamp = createdAt(id);
    const company: Company = {
      id,
      inn: input.inn.trim(),
      ogrn: "",
      name: input.name.trim(),
      profile: {},
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    state.companies.push(company);
    writeState(state);
    return clone(company);
  },

  patchProfile(id: number, patch: Record<string, unknown>): Company {
    const state = readState();
    const company = requireCompany(state, id);
    company.profile = { ...company.profile, ...clone(patch) };
    company.updatedAt = createdAt(id + Object.keys(company.profile).length);
    writeState(state);
    return clone(company);
  },

  files(companyId: number): CompanyFile[] {
    const state = readState();
    requireCompany(state, companyId);
    return clone(
      state.files
        .filter((file) => file.companyId === companyId)
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt)),
    );
  },

  uploadFile(companyId: number, file: File): CompanyFile {
    const state = readState();
    requireCompany(state, companyId);
    if (!file.name) throw new DemoStoreError(400, "Выберите файл");
    if (file.size > 50 * 1024 * 1024) throw new DemoStoreError(400, "Файл не должен превышать 50 МБ");
    const id = nextId(state.files);
    const companyFile: CompanyFile = {
      id,
      companyId,
      filename: file.name,
      contentType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      createdAt: createdAt(id),
    };
    state.files.push(companyFile);
    writeState(state);
    return clone(companyFile);
  },
};
