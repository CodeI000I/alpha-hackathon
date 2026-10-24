import { dataMode } from "../api/client";
import type { DataMode } from "../api/types";

export interface OnboardingForm { fullName: string; email: string; companyName: string; inn: string }
export interface OnboardingDraft { form: OnboardingForm; selectedRoles: string[]; step: 1 | 2 }
export const emptyOnboardingForm: OnboardingForm = { fullName: "", email: "", companyName: "", inn: "" };

export function validateRegistrationIdentity(form: Pick<OnboardingForm, "fullName" | "email">): Partial<Record<"fullName" | "email", string>> {
  const errors: Partial<Record<"fullName" | "email", string>> = {};
  if (!form.fullName.trim()) errors.fullName = "Укажите имя.";
  else if (form.fullName.trim().length > 120) errors.fullName = "Не больше 120 символов.";
  if (!/^\S+@\S+\.\S+$/.test(form.email.trim())) errors.email = "Укажите корректную электронную почту.";
  return errors;
}

function draftKey(mode: DataMode): string { return `signal.registration-draft.v1.${mode}`; }
function normalizeDraft(value: unknown): OnboardingDraft | null {
  if (!value || typeof value !== "object") return null;
  const draft = value as Partial<OnboardingDraft>;
  if (!draft.form || typeof draft.form !== "object") return null;
  const fields = ["fullName", "email", "companyName", "inn"] as const;
  if (fields.some((key) => typeof draft.form?.[key] !== "string")) return null;
  const form: OnboardingForm = {
    fullName: draft.form.fullName.slice(0, 120), email: draft.form.email.slice(0, 320),
    companyName: draft.form.companyName.slice(0, 160), inn: draft.form.inn.replace(/\D/g, "").slice(0, 12),
  };
  const selectedRoles = Array.isArray(draft.selectedRoles)
    ? [...new Set(draft.selectedRoles.filter((role): role is string => typeof role === "string" && role.length > 0 && role.length <= 100))].slice(0, 100)
    : [];
  // A forged or stale second-step marker cannot skip the identity fields.
  const step = draft.step === 2 && Object.keys(validateRegistrationIdentity(form)).length === 0 ? 2 : 1;
  return { form, selectedRoles, step };
}

export function readOnboardingDraft(mode: DataMode = dataMode): OnboardingDraft | null {
  try { const raw = sessionStorage.getItem(draftKey(mode)); return raw ? normalizeDraft(JSON.parse(raw)) : null; } catch { return null; }
}
export function saveOnboardingDraft(draft: OnboardingDraft, mode: DataMode = dataMode): void {
  const safe = normalizeDraft(draft);
  if (!safe) return;
  // Only the explicit form fields are serialized. Never a password or arbitrary input.
  try { sessionStorage.setItem(draftKey(mode), JSON.stringify(safe)); } catch { /* Registration still works without draft storage. */ }
}
export function clearOnboardingDraft(mode: DataMode = dataMode): void {
  try { sessionStorage.removeItem(draftKey(mode)); } catch { /* Storage may be unavailable. */ }
}

function requestKeyStorageKey(mode: DataMode): string { return `signal.registration-request.v1.${mode}`; }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function newRequestKey(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function getOnboardingRequestKey(mode: DataMode = dataMode): string {
  const key = requestKeyStorageKey(mode);
  try {
    const saved = localStorage.getItem(key);
    if (saved && UUID.test(saved)) return saved;
    const generated = newRequestKey();
    localStorage.setItem(key, generated);
    return generated;
  } catch {
    return newRequestKey();
  }
}

export function clearOnboardingRequestKey(mode: DataMode = dataMode): void {
  try { localStorage.removeItem(requestKeyStorageKey(mode)); } catch { /* Storage may be unavailable. */ }
}
